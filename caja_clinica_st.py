import os
import time
import psycopg2
from datetime import datetime
import streamlit as st

# ==========================================
# 1. CONFIGURACIÓN E INICIALIZACIÓN
# ==========================================
CLINIC_NAME = os.getenv("CLINIC_NAME", "FISIOSER")
PRIMARY_COLOR = os.getenv("PRIMARY_COLOR", "#10b981") 
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "1234")  # Ajustar variable en Render/Local
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

st.set_page_config(
    page_title=f"Control de Caja - {CLINIC_NAME}",
    page_icon="🏥",
    layout="wide"
)

# Estilo personalizado mínimo para el color primario
st.markdown(f"""
    <style>
    :root {{
        --primary-color: {PRIMARY_COLOR};
    }}
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. FUNCIONES DE BASE DE DATOS
# ==========================================
def get_db_connection():
    if not DATABASE_URL:
        st.error("⚠️ DATABASE_URL no está configurada.")
        return None
    return psycopg2.connect(DATABASE_URL)

def inicializar_bd():
    conn = get_db_connection()
    if not conn:
        return
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS flujo_caja (
            id SERIAL PRIMARY KEY,
            tipo VARCHAR(10) NOT NULL,       
            concepto TEXT NOT NULL,          
            categoria VARCHAR(100) NOT NULL, 
            monto REAL NOT NULL,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            metodo VARCHAR(50),
            tipo_gasto VARCHAR(50),
            socio VARCHAR(100)
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()

# Inicializamos la base de datos
inicializar_bd()

def obtener_reporte_mensual():
    conn = get_db_connection()
    if not conn: return []
    cursor = conn.cursor()
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
    conn.close()
    return [{"periodo": r[0], "ingresos": r[1] or 0, "egresos": r[2] or 0, "ganancia": (r[1] or 0) - (r[2] or 0)} for r in filas]

def obtener_reporte_semanal():
    conn = get_db_connection()
    if not conn: return []
    cursor = conn.cursor()
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
    conn.close()
    return [{"periodo": r[0], "ingresos": r[1] or 0, "egresos": r[2] or 0, "ganancia": (r[1] or 0) - (r[2] or 0)} for r in filas]

def obtener_movimientos():
    conn = get_db_connection()
    if not conn: return []
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, tipo, concepto, categoria, monto, 
        (fecha AT TIME ZONE 'UTC' AT TIME ZONE 'America/Mexico_City'),
        metodo, tipo_gasto, socio
        FROM flujo_caja ORDER BY fecha DESC LIMIT 15
    """)
    movimientos = cursor.fetchall()
    cursor.close()
    conn.close()
    return movimientos

def borrar_movimiento(mov_id):
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM flujo_caja WHERE id = %s", (mov_id,))
        conn.commit()
        cursor.close()
        conn.close()

# ==========================================
# 3. CONTROL DE AUTENTICACIÓN Y SESIÓN
# ==========================================
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

def login_form():
    st.title(f"🏥 {CLINIC_NAME} - Control de Caja")
    st.subheader("Iniciar Sesión")
    
    with st.form("login_form"):
        password = st.text_input("Contraseña Administrador", type="password")
        submit = st.form_submit_button("Ingresar")
        
        if submit:
            if password == ADMIN_PASSWORD:
                st.session_state.autenticado = True
                st.rerun()
            else:
                time.sleep(1) # Protección contra fuerza bruta
                st.error("❌ Contraseña incorrecta")

if not st.session_state.autenticado:
    login_form()
    st.stop()

# ==========================================
# 4. INTERFAZ PRINCIPAL (DESPUÉS DEL LOGIN)
# ==========================================

# Barra superior con Logout
col_title, col_logout = st.columns([0.85, 0.15])
with col_title:
    st.title(f"🏥 {CLINIC_NAME} - Control de Caja")
with col_logout:
    if st.button("Cerrar Sesión"):
        st.session_state.autenticado = False
        st.rerun()

# Menú lateral
opcion = st.sidebar.radio("Navegación", ["Panel Principal", "Nuevo Movimiento", "Reporte de Inversiones"])

