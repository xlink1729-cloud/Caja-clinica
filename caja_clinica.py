import os
import time
import psycopg2
from psycopg2 import pool
from datetime import datetime
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse 
from zoneinfo import ZoneInfo
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

CLINIC_NAME = os.getenv("CLINIC_NAME")
PRIMARY_COLOR = os.getenv("PRIMARY_COLOR", "#10b981") 
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

app = FastAPI(title="Control de Caja")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Configuración de sesión segura
app.add_middleware(
    SessionMiddleware, 
    secret_key=os.getenv("SESSION_SECRET"),
    session_cookie="session_caja",
    same_site="lax",
    https_only=True
)

templates = Jinja2Templates(directory="templates")
templates.env.globals["CLINIC_NAME"] = CLINIC_NAME
templates.env.globals["PRIMARY_COLOR"] = PRIMARY_COLOR

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

def obtener_conexion():
    """Abre conexión segura a Neon."""
    return psycopg2.connect(DATABASE_URL)

def inicializar_bd():
    if not DATABASE_URL:
        return
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()
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
        cursor.close()
        conexion.close()
    except Exception as e:
        print(f"Error al conectar con Neon: {e}")

@app.on_event("startup")
def startup_event():
    inicializar_bd()

def usuario_autenticado(request: Request):
    return request.session.get("autenticado") == True

def obtener_reporte_mensual():
    if not DATABASE_URL: return []
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    cursor.execute("""
        SELECT TO_CHAR(fecha AT TIME ZONE 'UTC' AT TIME ZONE 'America/Mexico_City', 'YYYY-MM') as mes,
               SUM(CASE WHEN tipo = 'INGRESO' THEN monto ELSE 0 END) as ingresos,
               SUM(CASE WHEN tipo = 'EGRESO' THEN monto ELSE 0 END) as egresos
        FROM flujo_caja 
        GROUP BY mes 
        ORDER BY mes DESC;
    """)
    filas = cursor.fetchall()
    cursor.close()
    conexion.close()
    return [{"periodo": r[0], "ingresos": r[1] or 0, "egresos": r[2] or 0, "ganancia": (r[1] or 0) - (r[2] or 0)} for r in filas]
    
def obtener_reporte_semanal():
    if not DATABASE_URL: return []
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    cursor.execute("""
        SELECT TO_CHAR(fecha AT TIME ZONE 'UTC' AT TIME ZONE 'America/Mexico_City', 'IYYY-"W"IW') as semana,
               SUM(CASE WHEN tipo = 'INGRESO' THEN monto ELSE 0 END),
               SUM(CASE WHEN tipo = 'EGRESO' THEN monto ELSE 0 END)
        FROM flujo_caja 
        GROUP BY semana 
        ORDER BY semana DESC;
    """)
    filas = cursor.fetchall()
    cursor.close()
    conexion.close()
    return [{"periodo": r[0], "ingresos": r[1] or 0, "egresos": r[2] or 0, "ganancia": (r[1] or 0) - (r[2] or 0)} for r in filas]

def calcular_deuda_directa():
    """Calcula la deuda directa al 100% entre Paola y Jorge."""
    if not DATABASE_URL:
        return {"inv_paola": 0, "inv_jorge": 0, "deuda_jorge": 0, "deuda_paola": 0}
        
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    
    # Suma total de inversiones pagadas individualmente por cada uno
    cursor.execute("""
        SELECT 
            COALESCE(SUM(CASE WHEN socio = 'Paola' THEN monto ELSE 0 END), 0) as paola,
            COALESCE(SUM(CASE WHEN socio = 'Jorge' THEN monto ELSE 0 END), 0) as jorge
        FROM flujo_caja 
        WHERE tipo_gasto = 'INVERSION';
    """)
    
    res = cursor.fetchone()
    cursor.close()
    conexion.close()
    
    inv_paola = res[0]
    inv_jorge = res[1]
    
    # Diferencia directa (100% del monto)
    diferencia = inv_paola - inv_jorge
    
    return {
        "inv_paola": inv_paola,
        "inv_jorge": inv_jorge,
        "deuda_jorge": diferencia if diferencia > 0 else 0,
        "deuda_paola": abs(diferencia) if diferencia < 0 else 0
    }

# --- AUTENTICACIÓN ---

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
        time.sleep(1)
        request.session["error_login"] = "❌ Contraseña incorrecta"
        return RedirectResponse(url="/login", status_code=303)

@app.get("/logout")
async def logout_action(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)

# --- RUTAS PRINCIPALES ---

