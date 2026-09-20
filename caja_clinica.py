import os
import time
import psycopg2
from datetime import datetime
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse 
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from contextlib import contextmanager

# ==========================================
# CONFIGURACIÓN Y VARIABLES DE ENTORNO
# ==========================================
CLINIC_NAME = os.getenv("CLINIC_NAME")
PRIMARY_COLOR = os.getenv("PRIMARY_COLOR", "#10b981") 
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
SESSION_SECRET = os.getenv("SESSION_SECRET")

app = FastAPI(title="Control de Caja")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Configuración segura de cookies de sesión
app.add_middleware(
    SessionMiddleware, 
    secret_key=SESSION_SECRET,
    session_cookie="session_caja",
    same_site="lax",
    https_only=True  # Garantiza transmisión encriptada bajo HTTPS
)

templates = Jinja2Templates(directory="templates")
templates.env.globals["CLINIC_NAME"] = CLINIC_NAME
templates.env.globals["PRIMARY_COLOR"] = PRIMARY_COLOR

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ==========================================
# GESTIÓN SEGURA DE BASE DE DATOS
# ==========================================
@contextmanager
def obtener_conexion():
    """
    Context Manager para asegurar que las conexiones a Neon 
    se cierren siempre correctamente, incluso si ocurre un error.
    """
    conexion = psycopg2.connect(DATABASE_URL)
    try:
        yield conexion
    finally:
        conexion.close()

def inicializar_bd():
    """Crea la estructura base de la tabla si no existe al iniciar."""
    if not DATABASE_URL:
        return
    try:
        with obtener_conexion() as conexion:
            with conexion.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS flujo_caja (
                        id SERIAL PRIMARY KEY,
                        tipo VARCHAR(10) NOT NULL,       
                        concepto TEXT NOT NULL,          
                        categoria VARCHAR(100) NOT NULL, 
                        monto REAL NOT NULL,
                        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        tipo_gasto VARCHAR(20) DEFAULT 'OPERATIVO',
                        metodo VARCHAR(20) DEFAULT 'EFECTIVO',
                        socio VARCHAR(50) DEFAULT 'AMBOS'
                    );
                """)
                conexion.commit()
    except Exception as e:
        print(f"Error al conectar con Neon: {e}")

@app.on_event("startup")
def startup_event():
    inicializar_bd()

# ==========================================
# FUNCIONES AUXILIARES Y LÓGICA DE NEGOCIO
# ==========================================
def usuario_autenticado(request: Request) -> bool:
    """Verifica si el usuario actual tiene una sesión activa."""
    return request.session.get("autenticado") == True

def obtener_reporte_mensual():
    """Genera el resumen de ingresos, egresos y utilidad por mes."""
    if not DATABASE_URL: return []
    with obtener_conexion() as conexion:
        with conexion.cursor() as cursor:
            cursor.execute("""
                SELECT TO_CHAR(fecha AT TIME ZONE 'UTC' AT TIME ZONE 'America/Mexico_City', 'YYYY-MM') as mes,
                       SUM(CASE WHEN tipo = 'INGRESO' THEN monto ELSE 0 END) as ingresos,
                       SUM(CASE WHEN tipo = 'EGRESO' THEN monto ELSE 0 END) as egresos
                FROM flujo_caja 
                GROUP BY mes 
                ORDER BY mes DESC;
            """)
            filas = cursor.fetchall()
            return [{"periodo": r[0], "ingresos": r[1] or 0, "egresos": r[2] or 0, "ganancia": (r[1] or 0) - (r[2] or 0)} for r in filas]

def obtener_reporte_semanal():
    """Genera el resumen de ingresos, egresos y utilidad por semana ISO."""
    if not DATABASE_URL: return []
    with obtener_conexion() as conexion:
        with conexion.cursor() as cursor:
            cursor.execute("""
                SELECT TO_CHAR(fecha AT TIME ZONE 'UTC' AT TIME ZONE 'America/Mexico_City', 'IYYY-"W"IW') as semana,
                       SUM(CASE WHEN tipo = 'INGRESO' THEN monto ELSE 0 END),
                       SUM(CASE WHEN tipo = 'EGRESO' THEN monto ELSE 0 END)
                FROM flujo_caja 
                GROUP BY semana 
                ORDER BY semana DESC;
            """)
            filas = cursor.fetchall()
            return [{"periodo": r[0], "ingresos": r[1] or 0, "egresos": r[2] or 0, "ganancia": (r[1] or 0) - (r[2] or 0)} for r in filas]

def calcular_deuda_directa():
    if not DATABASE_URL:
        return {"inv_paola": 0, "inv_jorge": 0, "deuda_jorge": 0, "deuda_paola": 0}
        
    with obtener_conexion() as conexion:
        with conexion.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    COALESCE(SUM(CASE WHEN socio = 'PAOLA' THEN monto ELSE 0 END), 0) as pagado_paola,
                    COALESCE(SUM(CASE WHEN socio = 'JORGE' THEN monto ELSE 0 END), 0) as pagado_jorge
                FROM flujo_caja 
                WHERE tipo = 'EGRESO';
            """)
            res = cursor.fetchone()
            pagado_paola = res[0]
            pagado_jorge = res[1]
            
            # Aplica la regla 50/50: divide la diferencia entre 2
            diferencia_deuda = (pagado_paola - pagado_jorge) / 2.0
            
            return {
                "inv_paola": pagado_paola,
                "inv_jorge": pagado_jorge,
                "deuda_jorge": diferencia_deuda if diferencia_deuda > 0 else 0,
                "deuda_paola": abs(diferencia_deuda) if diferencia_deuda < 0 else 0
            }