# ------------------------------------------
# SECCIÓN 1: PANEL PRINCIPAL
# ------------------------------------------
if opcion == "Panel Principal":
    st.header("Últimos Movimientos")
    
    movimientos = obtener_movimientos()
    if movimientos:
        for m in movimientos:
            mov_id, tipo, concepto, categoria, monto, fecha, metodo, tipo_gasto, socio = m
            col1, col2, col3, col4, col5 = st.columns([1, 2, 2, 1, 1])
            
            with col1:
                st.write(f"**{tipo}**")
                st.caption(str(fecha)[:16] if fecha else "")
            with col2:
                st.write(f"**{concepto}** ({categoria})")
                st.caption(f"Método: {metodo} | Gasto: {tipo_gasto} | Socio: {socio}")
            with col3:
                color = "green" if tipo == "INGRESO" else "red"
                st.markdown(f":{color}[${monto:,.2f}]")
            with col4:
                # Modal para editar rápido
                with st.popover("✏️ Editar"):
                    with st.form(f"edit_form_{mov_id}"):
                        e_tipo = st.selectbox("Tipo", ["INGRESO", "EGRESO"], index=0 if tipo == "INGRESO" else 1)
                        e_concepto = st.text_input("Concepto", value=concepto)
                        e_categoria = st.text_input("Categoría", value=categoria)
                        e_monto = st.number_input("Monto", value=float(monto))
                        
                        if st.form_submit_button("Guardar Cambios"):
                            conn = get_db_connection()
                            cursor = conn.cursor()
                            cursor.execute("UPDATE flujo_caja SET tipo=%s, concepto=%s, categoria=%s, monto=%s WHERE id=%s", 
                                           (e_tipo, e_concepto, e_categoria, e_monto, mov_id))
                            conn.commit()
                            cursor.close()
                            conn.close()
                            st.success("Actualizado")
                            st.rerun()
            with col5:
                if st.button("🗑️", key=f"del_{mov_id}"):
                    borrar_movimiento(mov_id)
                    st.rerun()
            st.divider()
    else:
        st.info("No hay movimientos registrados.")

    st.header("Reportes")
    tab1, tab2 = st.tabs(["Mensual", "Semanal"])
    
    with tab1:
        st.dataframe(obtener_reporte_mensual(), use_container_width=True)
    with tab2:
        st.dataframe(obtener_reporte_semanal(), use_container_width=True)

# ------------------------------------------
# SECCIÓN 2: REGISTRAR MOVIMIENTO
# ------------------------------------------
elif opcion == "Nuevo Movimiento":
    st.header("Registrar Nuevo Movimiento")
    
    with st.form("nuevo_movimiento_form"):
        col1, col2 = st.columns(2)
        with col1:
            tipo = st.selectbox("Tipo de Movimiento", ["INGRESO", "EGRESO"])
            metodo = st.selectbox("Método de Pago", ["EFECTIVO", "TRANSFERENCIA", "DEBITO", "CREDITO"])
            tipo_gasto = st.selectbox("Tipo de Gasto", ["OPERATIVO", "INVERSION"])
            socio = st.text_input("Socio / Encargado")
        
        with col2:
            concepto = st.text_input("Concepto")
            categoria = st.text_input("Categoría")
            monto = st.number_input("Monto", min_value=0.0, step=10.0)
            fecha = st.date_input("Fecha", value=datetime.now())

        btn_guardar = st.form_submit_button("Guardar Registro")

        if btn_guardar:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO flujo_caja (fecha, tipo, metodo, tipo_gasto, socio, concepto, categoria, monto) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (fecha, tipo, metodo, tipo_gasto, socio, concepto, categoria, monto))
                conn.commit()
                cursor.close()
                conn.close()
                st.success("✅ Registro guardado correctamente")

# ------------------------------------------
# SECCIÓN 3: REPORTE DE INVERSIONES
# ------------------------------------------
elif opcion == "Reporte de Inversiones":
    st.header("Reporte de Inversiones por Socio")
    
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT socio, SUM(monto) as total_invertido
            FROM flujo_caja 
            WHERE tipo_gasto = 'INVERSION'
            GROUP BY socio;
        """)
        resumen = cursor.fetchall()
        cursor.close()
        conn.close()
        
        if resumen:
            datos = [{"Socio": r[0], "Total Invertido ($)": r[1]} for r in resumen]
            st.dataframe(datos, use_container_width=True)
            st.bar_chart(data=datos, x="Socio", y="Total Invertido ($)")
        else:
            st.info("No hay registros de inversiones.")