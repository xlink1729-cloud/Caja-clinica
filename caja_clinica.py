import os
import time
import psycopg2
from datetime import datetime
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse 
from zoneinfo import ZoneInfo
from fastapi.staticfiles import StaticFiles
from fastapi import Form
from starlette.middleware.sessions import SessionMiddleware

CLINIC_NAME = os.getenv("CLINIC_NAME", "FISIOSER")
PRIMARY_COLOR = os.getenv("PRIMARY_COLOR", "#10b981") 
# Contraseña maestra leída desde el panel de Render
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

app = FastAPI(title="Control de Caja")
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- MEDIDAS DE CIBERSEGURIDAD AVANZADA PARA SESIONES (Manejo de Efectivo) ---
app.add_middleware(
    SessionMiddleware, 
    secret_key=os.getenv("SESSION_SECRET", "secreto_super_seguro_2026"),
    session_cookie="session_caja",
    same_site="lax",       # Protege contra ataques de falsificación de peticiones en sitios cruzados (CSRF)
    https_only=True        # CRÍTICO: La cookie de sesión solo viaja por canales encriptados HTTPS (Render)
)

templates = Jinja2Templates(directory="templates")
templates.env.globals["CLINIC_NAME"] = CLINIC_NAME
templates.env.globals["PRIMARY_COLOR"] = PRIMARY_COLOR

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

def inicializar_bd():
    if not DATABASE_URL:
        return
    conexion = psycopg2.connect(DATABASE_URL)
    cursor = conexion.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS flujo_caja (
            id SERIAL PRIMARY KEY,
            tipo VARCHAR(10) NOT NULL,       
            concepto TEXT NOT NULL,          
            categoria VARCHAR(100) NOT NULL, 
            monto REAL NOT NULL,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conexion.commit()
    cursor.close()
    conexion.close()

@app.on_event("startup")
def startup_event():
    inicializar_bd()

def usuario_autenticado(request: Request):
    return request.session.get("autenticado") == True

def obtener_reporte_mensual():
    if not DATABASE_URL: return []
    conexion = psycopg2.connect(DATABASE_URL)
    cursor = conexion.cursor()
    # Esta consulta agrupa por mes y calcula la ganancia real
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
    conexion = psycopg2.connect(DATABASE_URL)
    cursor = conexion.cursor()
    
    # LA CORRECCIÓN: Convertimos 'fecha' a la zona horaria local antes de sacar la semana
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
    
# --- RUTAS DE AUTENTICACIÓN ---

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if usuario_autenticado(request):
        return RedirectResponse(url="/", status_code=303)
    error = request.session.pop("error_login", None)
    
    # LA CORRECCIÓN: 'request' va primero afuera, y las demás variables en 'context'
    return templates.TemplateResponse(
        request=request, 
        name="login.html", 
        context={"error": error}
    )

@app.post("/login")
async def login_action(request: Request, password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        request.session["autenticado"] = True
        return RedirectResponse(url="/", status_code=303)
    else:
        # MITIGACIÓN DE FUERZA BRUTA: Hace esperar 1 segundo si la clave falla, 
        # impidiendo que un script intente miles de contraseñas por segundo de forma automatizada.
        time.sleep(1)
        request.session["error_login"] = "❌ Contraseña incorrecta"
        return RedirectResponse(url="/login", status_code=303)

@app.get("/logout")
async def logout_action(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)

# --- RUTAS PROTEGIDAS DEL PANEL (Consultas parametrizadas contra inyección SQL) ---

@app.get("/", response_class=HTMLResponse)
async def panel_principal(request: Request):
    if not usuario_autenticado(request):
        return RedirectResponse(url="/login", status_code=303)
        
    reporte_mes = obtener_reporte_mensual()
    reporte_semana = obtener_reporte_semanal()
    
    movimientos = []
    if DATABASE_URL:
        conexion = psycopg2.connect(DATABASE_URL)
        cursor = conexion.cursor()
        # Ajustamos el SELECT para incluir tipo_gasto (ahora en la posición 7)
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
            "movimientos": movimientos, 
            "mensaje": mensaje
        }
    )
    
@app.post("/guardar-movimiento")
async def guardar_movimiento(
    request: Request, 
    tipo: str = Form(...), 
    metodo: str = Form(...),
    tipo_gasto: str = Form(...),    # Nuevo campo para distinguir Operativo vs Inversión
    socio: str = Form(...),
    concepto: str = Form(...), 
    categoria: str = Form(...), 
    monto: float = Form(...),
    fecha: str = Form(...) 
):
    if not usuario_autenticado(request):
        return RedirectResponse(url="/login", status_code=303)
        
    # Validación de seguridad
    if metodo not in ["EFECTIVO", "TRANSFERENCIA", "DEBITO", "CREDITO"]: metodo = "EFECTIVO"
    if tipo_gasto not in ["OPERATIVO", "INVERSION"]: tipo_gasto = "OPERATIVO"
        
    conexion = psycopg2.connect(DATABASE_URL)
    cursor = conexion.cursor()
    
    # INSERT incluyendo el nuevo campo 'tipo_gasto'
    cursor.execute("""
    INSERT INTO flujo_caja (fecha, tipo, metodo, tipo_gasto, socio, concepto, categoria, monto) 
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (fecha, tipo, metodo, tipo_gasto, socio, concepto, categoria, monto))
    
    conexion.commit()
    cursor.close()
    conexion.close()
    
    request.session["mensaje_flash"] = "✅ Registro guardado correctamente"
    return RedirectResponse(url="/", status_code=303)

@app.post("/borrar-movimiento/{id}")
async def borrar_movimiento(request: Request, id: int):
    if not usuario_autenticado(request):
        return RedirectResponse(url="/login", status_code=303)
        
    conexion = psycopg2.connect(DATABASE_URL)
    cursor = conexion.cursor()
    cursor.execute("DELETE FROM flujo_caja WHERE id = %s", (id,))
    conexion.commit()
    cursor.close()
    conexion.close()
    return RedirectResponse(url="/", status_code=303)

# --- RUTA PARA MOSTRAR EL FORMULARIO DE EDICIÓN ---
@app.get("/editar-movimiento/{id}", response_class=HTMLResponse)
async def editar_form(request: Request, id: int):
    if not usuario_autenticado(request):
        return RedirectResponse(url="/login", status_code=303)
    
    conexion = psycopg2.connect(DATABASE_URL)
    cursor = conexion.cursor()
    cursor.execute("SELECT id, tipo, concepto, categoria, monto, fecha FROM flujo_caja WHERE id = %s", (id,))
    movimiento = cursor.fetchone()
    cursor.close()
    conexion.close()
    
    return templates.TemplateResponse(request, "editar.html", {"m": movimiento})

# --- RUTA PARA GUARDAR LA EDICIÓN ---
@app.post("/actualizar-movimiento/{id}")
async def actualizar_movimiento(request: Request, id: int, tipo: str = Form(...), concepto: str = Form(...), categoria: str = Form(...), monto: float = Form(...)):
    conexion = psycopg2.connect(DATABASE_URL)
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
        
    conexion = psycopg2.connect(DATABASE_URL)
    cursor = conexion.cursor()
    
    # Consulta que suma lo invertido por cada uno
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
