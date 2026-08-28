import os
import time
import psycopg2
from datetime import datetime
import pandas as pd
import streamlit as st

# ==========================================
# 1. CONFIGURACIÓN INICIAL
# ==========================================
CLINIC_NAME = os.getenv("CLINIC_NAME", "FISIOSER")
PRIMARY_COLOR = os.getenv("PRIMARY_COLOR", "#10b981") 
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "1234")
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

st.set_page_config(
    page_title=f"{CLINIC_NAME} - Control de Caja",
    page_icon="🏥",
    layout="wide"
)

# Estilo personalizado para emular Tailwind / Marca
st.markdown(f"""
    <style>
    :root {{
        --primary-color: {PRIMARY_COLOR};
    }}
    .main-header {{
        font-weight: 700;
        color: #1f2937;
    }}
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. FUNCIONES BASE DE DATOS
# ==========================================
def get_db_connection():
    if not DATABASE_URL:
        st.error("⚠️ DATABASE_URL no está configurada en las variables de entorno.")
        return None
    return psycopg2.connect(DATABASE_URL)

def inicializar_bd():
    conn = get_db_connection()
    if not conn: return
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
    return [{"Mes": r[0], "Ingresos": r[1] or 0.0, "Egresos": r[2] or 0.0, "Ganancia": (r[1] or 0.0) - (r[2] or 0.0)} for r in filas]

def obtener_reporte_semanal():
    conn = get_db_connection()
    if not conn: return []
    cursor = conn.cursor()
    cursor.execute("""
        SELECT TO_CHAR(fecha AT TIME ZONE 'UTC' AT TIME ZONE 'America/Mexico_City', 'IYYY-"W"IW') as semana,
               SUM(CASE WHEN tipo = 'INGRESO' THEN monto ELSE 0 END) as ingresos,
               SUM(CASE WHEN tipo = 'EGRESO' THEN monto ELSE 0 END) as egresos
        FROM flujo_caja 
        GROUP BY semana 
        ORDER BY semana DESC;
    """)
    filas = cursor.fetchall()
    cursor.close()
    conn.close()
    return [{"Semana": r[0], "Ingresos": r[1] or 0.0, "Egresos": r[2] or 0.0, "Ganancia": (r[1] or 0.0) - (r[2] or 0.0)} for r in filas]

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
    movs = cursor.fetchall()
    cursor.close()
    conn.close()
    return movs

# ==========================================
# 3. CONTROL DE SESIÓN / LOGIN
# ==========================================
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if not st.session_state.autenticado:
    col_a, col_b, col_c = st.columns([1, 2, 1])
    with col_b:
        st.markdown(f"<h2 style='text-align: center;'>Control Financiero {CLINIC_NAME}</h2>", unsafe_allow_html=True)
        st.caption("Ingresa la clave de acceso para continuar")
        
        with st.form("login_form"):
            password = st.text_input("Contraseña de Administrador", type="password", placeholder="••••••••")
            submit = st.form_submit_button("Entrar al Sistema", use_container_width=True)
            
            if submit:
                if password == ADMIN_PASSWORD:
                    st.session_state.autenticado = True
                    st.rerun()
                else:
                    time.sleep(1) # Protección contra fuerza bruta
                    st.error("❌ Contraseña incorrecta")
    st.stop()

# ==========================================
# 4. ENCABEZADO Y NAVEGACIÓN
# ==========================================
col_h1, col_h2 = st.columns([0.8, 0.2])
with col_h1:
    st.title(f"🏥 {CLINIC_NAME} - Control de Caja")
with col_h2:
    if st.button("🔒 Cerrar Sesión", use_container_width=True):
        st.session_state.autenticado = False
        st.rerun()

opcion_menu = st.sidebar.radio("Menú", ["📝 Control de Caja", "🏗️ Resumen de Inversión"])

# Mapeo para legibilidad de UI
SOCIOS_MAP = {"AMBOS": "🤝 Ambos", "NOVIA": "👤 Paola", "COMPAÑERO": "👤 Jorge"}
SOCIOS_REV = {v: k for k, v in SOCIOS_MAP.items()}

# ==========================================
# SECCIÓN: CONTROL DE CAJA
# ==========================================
if opcion_menu == "📝 Control de Caja":
    
    # --- FORMULARIO NUEVO MOVIMIENTO ---
    with st.expander("📝 Registrar Movimiento", expanded=True):
        with st.form("form_guardar_movimiento", clear_on_submit=True):
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                fecha = st.date_input("Fecha", value=datetime.now())
                tipo = st.selectbox("Tipo", ["INGRESO", "EGRESO"], format_func=lambda x: "📥 Ingreso" if x=="INGRESO" else "📤 Egreso")
            with col2:
                metodo = st.selectbox("Método", ["EFECTIVO", "TRANSFERENCIA", "DEBITO", "CREDITO"], 
                                      format_func=lambda x: {"EFECTIVO": "💵 Efectivo", "TRANSFERENCIA": "📱 Transferencia", "DEBITO": "💳 Débito", "CREDITO": "💳 Crédito"}[x])
                tipo_gasto = st.selectbox("Tipo de Gasto", ["OPERATIVO", "INVERSION"], 
                                          format_func=lambda x: "🏢 Operativo" if x=="OPERATIVO" else "🏗️ Inversión/Deuda")
            with col3:
                socio_label = st.selectbox("Responsable / Socio", list(SOCIOS_MAP.values()))
                concepto = st.text_input("Concepto", placeholder="Concepto")
            with col4:
                categoria = st.text_input("Categoría", placeholder="Categoría")
                monto = st.number_input("Monto", min_value=0.0, step=0.01, format="%.2f")
                
            btn_guardar = st.form_submit_button("Guardar Registro", use_container_width=True)
            
            if btn_guardar:
                if not concepto or not categoria or monto <= 0:
                    st.warning("Por favor completa los campos requeridos y un monto mayor a cero.")
                else:
                    socio_val = SOCIOS_REV[socio_label]
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO flujo_caja (fecha, tipo, metodo, tipo_gasto, socio, concepto, categoria, monto) 
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (fecha, tipo, metodo, tipo_gasto, socio_val, concepto, categoria, monto))
                    conn.commit()
                    cursor.close()
                    conn.close()
                    st.success("✅ Registro guardado correctamente")
                    st.rerun()

    # --- BALANCES SEMANAL Y MENSUAL ---
    col_sem, col_mes = st.columns(2)
    with col_sem:
        st.subheader("🗓️ Balance por Semana")
        df_sem = pd.DataFrame(obtener_reporte_semanal())
        if not df_sem.empty:
            st.dataframe(df_sem.style.format({"Ingresos": "${:,.2f}", "Egresos": "${:,.2f}", "Ganancia": "${:,.2f}"}), use_container_width=True)
        else:
            st.info("No hay datos disponibles.")

    with col_mes:
        st.subheader("📊 Balance por Mes")
        df_mes = pd.DataFrame(obtener_reporte_mensual())
        if not df_mes.empty:
            st.dataframe(df_mes.style.format({"Ingresos": "${:,.2f}", "Egresos": "${:,.2f}", "Ganancia": "${:,.2f}"}), use_container_width=True)
        else:
            st.info("No hay datos disponibles.")

    # --- ARQUEO DE CAJA ---
    with st.expander("⚖️ Arqueo de Caja (Solo Efectivo)"):
        with st.form("form_arqueo"):
            c_arq1, c_arq2, c_arq3 = st.columns([1, 1, 1])
            with c_arq1:
                fecha_arq = st.date_input("Fecha Arqueo", value=datetime.now())
            with c_arq2:
                monto_fisico = st.number_input("Monto Físico ($)", min_value=0.0, step=0.01)
            with c_arq3:
                st.write("")
                st.write("")
                btn_arq = st.form_submit_button("Verificar Saldo")

            if btn_arq:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT SUM(CASE WHEN tipo='INGRESO' THEN monto ELSE -monto END)
                    FROM flujo_caja
                    WHERE metodo = 'EFECTIVO' AND DATE(fecha AT TIME ZONE 'UTC' AT TIME ZONE 'America/Mexico_City') <= %s
                """, (fecha_arq,))
                resultado = cursor.fetchone()[0] or 0.0
                cursor.close()
                conn.close()

                diferencia = monto_fisico - resultado
                st.info(f"Saldo teórico en sistema (Efectivo): **${resultado:,.2f}**")
                if diferencia == 0:
                    st.success("✅ El arqueo coincide perfectamente.")
                elif diferencia > 0:
                    st.warning(f"⚠️ Sobrante en caja de: **${diferencia:,.2f}**")
                else:
                    st.error(f"❌ Faltante en caja de: **${abs(diferencia):,.2f}**")

    # --- ÚLTIMOS MOVIMIENTOS Y EDICIÓN ---
    st.subheader("🕒 Últimos 15 Movimientos")
    movimientos = obtener_movimientos()

    if movimientos:
        for m in movimientos:
            mov_id, m_tipo, m_concepto, m_categoria, m_monto, m_fecha, m_metodo, m_tipo_gasto, m_socio = m
            
            c_f, c_r, c_t, c_m, c_c, c_mon, c_act = st.columns([1, 1, 1, 1, 2, 1, 1])
            with c_f:
                st.caption(str(m_fecha)[:10] if m_fecha else "")
            with c_r:
                st.write(f"**{SOCIOS_MAP.get(m_socio, m_socio)}**")
            with c_t:
                st.write(f"📥 {m_tipo}" if m_tipo == "INGRESO" else f"📤 {m_tipo}")
            with c_m:
                st.caption(f"[{m_metodo}]")
            with c_c:
                st.write(f"**{m_concepto}**")
                st.caption(f"{m_categoria} | {m_tipo_gasto}")
            with c_mon:
                color = "green" if m_tipo == "INGRESO" else "red"
                st.markdown(f":{color}[${m_monto:,.2f}]")
            with c_act:
                # Modal popover para editar directamente
                with st.popover("✏️"):
                    with st.form(f"edit_form_{mov_id}"):
                        e_tipo = st.selectbox("Tipo", ["INGRESO", "EGRESO"], index=0 if m_tipo=="INGRESO" else 1)
                        e_concepto = st.text_input("Concepto", value=m_concepto)
                        e_categoria = st.text_input("Categoría", value=m_categoria)
                        e_monto = st.number_input("Monto", value=float(m_monto), step=0.01)
                        
                        if st.form_submit_button("Guardar Cambios"):
                            conn = get_db_connection()
                            cursor = conn.cursor()
                            cursor.execute("UPDATE flujo_caja SET tipo=%s, concepto=%s, categoria=%s, monto=%s WHERE id=%s", 
                                           (e_tipo.upper(), e_concepto, e_categoria, e_monto, mov_id))
                            conn.commit()
                            cursor.close()
                            conn.close()
                            st.success("Actualizado")
                            st.rerun()

                if st.button("🗑️", key=f"del_btn_{mov_id}"):
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM flujo_caja WHERE id = %s", (mov_id,))
                    conn.commit()
                    cursor.close()
                    conn.close()
                    st.rerun()
            st.divider()
    else:
        st.info("No hay movimientos recientes.")

# ==========================================
# SECCIÓN: RESUMEN DE INVERSIÓN
# ==========================================
elif opcion_menu == "🏗️ Resumen de Inversión":
    st.title("🏗️ Resumen de Inversión")
    
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
            suma_total = sum(r[1] for r in resumen)
            
            filas_tabla = []
            for r in resumen:
                socio_nombre = SOCIOS_MAP.get(r[0], r[0])
                monto_inv = r[1]
                porcentaje = (monto_inv / suma_total * 100) if suma_total > 0 else 0.0
                filas_tabla.append({
                    "Socio": socio_nombre,
                    "Monto Invertido": f"${monto_inv:,.2f}",
                    "Porcentaje": f"{porcentaje:.1f}%"
                })

            st.table(filas_tabla)
            st.markdown(f"**TOTAL GENERAL:** `${suma_total:,.2f}` | **100%**")
            
            # Gráfica de distribución de inversión
            df_chart = pd.DataFrame([{"Socio": SOCIOS_MAP.get(r[0], r[0]), "Inversión": r[1]} for r in resumen])
            st.bar_chart(df_chart, x="Socio", y="Inversión")
        else:
            st.info("No se han registrado gastos categorizados como INVERSION.")