@app.get("/", response_class=HTMLResponse)
async def panel_principal(request: Request):
    if not usuario_autenticado(request):
        return RedirectResponse(url="/login", status_code=303)
        
    reporte_mes = obtener_reporte_mensual()
    reporte_semana = obtener_reporte_semanal()
    cuentas = calcular_deuda_directa()
    
    movimientos = []
    if DATABASE_URL:
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT id, tipo, concepto, categoria, monto, 
            (fecha AT TIME ZONE 'UTC' AT TIME ZONE 'America/Mexico_City'),
            metodo, tipo_gasto, socio
            FROM flujo_caja ORDER BY fecha DESC LIMIT 15
        """)
        movimientos = cursor.fetchall()
        cursor.close()
        conexion.close()
    
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
        
    if metodo not in ["EFECTIVO", "TRANSFERENCIA", "DEBITO", "CREDITO"]: metodo = "EFECTIVO"
    if tipo_gasto not in ["OPERATIVO", "INVERSION"]: tipo_gasto = "OPERATIVO"
        
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    cursor.execute("""
        INSERT INTO flujo_caja (fecha, tipo, metodo, tipo_gasto, socio, concepto, categoria, monto) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (fecha, tipo, metodo, tipo_gasto, socio, concepto, categoria, monto))
    
    conexion.commit()
    cursor.close()
    conexion.close()
    
    request.session["mensaje_flash"] = "✅ Registro guardado correctamente"
    return RedirectResponse(url="/", status_code=303)

# --- NUEVA RUTA: ARQUEO DE CAJA ---
@app.post("/arqueo")
async def realizar_arqueo(request: Request, fecha_arqueo: str = Form(...), monto_fisico: float = Form(...)):
    if not usuario_autenticado(request):
        return RedirectResponse(url="/login", status_code=303)
        
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    
    # Calcula el total de efectivo esperado en esa fecha específica
    cursor.execute("""
        SELECT 
            COALESCE(SUM(CASE WHEN tipo = 'INGRESO' THEN monto ELSE 0 END), 0) -
            COALESCE(SUM(CASE WHEN tipo = 'EGRESO' THEN monto ELSE 0 END), 0)
        FROM flujo_caja
        WHERE metodo = 'EFECTIVO' AND DATE(fecha AT TIME ZONE 'UTC' AT TIME ZONE 'America/Mexico_City') = %s
    """, (fecha_arqueo,))
    
    esperado = cursor.fetchone()[0] or 0.0
    cursor.close()
    conexion.close()
    
    diferencia = monto_fisico - esperado
    
    if diferencia == 0:
        msg = f"⚖️ Arqueo de {fecha_arqueo}: Cuadre perfecto. Esperado: ${esperado:,.2f} | Contado: ${monto_fisico:,.2f}"
    elif diferencia > 0:
        msg = f"🟢 Arqueo de {fecha_arqueo}: Sobrante de ${diferencia:,.2f}. Esperado: ${esperado:,.2f} | Contado: ${monto_fisico:,.2f}"
    else:
        msg = f"🔴 Arqueo de {fecha_arqueo}: Faltante de ${abs(diferencia):,.2f}. Esperado: ${esperado:,.2f} | Contado: ${monto_fisico:,.2f}"
        
    request.session["mensaje_flash"] = msg
    return RedirectResponse(url="/", status_code=303)

@app.post("/borrar-movimiento/{id}")
async def borrar_movimiento(request: Request, id: int):
    if not usuario_autenticado(request):
        return RedirectResponse(url="/login", status_code=303)
        
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    cursor.execute("DELETE FROM flujo_caja WHERE id = %s", (id,))
    conexion.commit()
    cursor.close()
    conexion.close()
    return RedirectResponse(url="/", status_code=303)

@app.get("/editar-movimiento/{id}", response_class=HTMLResponse)
async def editar_form(request: Request, id: int):
    if not usuario_autenticado(request):
        return RedirectResponse(url="/login", status_code=303)
    
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    cursor.execute("""
        SELECT id, tipo, concepto, categoria, monto, 
               TO_CHAR(fecha AT TIME ZONE 'UTC' AT TIME ZONE 'America/Mexico_City', 'YYYY-MM-DD'),
               metodo, tipo_gasto, socio
        FROM flujo_caja WHERE id = %s
    """, (id,))
    movimiento = cursor.fetchone()
    cursor.close()
    conexion.close()
    
    return templates.TemplateResponse(request, "editar.html", {"m": movimiento})

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
        
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    cursor.execute("UPDATE flujo_caja SET tipo=%s, concepto=%s, categoria=%s, monto=%s WHERE id=%s", (tipo.upper(), concepto, categoria, monto, id))
    conexion.commit()
    cursor.close()
    conexion.close()
    request.session["mensaje_flash"] = "✅ Registro actualizado"
    return RedirectResponse(url="/", status_code=303)

@app.get("/reporte-inversion", response_class=HTMLResponse)
async def reporte_inversion(request: Request):
    if not usuario_autenticado(request):
        return RedirectResponse(url="/login", status_code=303)
        
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    cursor.execute("""
        SELECT socio, SUM(monto) as total_invertido
        FROM flujo_caja 
        WHERE tipo_gasto = 'INVERSION'
        GROUP BY socio;
    """)
    resumen = cursor.fetchall()
    cursor.close()
    conexion.close()
    
    return templates.TemplateResponse(
        request=request, 
        name="reporte_inversion.html", 
        context={"resumen": resumen}
    )
