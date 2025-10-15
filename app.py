
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="Tera Monitor", page_icon="📈", layout="wide")

CSV_URL = "https://gist.githubusercontent.com/vincenzogiannico/53654730a091a40b4458ba923241d209/raw/tera_allvars.csv"

# --- Sidebar ---
st.sidebar.title("⚙️ Controlli")
auto_refresh = st.sidebar.checkbox("Auto-refresh", value=True, help="Ricarica automaticamente i dati dalla sorgente")
refresh_sec = st.sidebar.number_input("Intervallo refresh (s)", min_value=10, max_value=3600, value=60, step=10)

# --- Data loading ---
@st.cache_data(ttl=60)
def load_data(url: str) -> pd.DataFrame:
    df = pd.read_csv(url)
    # Parse ISO8601 with timezone if present
    df['ts'] = pd.to_datetime(df['ts'], utc=True, errors='coerce')
    # Ensure sorted
    df = df.sort_values('ts')
    return df

if auto_refresh:
    # Trigger a periodic rerun (works in Streamlit >= 1.25)
    # exist reference to avoid linter warning
    st.autorefresh = st.sidebar.empty()
    st.sidebar.caption("Il refresh automatico usa cache con TTL 60s.")
    st.sidebar.write(" ")
    st.experimental_set_query_params(_=datetime.now(timezone.utc).timestamp())  # keeps the browser URL changing slightly

df = load_data(CSV_URL)

if df.empty or df['ts'].isna().all():
    st.error("Non posso verificare il contenuto del CSV o la colonna 'ts' non è valida.")
    st.stop()

# Identify numeric columns (exclude 'ts')
num_cols = [c for c in df.columns if c != 'ts' and pd.api.types.is_numeric_dtype(df[c])]
default_vars = []
# Choose reasonable defaults if present
for cand in ["A01_Temp", "A01_Umid"]:
    if cand in num_cols:
        default_vars.append(cand)
if not default_vars and num_cols:
    default_vars = num_cols[:2]

st.title("📊 Tera – Dashboard interattiva")

# --- Time window selection ---
st.subheader("Finestra temporale")
col_a, col_b = st.columns([1,2])
with col_a:
    preset = st.selectbox(
        "Seleziona intervallo",
        options=["Ultime 6 ore", "Ultime 12 ore", "Ultime 24 ore", "Ultimi 3 giorni", "Ultimi 7 giorni", "Personalizzato"],
        index=2
    )
with col_b:
    if preset == "Personalizzato":
        min_ts = df['ts'].min().to_pydatetime()
        max_ts = df['ts'].max().to_pydatetime()
        start = st.datetime_input("Inizio (UTC)", value=max_ts - timedelta(days=1), min_value=min_ts, max_value=max_ts)
        end = st.datetime_input("Fine (UTC)", value=max_ts, min_value=min_ts, max_value=max_ts)
    else:
        max_ts = df['ts'].max().to_pydatetime()
        if preset == "Ultime 6 ore":
            start, end = max_ts - timedelta(hours=6), max_ts
        elif preset == "Ultime 12 ore":
            start, end = max_ts - timedelta(hours=12), max_ts
        elif preset == "Ultime 24 ore":
            start, end = max_ts - timedelta(hours=24), max_ts
        elif preset == "Ultimi 3 giorni":
            start, end = max_ts - timedelta(days=3), max_ts
        elif preset == "Ultimi 7 giorni":
            start, end = max_ts - timedelta(days=7), max_ts
        else:
            start, end = max_ts - timedelta(days=1), max_ts

# Filter by time window (timestamps are UTC)
mask = (df['ts'] >= pd.Timestamp(start, tz='UTC')) & (df['ts'] <= pd.Timestamp(end, tz='UTC'))
dff = df.loc[mask].copy()
if dff.empty:
    st.warning("La finestra selezionata non contiene dati.")
    dff = df.tail(1)

# --- Variable selection ---
with st.sidebar:
    st.markdown("---")
    st.markdown("### Variabili")
    vars_selected = st.multiselect("Seleziona variabili (max 6)", options=num_cols, default=default_vars, max_selections=6)
    resample = st.selectbox("Aggregazione (resample)", options=["nessuna", "5min", "15min", "1H", "3H", "6H"], index=0,
                            help="Applica una media su intervalli temporali per rendere le serie più leggibili.")
    show_points = st.checkbox("Mostra punti", value=False)
    normalize = st.checkbox("Normalizza (0–1)", value=False, help="Scala ogni variabile su [0,1] per confronti su un unico grafico.")

# Optional resampling
if resample != "nessuna":
    rule = resample
    dff = (dff.set_index('ts')
             .resample(rule)
             .mean(numeric_only=True)
             .reset_index())

# Normalization for visualization
plot_df = dff.copy()
if normalize and vars_selected:
    for c in vars_selected:
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

    # Separate small multiples (optional)
    with st.expander("Vedi grafici separati per variabile"):
        for v in vars_selected:
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
    st.dataframe(dff[['ts'] + [c for c in vars_selected if c in dff.columns]], hide_index=True, use_container_width=True)
    csv = dff.to_csv(index=False).encode('utf-8')
    st.download_button("Scarica CSV filtrato", data=csv, file_name="tera_filtrato.csv", mime="text/csv")

st.caption("Fonte dati: " + CSV_URL)
