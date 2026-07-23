import os
import streamlit as st
import psycopg2
import pandas as pd
from datetime import date, datetime

# --- CONFIGURACIÓN DE LA PÁGINA ---
CLINIC_NAME = os.getenv("CLINIC_NAME", "FISIOSER")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
DATABASE_URL = os.getenv("DATABASE_URL")

st.set_page_config(
    page_title=f"Control de Caja - {CLINIC_NAME}",
    page_icon="🏦",
    layout="wide"
)

# --- FUNCIÓN DE CONEXIÓN A BASE DE DATOS ---
def get_connection():
    if not DATABASE_URL:
        st.error("❌ No se encontró la variable DATABASE_URL.")
        return None
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1) if DATABASE_URL.startswith("postgres://") else DATABASE_URL
    return psycopg2.connect(url)

# --- MODULO DE AUTENTICACIÓN ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if not st.session_state.autenticado:
    st.title(f"🔐 Acceso - {CLINIC_NAME}")
    with st.form("login_form"):
        pwd = st.text_input("Contraseña de Administrador", type="password")
        submit_login = st.form_submit_button("Ingresar")
        if submit_login:
            if pwd == ADMIN_PASSWORD:
                st.session_state.autenticado = True
                st.rerun()
            else:
                st.error("❌ Contraseña incorrecta")
    st.stop()

# --- PANEL PRINCIPAL DE LA CAJA ---
st.title(f"🏦 Control de Caja - {CLINIC_NAME}")

# Botón para cerrar sesión
col_title, col_logout = st.columns([5, 1])
with col_logout:
    if st.button("🚪 Cerrar Sesión", use_container_width=True):
        st.session_state.autenticado = False
        st.rerun()

# --- FORMULARIO PARA REGISTRAR MOVIMIENTO ---
st.subheader("✏️ Registrar Movimiento")
with st.form("form_guardar_movimiento", clear_on_submit=True):
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        fecha = st.date_input("Fecha", value=date.today())
    with col2:
        tipo = st.selectbox("Tipo", ["INGRESO", "EGRESO"])
    with col3:
        metodo = st.selectbox("Método de Pago", ["EFECTIVO", "TRANSFERENCIA", "DEBITO", "CREDITO"])
    with col4:
        tipo_gasto = st.selectbox("Tipo de Gasto", ["OPERATIVO", "INVERSION"])

    col5, col6, col7, col8 = st.columns(4)
    with col5:
        socio = st.text_input("Socio / Aplicado a", placeholder="Ej. General / Socio A")
    with col6:
        concepto = st.text_input("Concepto", placeholder="Ej. Lámpara de Emergencia")
    with col7:
        categoria = st.text_input("Categoría", placeholder="Ej. Equipamiento / Mantenimiento")
    with col8:
        monto = st.number_input("Monto ($)", min_value=0.0, step=0.01, format="%.2f")

    guardar = st.form_submit_button("💾 Guardar Movimiento", use_container_width=True)

if guardar:
    if not concepto or monto <= 0:
        st.warning("⚠️ Debes ingresar un concepto y un monto válido.")
    else:
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO flujo_caja (fecha, tipo, metodo, tipo_gasto, socio, concepto, categoria, monto) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (fecha, tipo, metodo, tipo_gasto, socio, concepto, categoria, monto))
            conn.commit()
            cursor.close()
            conn.close()
            st.success("✅ Movimiento guardado correctamente")
            st.rerun()
        except Exception as e:
            st.error(f"Error al guardar: {e}")

st.divider()

# --- CONSULTA DE DATOS Y DASHBOARD ---
try:
    conn = get_connection()
    df = pd.read_sql("""
        SELECT id, fecha, tipo, metodo, tipo_gasto, socio, concepto, categoria, monto 
        FROM flujo_caja 
        ORDER BY fecha DESC, id DESC
    """, conn)
    conn.close()
except Exception as e:
    st.error(f"Error al consultar datos: {e}")
    df = pd.DataFrame()

if not df.empty:
    # --- RESUMEN RÁPIDO (METRICAS) ---
    ingresos = df[df['tipo'] == 'INGRESO']['monto'].sum()
    egresos = df[df['tipo'] == 'EGRESO']['monto'].sum()
    balance = ingresos - egresos

    m1, m2, m3 = st.columns(3)
    m1.metric("Ingresos Totales", f"${ingresos:,.2f}")
    m2.metric("Egresos Totales", f"${egresos:,.2f}")
    m3.metric("Balance Neto", f"${balance:,.2f}", delta=f"${balance:,.2f}")

    st.divider()

    # --- PESTAÑAS PARA TABLA, REPORTES Y ACCIONES ---
    tab_tabla, tab_reportes, tab_inversion = st.tabs(["📋 Últimos Movimientos", "📊 Reporte Semanal / Mensual", "📈 Reporte de Inversión"])

    with tab_tabla:
        st.write("### Historial de Movimientos")
        # Tabla interactiva
        st.dataframe(df, use_container_width=True)

        # Sección para borrar movimiento
        with st.expander("🗑️ Borrar un Movimiento"):
            id_borrar = st.number_input("Ingresa el ID del movimiento a eliminar:", min_value=1, step=1)
            if st.button("Eliminar Registro", type="primary"):
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM flujo_caja WHERE id = %s", (id_borrar,))
                conn.commit()
                cursor.close()
                conn.close()
                st.success(f"Movimiento con ID {id_borrar} eliminado.")
                st.rerun()

    with tab_reportes:
        st.write("### Resumen por Períodos")
        df['fecha'] = pd.to_datetime(df['fecha'])
        df['Mes'] = df['fecha'].dt.to_period('M').astype(str)
        
        reporte_mes = df.groupby(['Mes', 'tipo'])['monto'].sum().unstack(fill_value=0)
        if 'INGRESO' not in reporte_mes: reporte_mes['INGRESO'] = 0.0
        if 'EGRESO' not in reporte_mes: reporte_mes['EGRESO'] = 0.0
        reporte_mes['Ganancia'] = reporte_mes['INGRESO'] - reporte_mes['EGRESO']
        
        st.dataframe(reporte_mes, use_container_width=True)
        st.bar_chart(reporte_mes[['INGRESO', 'EGRESO']])

    with tab_inversion:
        st.write("### Resumen de Inversión por Socio")
        df_inv = df[df['tipo_gasto'] == 'INVERSION']
        if not df_inv.empty:
            resumen_inv = df_inv.groupby('socio')['monto'].sum().reset_index()
            resumen_inv.columns = ['Socio', 'Total Invertido ($)']
            st.dataframe(resumen_inv, use_container_width=True)
            st.bar_chart(data=resumen_inv, x='Socio', y='Total Invertido ($)')
        else:
            st.info("No hay registros clasificados como INVERSIÓN aún.")
