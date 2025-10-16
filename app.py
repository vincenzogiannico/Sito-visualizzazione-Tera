
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta

CSV_URL = st.secrets["CSV_URL"]



st.set_page_config(page_title="Tera Monitor", page_icon="📈", layout="wide")


# --- Sidebar ---
st.sidebar.title("⚙️ Controlli")
st.sidebar.caption("Il caricamento usa cache con TTL fisso (60s). Usa 'Ricarica dati' per forzare un reload.")
reload_btn = st.sidebar.button("🔄 Ricarica dati (svuota cache)")

# --- Data loading ---
@st.cache_data(ttl=60)
def load_data(url: str) -> pd.DataFrame:
    df = pd.read_csv(url)
    # Parse ISO8601; se è presente il fuso orario, pandas lo conserva
    df['ts'] = pd.to_datetime(df['ts'], utc=True, errors='coerce')  # imponiamo UTC
    df = df.dropna(subset=['ts']).sort_values('ts')
    return df

if reload_btn:
    load_data.clear()
    st.experimental_rerun()

df = load_data(CSV_URL)

if df.empty or df['ts'].isna().all():
    st.error("Non posso verificare il contenuto del CSV o la colonna 'ts' non è valida.")
    st.stop()

# Identify numeric columns (exclude 'ts')
num_cols = [c for c in df.columns if c != 'ts' and pd.api.types.is_numeric_dtype(df[c])]
default_vars = []
for cand in ["A01_Temp", "A01_Umid"]:
    if cand in num_cols:
        default_vars.append(cand)
if not default_vars and num_cols:
    default_vars = num_cols[:2]

st.title("📊 Tera – Dashboard interattiva")

# --- Time window selection ---
st.subheader("Finestra temporale")

# Helper per creare valori di input naive (senza tz) per i widget
def to_naive(dt_aware: pd.Timestamp) -> datetime:
    # Converte in UTC, poi ritorna naive (senza tz) per compatibilità con gli input Streamlit
    return dt_aware.tz_convert('UTC').to_pydatetime().replace(tzinfo=None)

min_ts_aware = df['ts'].min().tz_convert('UTC')
max_ts_aware = df['ts'].max().tz_convert('UTC')

col_a, col_b = st.columns([1,2])
with col_a:
    preset = st.selectbox(
        "Seleziona intervallo",
        options=["Ultime 6 ore", "Ultime 12 ore", "Ultime 24 ore", "Ultimi 3 giorni", "Ultimi 7 giorni", "Personalizzato"],
        index=2
    )
with col_b:
    if preset == "Personalizzato":
        start = st.datetime_input(
            "Inizio (UTC)",
            value=to_naive(min(max_ts_aware - pd.Timedelta(days=1), max_ts_aware)),
            min_value=to_naive(min_ts_aware),
            max_value=to_naive(max_ts_aware)
        )
        end = st.datetime_input(
            "Fine (UTC)",
            value=to_naive(max_ts_aware),
            min_value=to_naive(min_ts_aware),
            max_value=to_naive(max_ts_aware)
        )
    else:
        max_naive = to_naive(max_ts_aware)
        if preset == "Ultime 6 ore":
            start, end = max_naive - timedelta(hours=6), max_naive
        elif preset == "Ultime 12 ore":
            start, end = max_naive - timedelta(hours=12), max_naive
        elif preset == "Ultime 24 ore":
            start, end = max_naive - timedelta(hours=24), max_naive
        elif preset == "Ultimi 3 giorni":
            start, end = max_naive - timedelta(days=3), max_naive
        elif preset == "Ultimi 7 giorni":
            start, end = max_naive - timedelta(days=7), max_naive
        else:
            start, end = max_naive - timedelta(days=1), max_naive

# Funzione robusta: porta qualsiasi datetime a Timestamp UTC consapevole
def ensure_ts_utc(x) -> pd.Timestamp:
    tx = pd.Timestamp(x)
    if tx.tzinfo is None:
        return tx.tz_localize('UTC')
    return tx.tz_convert('UTC')

start_utc = ensure_ts_utc(start)
end_utc = ensure_ts_utc(end)

# Filtro temporale
mask = (df['ts'] >= start_utc) & (df['ts'] <= end_utc)
dff = df.loc[mask].copy()
if dff.empty:
    st.warning("La finestra selezionata non contiene dati. Mostro l'ultimo record disponibile.")
    dff = df.tail(1)

# --- Sidebar: variabili e opzioni ---
with st.sidebar:
    st.markdown("---")
    st.markdown("### Variabili")
    vars_selected = st.multiselect("Seleziona variabili (max 6)", options=num_cols, default=default_vars, max_selections=6)
    resample = st.selectbox("Aggregazione (resample)", options=["nessuna", "5min", "15min", "1H", "3H", "6H"], index=0,
                            help="Media su intervalli temporali per rendere le serie più leggibili.")
    show_points = st.checkbox("Mostra punti", value=False)
    normalize = st.checkbox("Normalizza (0–1)", value=False, help="Scala ogni variabile su [0,1] per confronti su un unico grafico.")

# Optional resampling
if resample != "nessuna":
    dff = (dff.set_index('ts')
             .resample(resample)
             .mean(numeric_only=True)
             .reset_index())

# Normalization for visualization
plot_df = dff.copy()
if normalize and vars_selected:
    for c in vars_selected:
        if c in plot_df.columns:
            s = plot_df[c]
            rng = s.max() - s.min()
            if pd.notna(rng) and rng != 0:
                plot_df[c] = (s - s.min()) / rng

# --- Charts ---
st.subheader("Grafico interattivo")
if not vars_selected:
    st.info("Seleziona almeno una variabile nella sidebar.")
else:
    fig = px.line(plot_df, x="ts", y=vars_selected, markers=show_points)
    fig.update_layout(legend=dict(orientation="h", y=-0.2), margin=dict(l=10, r=10, t=30, b=10), height=500)
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Vedi grafici separati per variabile"):
        for v in vars_selected:
            if v in plot_df.columns:
                fig_v = px.line(plot_df, x="ts", y=v, markers=show_points, title=v)
                fig_v.update_layout(margin=dict(l=10, r=10, t=30, b=10), height=280)
                st.plotly_chart(fig_v, use_container_width=True)

# --- KPIs quick view ---
st.subheader("Indicatori rapidi")
kcols = st.columns(4)
def last_val(col):
    if col in dff.columns and pd.api.types.is_numeric_dtype(dff[col]):
        return dff[col].iloc[-1]
    return None

for i, v in enumerate(default_vars[:4]):
    with kcols[i]:
        val = last_val(v)
        if val is not None:
            st.metric(v, f"{val:.2f}")

# --- Data table and download ---
with st.expander("Dati filtrati"):
    cols_to_show = ['ts'] + [c for c in vars_selected if c in dff.columns]
    st.dataframe(dff[cols_to_show], hide_index=True, use_container_width=True)
    csv = dff.to_csv(index=False).encode('utf-8')
    st.download_button("Scarica CSV filtrato", data=csv, file_name="tera_filtrato.csv", mime="text/csv")

st.caption("Fonte dati: " + CSV_URL)
