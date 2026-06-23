import os
import psycopg2
from datetime import datetime
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse 
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

CLINIC_NAME = os.getenv("CLINIC_NAME", "FISIOSER")
PRIMARY_COLOR = os.getenv("PRIMARY_COLOR", "#10b981") 
# Definimos la contraseña que se leerá desde Render. Si no hay, por defecto es 'admin123'
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

app = FastAPI(title="Control de Caja")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Secreto criptográfico para las cookies de sesión
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "secreto_super_seguro_2026"))

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

# Función auxiliar para verificar si el usuario ya inició sesión
def usuario_autenticado(request: Request):
    return request.session.get("autenticado") == True

def obtener_reporte_mensual():
    if not DATABASE_URL: return []
    conexion = psycopg2.connect(DATABASE_URL)
    cursor = conexion.cursor()
    cursor.execute("""
        SELECT TO_CHAR(fecha, 'YYYY-MM') as mes,
               SUM(CASE WHEN tipo = 'INGRESO' THEN monto ELSE 0 END),
               SUM(CASE WHEN tipo = 'EGRESO' THEN monto ELSE 0 END)
        FROM flujo_caja GROUP BY mes ORDER BY mes DESC;
    """)
    filas = cursor.fetchall()
    cursor.close()
    conexion.close()
    return [{"periodo": r[0], "ingresos": r[1] or 0, "egresos": r[2] or 0, "ganancia": (r[1] or 0) - (r[2] or 0)} for r in filas]

def obtener_reporte_semanal():
    if not DATABASE_URL: return []
    conexion = psycopg2.connect(DATABASE_URL)
    cursor = conexion.cursor()
    cursor.execute("""
        SELECT TO_CHAR(fecha, 'IYYY-"W"IW') as semana,
               SUM(CASE WHEN tipo = 'INGRESO' THEN monto ELSE 0 END),
               SUM(CASE WHEN tipo = 'EGRESO' THEN monto ELSE 0 END)
        FROM flujo_caja GROUP BY semana ORDER BY semana DESC;
    """)
    filas = cursor.fetchall()
    cursor.close()
    conexion.close()
    return [{"periodo": r[0], "ingresos": r[1] or 0, "egresos": r[2] or 0, "ganancia": (r[1] or 0) - (r[2] or 0)} for r in filas]

# --- RUTAS DE AUTENTICACIÓN ---

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    # Si ya está logueado, lo mandamos al panel directo
    if usuario_autenticado(request):
        return RedirectResponse(url="/", status_code=303)
    error = request.session.pop("error_login", None)
    return templates.TemplateResponse("login.html", {"request": request, "error": error})

@app.post("/login")
async def login_action(request: Request, password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        request.session["autenticado"] = True
        return RedirectResponse(url="/", status_code=303)
    else:
        request.session["error_login"] = "❌ Contraseña incorrecta"
        return RedirectResponse(url="/login", status_code=303)

@app.get("/logout")
async def logout_action(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)

# --- RUTAS PROTEGIDAS DEL PANEL ---

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
        cursor.execute("SELECT id, tipo, concepto, categoria, monto, fecha FROM flujo_caja ORDER BY fecha DESC LIMIT 15")
        movimientos = cursor.fetchall()
        cursor.close()
        conexion.close()
    
    mensaje = request.session.pop("mensaje_flash", None)
    return templates.TemplateResponse("control_caja.html", {
        "request": request, "reporte_mensual": reporte_mes, "reporte_semanal": reporte_semana, "movimientos": movimientos, "mensaje": mensaje
    })

@app.post("/guardar-movimiento")
async def guardar_movimiento(request: Request, tipo: str = Form(...), concepto: str = Form(...), categoria: str = Form(...), monto: float = Form(...)):
    if not usuario_autenticado(request):
        return RedirectResponse(url="/login", status_code=303)
        
    conexion = psycopg2.connect(DATABASE_URL)
    cursor = conexion.cursor()
    cursor.execute("INSERT INTO flujo_caja (tipo, concepto, categoria, monto) VALUES (%s, %s, %s, %s)", (tipo.upper(), concepto.strip(), categoria.strip(), monto))
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