# ==========================================
# RUTAS DE AUTENTICACIÓN
# ==========================================
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if usuario_autenticado(request):
        return RedirectResponse(url="/", status_code=303)
    error = request.session.pop("error_login", None)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": error})

@app.post("/login")
async def login_action(request: Request, password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        request.session["autenticado"] = True
        return RedirectResponse(url="/", status_code=303)
    else:
        # Mitigación básica contra ataques de fuerza bruta por tiempo
        time.sleep(1)
        request.session["error_login"] = "❌ Contraseña incorrecta"
        return RedirectResponse(url="/login", status_code=303)

@app.get("/logout")
async def logout_action(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)

# ==========================================
# RUTAS PRINCIPALES DE OPERACIÓN
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def panel_principal(request: Request):
    if not usuario_autenticado(request):
        return RedirectResponse(url="/login", status_code=303)
        
    reporte_mes = obtener_reporte_mensual()
    reporte_semana = obtener_reporte_semanal()
    cuentas = calcular_deuda_directa()
    
    movimientos = []
    if DATABASE_URL:
        with obtener_conexion() as conexion:
            with conexion.cursor() as cursor:
                cursor.execute("""
                    SELECT id, tipo, concepto, categoria, monto, 
                    (fecha AT TIME ZONE 'UTC' AT TIME ZONE 'America/Mexico_City'),
                    metodo, tipo_gasto, socio
                    FROM flujo_caja ORDER BY fecha DESC LIMIT 15
                """)
                movimientos = cursor.fetchall()
    
    mensaje = request.session.pop("mensaje_flash", None)
    
    return templates.TemplateResponse(
        request=request, 
        name="control_caja.html", 
        context={
            "reporte_mensual": reporte_mes, 
            "reporte_semanal": reporte_semana, 
            "cuentas": cuentas,
            "movimientos": movimientos, 
            "mensaje": mensaje
        }
    )

@app.post("/guardar-movimiento")
async def guardar_movimiento(
    request: Request, 
    tipo: str = Form(...), 
    metodo: str = Form(...),
    tipo_gasto: str = Form(...),
    socio: str = Form(...),
    concepto: str = Form(...), 
    categoria: str = Form(...), 
    monto: float = Form(...),
    fecha: str = Form(...) 
):
    if not usuario_autenticado(request):
        return RedirectResponse(url="/login", status_code=303)
        
    # Sanitización / Validación de valores de entrada (Lista Blanca)
    if metodo not in ["EFECTIVO", "TRANSFERENCIA", "DEBITO", "CREDITO"]: metodo = "EFECTIVO"
    if tipo_gasto not in ["OPERATIVO", "INVERSION"]: tipo_gasto = "OPERATIVO"
    if socio not in ["AMBOS", "PAOLA", "JORGE"]: socio = "AMBOS"
        
    with obtener_conexion() as conexion:
        with conexion.cursor() as cursor:
            cursor.execute("""
                INSERT INTO flujo_caja (fecha, tipo, metodo, tipo_gasto, socio, concepto, categoria, monto) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (fecha, tipo.upper(), metodo, tipo_gasto, socio, concepto, categoria, monto))
            conexion.commit()
    
    request.session["mensaje_flash"] = "✅ Registro guardado correctamente"
    return RedirectResponse(url="/", status_code=303)

@app.post("/arqueo")
async def realizar_arqueo(request: Request, fecha_arqueo: str = Form(...), monto_fisico: float = Form(...)):
    """Verifica el total en efectivo acumulado en una fecha contra el dinero físico."""
    if not usuario_autenticado(request):
        return RedirectResponse(url="/login", status_code=303)
        
    with obtener_conexion() as conexion:
        with conexion.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    COALESCE(SUM(CASE WHEN tipo = 'INGRESO' THEN monto ELSE 0 END), 0) -
                    COALESCE(SUM(CASE WHEN tipo = 'EGRESO' THEN monto ELSE 0 END), 0)
                FROM flujo_caja
                WHERE metodo = 'EFECTIVO' AND DATE(fecha AT TIME ZONE 'UTC' AT TIME ZONE 'America/Mexico_City') = %s
            """, (fecha_arqueo,))
            esperado = cursor.fetchone()[0] or 0.0
    
    diferencia = monto_fisico - esperado
    
    if diferencia == 0:
        msg = f"⚖️ Arqueo de {fecha_arqueo}: Cuadre perfecto. Esperado: ${esperado:,.2f} | Contado: ${monto_fisico:,.2f}"
    elif diferencia > 0:
        msg = f"🟢 Arqueo de {fecha_arqueo}: Sobrante de ${diferencia:,.2f}. Esperado: ${esperado:,.2f} | Contado: ${monto_fisico:,.2f}"
    else:
        msg = f"🔴 Arqueo de {fecha_arqueo}: Faltante de ${abs(diferencia):,.2f}. Esperado: ${esperado:,.2f} | Contado: ${monto_fisico:,.2f}"
        
    request.session["mensaje_flash"] = msg
    return RedirectResponse(url="/", status_code=303)

@app.api_route("/borrar-movimiento/{id}", methods=["GET", "POST"])
async def borrar_movimiento(request: Request, id: int):
    if not usuario_autenticado(request):
        return RedirectResponse(url="/login", status_code=303)
        
    with obtener_conexion() as conexion:
        with conexion.cursor() as cursor:
            cursor.execute("DELETE FROM flujo_caja WHERE id = %s", (id,))
            conexion.commit()
            
    request.session["mensaje_flash"] = "🗑️ Movimiento eliminado correctamente"
    return RedirectResponse(url="/", status_code=303)
    
@app.get("/editar-movimiento/{id}", response_class=HTMLResponse)
async def editar_form(request: Request, id: int):
    if not usuario_autenticado(request):
        return RedirectResponse(url="/login", status_code=303)
    
    with obtener_conexion() as conexion:
        with conexion.cursor() as cursor:
            cursor.execute("""
                SELECT id, tipo, concepto, categoria, monto, 
                       TO_CHAR(fecha AT TIME ZONE 'UTC' AT TIME ZONE 'America/Mexico_City', 'YYYY-MM-DD'),
                       metodo, tipo_gasto, socio
                FROM flujo_caja WHERE id = %s
            """, (id,))
            movimiento = cursor.fetchone()
            
    return templates.TemplateResponse(request, "editar.html", {"m": movimiento})

@app.post("/actualizar-movimiento/{id}")
async def actualizar_movimiento(
    request: Request, 
    id: int, 
    fecha: str = Form(...),
    tipo: str = Form(...), 
    metodo: str = Form(...),
    tipo_gasto: str = Form(...),
    socio: str = Form(...),
    concepto: str = Form(...), 
    categoria: str = Form(...), 
    monto: float = Form(...)
):
    if not usuario_autenticado(request):
        return RedirectResponse(url="/login", status_code=303)
        
    with obtener_conexion() as conexion:
        with conexion.cursor() as cursor:
            cursor.execute("""
                UPDATE flujo_caja 
                SET fecha=%s, tipo=%s, metodo=%s, tipo_gasto=%s, socio=%s, concepto=%s, categoria=%s, monto=%s 
                WHERE id=%s
            """, (fecha, tipo.upper(), metodo, tipo_gasto, socio, concepto, categoria, monto, id))
            conexion.commit()
            
    request.session["mensaje_flash"] = "✅ Registro actualizado correctamente"
    return RedirectResponse(url="/", status_code=303)
    
@app.post("/actualizar-movimiento/{id}")
async def actualizar_movimiento(
    request: Request, 
    id: int, 
    tipo: str = Form(...), 
    concepto: str = Form(...), 
    categoria: str = Form(...), 
    monto: float = Form(...)
):
    if not usuario_autenticado(request):
        return RedirectResponse(url="/login", status_code=303)
        
    with obtener_conexion() as conexion:
        with conexion.cursor() as cursor:
            cursor.execute(
                "UPDATE flujo_caja SET tipo=%s, concepto=%s, categoria=%s, monto=%s WHERE id=%s", 
                (tipo.upper(), concepto, categoria, monto, id)
            )
            conexion.commit()
            
    request.session["mensaje_flash"] = "✅ Registro actualizado"
    return RedirectResponse(url="/", status_code=303)

@app.get("/reporte-inversion", response_class=HTMLResponse)
async def reporte_inversion(request: Request):
    if not usuario_autenticado(request):
        return RedirectResponse(url="/login", status_code=303)
        
    with obtener_conexion() as conexion:
        with conexion.cursor() as cursor:
            cursor.execute("""
                SELECT socio, SUM(monto) as total_invertido
                FROM flujo_caja 
                WHERE tipo_gasto = 'INVERSION'
                GROUP BY socio;
            """)
            resumen = cursor.fetchall()
            
    return templates.TemplateResponse(
        request=request, 
        name="reporte_inversion.html", 
        context={"resumen": resumen}
    )
