import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import numpy as np
from io import BytesIO
import calendar

# ─── CONFIG PAGINA ───────────────────────────────────────────
st.set_page_config(
    page_title="Energy Dashboard Pro",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── COLORI PRO ──────────────────────────────────────────────
COLORS = {
    "production": "#FFD700",
    "consumption": "#FF6B6B",
    "self_consumption": "#4ECDC4",
    "grid_feed": "#45B7D1",
    "grid_draw": "#F77F00",
    "bg": "#0E1117",
    "card_bg": "#1A1C23",
}

# ─── CSS CUSTOM ──────────────────────────────────────────────
st.markdown("""
<style>
    .main-header { font-size: 2.5rem; font-weight: 800; color: #FFD700; margin-bottom: -1rem; }
    .sub-header { font-size: 1.1rem; color: #8B949E; margin-bottom: 2rem; }
    .kpi-card {
        background: linear-gradient(135deg, #1A1C23 0%, #252830 100%);
        border-radius: 16px; padding: 1.2rem 0.8rem; text-align: center;
        border: 1px solid #2D3139; box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        height: 120px; display: flex; flex-direction: column; justify-content: center;
    }
    .kpi-value { font-size: 1.7rem; font-weight: 700; margin: 0; line-height: 1.2; }
    .kpi-label { font-size: 0.75rem; color: #8B949E; text-transform: uppercase; letter-spacing: 1px; margin: 0; }
</style>
""", unsafe_allow_html=True)


# ─── PARSER ROBUSTO ──────────────────────────────────────────
def parse_energy_file(uploaded_file):
    """
    Legge il file Excel del FV e restituisce DataFrame pulito.
    Il file ha questa struttura:
      Riga 0: Intestazioni (Data e ora, Produzione totale, ...)
      Riga 1: Unità ([dd.MM.yyyy], [Wh], ...)  <-- DA SALTARE
      Riga 2+: Dati giornalieri
    """
    try:
        # Leggi TUTTO senza header, così abbiamo controllo totale
        df_raw = pd.read_excel(uploaded_file, header=None, engine='openpyxl')
    except Exception as e:
        raise ValueError(f"Errore lettura Excel: {e}. Verifica che il file sia un .xlsx valido.")

    # Il file deve avere almeno 6 colonne e 3 righe (header + unità + 1 dato)
    if df_raw.shape[1] < 5:
        raise ValueError(f"Il file ha solo {df_raw.shape[1]} colonne, ne servono almeno 5.")

    # Riga 0 = nomi colonne, Riga 1 = unità (da scartare), Righe 2+ = dati
    headers = [str(h).strip() for h in df_raw.iloc[0].tolist()]
    df = df_raw.iloc[2:].copy()          # salta header e riga unità
    df.columns = headers
    df = df.reset_index(drop=True)

    # ─── Mappa colonne (riconoscimento flessibile) ───
    COLUMN_MAP = {
        'Date':              ['data', 'giorno', 'date', 'dd.mm'],
        'Production_Wh':     ['produzione', 'production', 'prod'],
        'Consumption_Wh':    ['consumo', 'consumption', 'cons'],
        'SelfConsumption_Wh':['autoconsumo', 'self', 'auto'],
        'GridFeedIn_Wh':     ['alimentata', 'immessa', 'feed', 'in rete', 'grid feed'],
        'GridDraw_Wh':       ['prelevata', 'draw', 'da rete', 'grid draw', 'prelievo'],
    }

    rename_dict = {}
    found_cols = set()

    for target_name, keywords in COLUMN_MAP.items():
        for i, col_name in enumerate(headers):
            if col_name is None:
                continue
            col_lower = str(col_name).lower()
            if any(kw in col_lower for kw in keywords) and target_name not in found_cols:
                rename_dict[col_name] = target_name
                found_cols.add(target_name)
                break

    df.rename(columns=rename_dict, inplace=True)

    # Verifica colonne trovate
    required = ['Date', 'Production_Wh', 'Consumption_Wh']
    missing = [r for r in required if r not in df.columns]
    if missing:
        raise ValueError(
            f"Colonne non trovate: {missing}. "
            f"Colonne disponibili: {list(df.columns)}. "
            f"Verifica che il file abbia le intestazioni corrette."
        )

    # ─── Pulisci tipi ───────────────────────────────
    # Data
    date_col = df['Date']
    # Prima prova dayfirst (dd.MM.yyyy)
    date_parsed = pd.to_datetime(date_col, dayfirst=True, errors='coerce')
    # Se non funziona, prova senza dayfirst
    if date_parsed.notna().sum() < 10:
        date_parsed = pd.to_datetime(date_col, dayfirst=False, errors='coerce')
    df['Date'] = date_parsed

    # Rimuovi righe senza data valida
    before = len(df)
    df = df.dropna(subset=['Date']).copy()
    after = len(df)
    if after == 0:
        raise ValueError("Nessuna data valida trovata dopo la pulizia.")
    if before - after > 0:
        st.info(f"📎 {uploaded_file.name}: rimosse {before - after} righe senza data valida")

    # Colonne numeriche
    num_cols = ['Production_Wh', 'Consumption_Wh', 'SelfConsumption_Wh', 'GridFeedIn_Wh', 'GridDraw_Wh']
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)

    # Aggiungi colonne mancanti come 0
    for c in num_cols:
        if c not in df.columns:
            df[c] = 0

    # ─── Converti Wh → kWh ─────────────────────────
    for c in num_cols:
        df[c.replace('_Wh', '_kWh')] = df[c] / 1000

    # ─── Metriche derivate ─────────────────────────
    # Evita np.where che può dare problemi; usa .loc
    df['Autonomy_Ratio'] = 0.0
    df['SelfConsumption_Rate'] = 0.0

    mask_cons = df['Consumption_kWh'] > 0
    if mask_cons.any():
        df.loc[mask_cons, 'Autonomy_Ratio'] = (
            df.loc[mask_cons, 'SelfConsumption_kWh'] /
            df.loc[mask_cons, 'Consumption_kWh'] * 100
        ).round(1)

    mask_prod = df['Production_kWh'] > 0
    if mask_prod.any():
        df.loc[mask_prod, 'SelfConsumption_Rate'] = (
            df.loc[mask_prod, 'SelfConsumption_kWh'] /
            df.loc[mask_prod, 'Production_kWh'] * 100
        ).round(1)

    # ─── Colonne temporali ─────────────────────────
    df['Year'] = df['Date'].dt.year
    df['Month'] = df['Date'].dt.month
    df['MonthName'] = df['Date'].dt.month.apply(
        lambda x: calendar.month_abbr[x] if 1 <= x <= 12 else '???'
    )
    df['DayOfYear'] = df['Date'].dt.dayofyear
    df['Weekday'] = df['Date'].dt.dayofweek
    df['Source'] = uploaded_file.name

    return df


# ─── KPI ROW ─────────────────────────────────────────────────
def create_kpi_row(df):
    total = df['Production_kWh'].sum()
    consumo = df['Consumption_kWh'].sum()
    auto = df['SelfConsumption_kWh'].sum()
    immessa = df['GridFeedIn_kWh'].sum()
    prelevata = df['GridDraw_kWh'].sum()

    autonomia = (auto / consumo * 100) if consumo > 0 else 0
    autoconsumo_rate = (auto / total * 100) if total > 0 else 0

    cols = st.columns(7)
    kpis = [
        ("⚡ Produzione",   f"{total:,.0f}",      "kWh", COLORS["production"]),
        ("🔥 Consumo",      f"{consumo:,.0f}",    "kWh", COLORS["consumption"]),
        ("🏠 Autoconsumo",  f"{auto:,.0f}",       "kWh", COLORS["self_consumption"]),
        ("📤 In Rete",      f"{immessa:,.0f}",    "kWh", COLORS["grid_feed"]),
        ("📥 Da Rete",      f"{prelevata:,.0f}",  "kWh", COLORS["grid_draw"]),
        ("🎯 Autonomia",    f"{autonomia:.1f}",   "%",   "#FFFFFF"),
        ("♻️ Tasso Autoc.", f"{autoconsumo_rate:.1f}", "%", "#FFFFFF"),
    ]

    for col, (label, value, unit, color) in zip(cols, kpis):
        with col:
            st.markdown(f"""
            <div class="kpi-card">
                <p class="kpi-label">{label}</p>
                <p class="kpi-value" style="color:{color}">
                    {value} <span style="font-size:0.8rem;color:#8B949E">{unit}</span>
                </p>
            </div>
            """, unsafe_allow_html=True)


# ─── GRAFICI ─────────────────────────────────────────────────

def plot_daily_energy(df, col_y, title, color, show_ma=True):
    """Line chart giornaliero con media mobile opzionale."""
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df['Date'], y=df[col_y],
        mode='lines', name='Giornaliero',
        line=dict(color=color, width=1.5),
        fill='tozeroy',
        fillcolor=f'rgba{_hex_to_rgba(color, 0.12)}',
        hovertemplate='%{x|%d %b %Y}: <b>%{y:,.1f} kWh</b><extra></extra>'
    ))

    if show_ma and len(df) > 7:
        df_sorted = df.sort_values('Date')
        ma7 = df_sorted[col_y].rolling(7, center=True).mean()
        fig.add_trace(go.Scatter(
            x=df_sorted['Date'], y=ma7.values,
            mode='lines', name='Media 7gg',
            line=dict(color='white', width=2.5, dash='dot'),
            hovertemplate='Media: <b>%{y:,.1f} kWh</b><extra></extra>'
        ))

    fig.update_layout(
        title=title, title_font_size=15,
        hovermode='x unified',
        height=360,
        margin=dict(l=10, r=10, t=45, b=10),
        legend=dict(orientation='h', yanchor='top', y=1.14, xanchor='left', x=0, font_size=11),
        xaxis=dict(showgrid=False, dtick='M1', tickformat='%b', tickfont_size=10),
        yaxis=dict(title='kWh', gridcolor='rgba(255,255,255,0.06)', title_font_size=11),
        paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["bg"],
        font_color='#CCC',
    )
    return fig


def plot_monthly_comparison(df):
    """Bar chart mensile produzione vs consumo."""
    monthly = df.groupby(['Year', 'Month', 'MonthName']).agg(
        Production=('Production_kWh', 'sum'),
        Consumption=('Consumption_kWh', 'sum'),
    ).reset_index()
    monthly['Label'] = monthly['MonthName'] + " '" + monthly['Year'].astype(str).str[-2:]
    monthly = monthly.sort_values(['Year', 'Month'])

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=monthly['Label'], y=monthly['Production'],
        name='Produzione', marker_color=COLORS["production"],
        hovertemplate='%{x}: <b>%{y:,.0f} kWh</b><extra></extra>'
    ))
    fig.add_trace(go.Bar(
        x=monthly['Label'], y=monthly['Consumption'],
        name='Consumo', marker_color=COLORS["consumption"],
        hovertemplate='%{x}: <b>%{y:,.0f} kWh</b><extra></extra>'
    ))

    fig.update_layout(
        title='📊 Produzione vs Consumo Mensile',
        barmode='group', bargap=0.15,
        height=400,
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='top', y=1.12, xanchor='left', x=0),
        xaxis=dict(showgrid=False, tickangle=-45, tickfont_size=10),
        yaxis=dict(title='kWh', gridcolor='rgba(255,255,255,0.06)'),
        paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["bg"],
        font_color='#CCC',
    )
    return fig


def plot_energy_flow_sankey(df):
    """Sankey del flusso energetico annuale."""
    self_cons = df['SelfConsumption_kWh'].sum()
    grid_feed = df['GridFeedIn_kWh'].sum()
    grid_draw = df['GridDraw_kWh'].sum()

    fig = go.Figure(go.Sankey(
        arrangement='snap',
        node=dict(
            pad=18, thickness=28,
            line=dict(color='rgba(255,255,255,0.25)', width=1.2),
            label=['☀️ FV', '🏠 Casa', '🔌 Rete', '⚡ Consumo'],
            color=[COLORS["production"], COLORS["self_consumption"],
                   '#5A6377', COLORS["consumption"]],
            x=[0.05, 0.35, 0.5, 0.78],
            y=[0.4, 0.3, 0.7, 0.5],
        ),
        link=dict(
            source=[0, 0, 2],
            target=[1, 2, 3],
            value=[self_cons, grid_feed, grid_draw],
            color=[f'rgba(78,205,196,0.35)',
                   f'rgba(69,183,209,0.35)',
                   f'rgba(247,127,0,0.35)'],
            label=['Autoconsumo', 'Immessa', 'Prelievo'],
        )
    ))

    fig.update_layout(
        title='🔀 Flusso Energetico Totale',
        height=350,
        paper_bgcolor=COLORS["bg"],
        font=dict(size=13, color='#CCC'),
    )
    return fig


def plot_calendar_heatmap(df):
    """Heatmap calendario produzione."""
    df_cal = df.copy()
    df_cal['Week'] = df_cal['Date'].dt.isocalendar().week.astype(int)
    df_cal['DayOfWeek'] = df_cal['Date'].dt.dayofweek

    # Fix anno nuovo
    df_cal.loc[(df_cal['Month'] == 1) & (df_cal['Week'] > 50), 'Week'] = 0

    pivot = df_cal.pivot_table(
        values='Production_kWh', index='DayOfWeek', columns='Week', aggfunc='sum'
    ).fillna(0)

    days_it = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom']
    # Assicura ordine corretto
    pivot = pivot.reindex(range(7), fill_value=0)
    pivot.index = days_it

    fig = go.Figure(go.Heatmap(
        z=pivot.values,
        x=[f'W{w}' for w in pivot.columns],
        y=days_it,
        colorscale='YlOrRd',
        hovertemplate='%{y} W%{x}: <b>%{z:,.1f} kWh</b><extra></extra>',
        colorbar=dict(title='kWh', thickness=12, tickfont_size=10),
    ))

    fig.update_layout(
        title='🗓️ Heatmap Produzione Giornaliera',
        height=260,
        xaxis=dict(showgrid=False, tickfont_size=8),
        yaxis=dict(showgrid=False, tickfont_size=11),
        paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["bg"],
        font_color='#CCC',
    )
    return fig


def plot_multi_file_comparison(dfs_dict):
    """Compara produzione mensile tra più file."""
    fig = go.Figure()

    for name, df in dfs_dict.items():
        monthly = df.groupby('Month').agg({'Production_kWh': 'sum'}).reset_index()
        monthly['MonthName'] = monthly['Month'].apply(
            lambda x: calendar.month_abbr[int(x)] if 1 <= int(x) <= 12 else '?'
        )
        monthly = monthly.sort_values('Month')

        fig.add_trace(go.Scatter(
            x=monthly['MonthName'], y=monthly['Production_kWh'],
            mode='lines+markers', name=name[:30],
            line=dict(width=2.5), marker=dict(size=8),
            hovertemplate='%{x}: <b>%{y:,.0f} kWh</b><extra>%{fullData.name}</extra>'
        ))

    fig.update_layout(
        title='🏆 Comparazione Multi-File: Produzione Mensile',
        height=400,
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='top', y=1.12, xanchor='left', x=0),
        xaxis=dict(showgrid=False),
        yaxis=dict(title='kWh', gridcolor='rgba(255,255,255,0.06)'),
        paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["bg"],
        font_color='#CCC',
    )
    return fig


def plot_stacked_area(df):
    """Area stacked: autoconsumo + immessa + prelievo."""
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df['Date'], y=df['SelfConsumption_kWh'],
        mode='none', stackgroup='one', name='Autoconsumo',
        fillcolor=COLORS["self_consumption"],
        hovertemplate='%{x}: <b>%{y:,.1f} kWh</b><extra>Autoconsumo</extra>'
    ))
    fig.add_trace(go.Scatter(
        x=df['Date'], y=df['GridFeedIn_kWh'],
        mode='none', stackgroup='one', name='Immessa in Rete',
        fillcolor=COLORS["grid_feed"],
        hovertemplate='%{x}: <b>%{y:,.1f} kWh</b><extra>Immessa</extra>'
    ))
    fig.add_trace(go.Scatter(
        x=df['Date'], y=df['GridDraw_kWh'],
        mode='none', stackgroup='two', name='Prelievo da Rete',
        fillcolor=COLORS["grid_draw"],
        hovertemplate='%{x}: <b>%{y:,.1f} kWh</b><extra>Prelievo</extra>'
    ))

    fig.update_layout(
        title='📈 Ripartizione Giornaliera dei Flussi',
        height=360,
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='top', y=1.12, xanchor='left', x=0),
        xaxis=dict(showgrid=False),
        yaxis=dict(title='kWh', gridcolor='rgba(255,255,255,0.06)'),
        paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["bg"],
        font_color='#CCC',
    )
    return fig


def plot_gauge_indicators(df):
    """Gauge per autonomia e tasso autoconsumo."""
    autonomia = (df['SelfConsumption_kWh'].sum() / df['Consumption_kWh'].sum() * 100) \
        if df['Consumption_kWh'].sum() > 0 else 0
    autoconsumo = (df['SelfConsumption_kWh'].sum() / df['Production_kWh'].sum() * 100) \
        if df['Production_kWh'].sum() > 0 else 0

    fig = make_subplots(
        rows=2, cols=1,
        specs=[[{'type': 'indicator'}], [{'type': 'indicator'}]],
        vertical_spacing=0.12
    )

    fig.add_trace(go.Indicator(
        mode='gauge+number',
        value=autonomia,
        title={'text': '🎯 Grado di Autonomia', 'font': {'size': 15}},
        number={'suffix': '%', 'font': {'size': 38, 'color': '#4ECDC4'}},
        gauge={
            'axis': {'range': [0, 100], 'tickwidth': 1},
            'bar': {'color': '#4ECDC4', 'thickness': 0.18},
            'steps': [
                {'range': [0, 30], 'color': 'rgba(247,127,0,0.25)'},
                {'range': [30, 60], 'color': 'rgba(255,215,0,0.25)'},
                {'range': [60, 100], 'color': 'rgba(78,205,196,0.25)'},
            ],
        }
    ), row=1, col=1)

    fig.add_trace(go.Indicator(
        mode='gauge+number',
        value=autoconsumo,
        title={'text': '♻️ Tasso di Autoconsumo', 'font': {'size': 15}},
        number={'suffix': '%', 'font': {'size': 38, 'color': '#FFD700'}},
        gauge={
            'axis': {'range': [0, 100], 'tickwidth': 1},
            'bar': {'color': '#FFD700', 'thickness': 0.18},
            'steps': [
                {'range': [0, 30], 'color': 'rgba(247,127,0,0.25)'},
                {'range': [30, 60], 'color': 'rgba(255,215,0,0.25)'},
                {'range': [60, 100], 'color': 'rgba(78,205,196,0.25)'},
            ],
        }
    ), row=2, col=1)

    fig.update_layout(
        height=480,
        paper_bgcolor=COLORS["bg"],
        margin=dict(t=30, b=10),
        font_color='#CCC',
    )
    return fig


# ─── UTILITY ─────────────────────────────────────────────────
def _hex_to_rgba(hex_color, alpha):
    """Converte #RRGGBB → (R, G, B, alpha)."""
    h = hex_color.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (r, g, b, alpha)


def to_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='EnergyData')
    return output.getvalue()


# ═══════════════════════════════════════════════════════════════
# 🚀 MAIN APP
# ═══════════════════════════════════════════════════════════════

st.markdown('<p class="main-header">⚡ Energy Dashboard Pro</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Carica fino a 10 file • Grafici interattivi • Analisi completa</p>',
            unsafe_allow_html=True)

# ─── SIDEBAR ─────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📂 Carica File Excel")
    st.caption("I tuoi file di export dell'inverter (fino a 10)")

    uploaded_files = st.file_uploader(
        "Trascina qui i file",
        type=["xlsx", "xls"],
        accept_multiple_files=True,
        key="file_uploader"
    )

    if uploaded_files and len(uploaded_files) > 10:
        st.warning("⚠️ Massimo 10 file. Userò solo i primi 10.")
        uploaded_files = uploaded_files[:10]

    if uploaded_files:
        st.divider()
        st.markdown("### 🔍 Filtri")

        try:
            # Leggi rapidamente per estrarre il range date
            temp = pd.read_excel(uploaded_files[0], header=None, engine='openpyxl', nrows=5)
        except:
            temp = None

        default_start = pd.to_datetime("2023-01-01")
        default_end = pd.to_datetime("2023-12-31")

        date_range = st.date_input(
            "Intervallo date",
            value=(default_start, default_end),
            key="date_filter"
        )

        st.divider()
        st.markdown("### 📥 Export")
        st.caption("Scarica tutti i dati elaborati")

        st.divider()
        st.markdown("### ℹ️ Formato Atteso")
        st.markdown("""
        ```
        Data e ora
        Produzione totale [Wh]
        Consumo totale [Wh]
        Autoconsumo [Wh]
        Energia alimentata nella rete [Wh]
        Energia prelevata dalla rete [Wh]
        ```
        """)

# ─── BODY ────────────────────────────────────────────────────
if not uploaded_files:
    col_a, col_b, col_c = st.columns([1, 2, 1])
    with col_b:
        st.markdown("""
        <div style="text-align:center; padding:4rem 2rem; background:#1A1C23;
                    border-radius:20px; border:2px dashed #2D3139; margin-top:3rem;">
            <h2 style="color:#8B949E;">📁 Nessun file caricato</h2>
            <p style="color:#5A6377;">Carica i tuoi file Excel dell'inverter<br>
            nella sidebar per visualizzare la dashboard.</p>
            <p style="color:#FFD700; font-size:0.85rem;">⚡ Fino a 10 file • Multi-anno • Confronti</p>
        </div>
        """, unsafe_allow_html=True)

    st.stop()


# ═══ PARSE FILES ═══
all_dfs = []
dfs_dict = {}
errors = []

with st.spinner("🔄 Elaborazione file in corso..."):
    for f in uploaded_files:
        try:
            df = parse_energy_file(f)
            if len(df) > 0:
                all_dfs.append(df)
                # Nome corto per legenda
                short_name = f.name.replace('.xlsx', '').replace('.xls', '')
                # Estrai anno dal nome o dai dati
                if df['Year'].nunique() == 1:
                    short_name = f"{short_name} ({int(df['Year'].iloc[0])})"
                dfs_dict[short_name] = df
            else:
                errors.append(f"⚠️ {f.name}: nessun dato valido")
        except Exception as e:
            errors.append(f"❌ {f.name}: {str(e)}")

for err in errors:
    st.error(err)

if not all_dfs:
    st.error("🚫 Nessun file valido processato. Controlla il formato.")
    st.stop()

# ═══ UNISCI E FILTRA ═══
df_all = pd.concat(all_dfs, ignore_index=True)

# Applica filtro date
if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
    start_date, end_date = date_range
    if start_date and end_date:
        df_all = df_all[
            (df_all['Date'] >= pd.Timestamp(start_date)) &
            (df_all['Date'] <= pd.Timestamp(end_date))
        ]

if df_all.empty:
    st.error("Nessun dato nell'intervallo selezionato.")
    st.stop()

# ═══ KPI ═══
st.markdown("---")
create_kpi_row(df_all)
st.markdown("---")

# ═══ TABS ═══
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📈 Trend Giornalieri", "📊 Analisi Mensile", "🔀 Flussi & Bilancio",
    "🗓️ Calendario", "📋 Dati & Export"
])

with tab1:
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(
            plot_daily_energy(df_all, 'Production_kWh',
                              '☀️ Produzione Giornaliera', COLORS["production"]),
            use_container_width=True
        )
    with c2:
        st.plotly_chart(
            plot_daily_energy(df_all, 'Consumption_kWh',
                              '🔥 Consumo Giornaliero', COLORS["consumption"]),
            use_container_width=True
        )

    c3, c4 = st.columns(2)
    with c3:
        st.plotly_chart(
            plot_daily_energy(df_all, 'GridFeedIn_kWh',
                              '📤 Energia Immessa in Rete', COLORS["grid_feed"], show_ma=False),
            use_container_width=True
        )
    with c4:
        st.plotly_chart(
            plot_daily_energy(df_all, 'GridDraw_kWh',
                              '📥 Energia Prelevata dalla Rete', COLORS["grid_draw"], show_ma=False),
            use_container_width=True
        )

    st.plotly_chart(plot_stacked_area(df_all), use_container_width=True)

with tab2:
    cm1, cm2 = st.columns([3, 2])
    with cm1:
        st.plotly_chart(plot_monthly_comparison(df_all), use_container_width=True)

    with cm2:
        monthly_table = df_all.groupby(['MonthName', 'Year']).agg(
            Produzione_kWh=('Production_kWh', 'sum'),
            Consumo_kWh=('Consumption_kWh', 'sum'),
            Autoconsumo_kWh=('SelfConsumption_kWh', 'sum'),
            Media_Autonomia=('Autonomy_Ratio', 'mean'),
        ).round(1).reset_index()

        monthly_table['Mese'] = monthly_table['MonthName'] + ' ' + monthly_table['Year'].astype(str)
        # Riordina
        monthly_table['_sort'] = monthly_table['Year'].astype(str) + \
            monthly_table['MonthName'].apply(
                lambda x: str(list(calendar.month_abbr).index(x)).zfill(2)
                if x in calendar.month_abbr else '99'
            )
        monthly_table = monthly_table.sort_values('_sort')

        st.markdown("#### 📋 Riepilogo Mensile")
        st.dataframe(
            monthly_table[['Mese', 'Produzione_kWh', 'Consumo_kWh',
                           'Autoconsumo_kWh', 'Media_Autonomia']],
            use_container_width=True,
            hide_index=True,
            column_config={
                'Mese': 'Mese',
                'Produzione_kWh': st.column_config.NumberColumn('Prod. kWh', format='%.0f'),
                'Consumo_kWh': st.column_config.NumberColumn('Cons. kWh', format='%.0f'),
                'Autoconsumo_kWh': st.column_config.NumberColumn('Autocons. kWh', format='%.0f'),
                'Media_Autonomia': st.column_config.NumberColumn('Auton. %', format='%.1f%%'),
            }
        )

    if len(dfs_dict) > 1:
        st.plotly_chart(plot_multi_file_comparison(dfs_dict), use_container_width=True)

with tab3:
    cs1, cs2 = st.columns([1, 1])
    with cs1:
        st.plotly_chart(plot_energy_flow_sankey(df_all), use_container_width=True)
    with cs2:
        st.plotly_chart(plot_gauge_indicators(df_all), use_container_width=True)

    # Donut charts
    st.markdown("### 🥧 Ripartizione Energetica")
    cp1, cp2 = st.columns(2)

    with cp1:
        vals_prod = [df_all['SelfConsumption_kWh'].sum(), df_all['GridFeedIn_kWh'].sum()]
        if sum(vals_prod) > 0:
            fig_d1 = go.Figure(go.Pie(
                labels=['Autoconsumo', 'Immessa in Rete'],
                values=vals_prod,
                marker_colors=[COLORS["self_consumption"], COLORS["grid_feed"]],
                hole=0.55, textinfo='percent+value',
                texttemplate='%{percent:.1%}<br>%{value:,.0f} kWh',
            ))
            fig_d1.update_layout(
                title='Dove va la Produzione', height=340,
                paper_bgcolor=COLORS["bg"], font_color='#CCC',
            )
            st.plotly_chart(fig_d1, use_container_width=True)
        else:
            st.info("Nessun dato di produzione")

    with cp2:
        vals_cons = [df_all['SelfConsumption_kWh'].sum(), df_all['GridDraw_kWh'].sum()]
        if sum(vals_cons) > 0:
            fig_d2 = go.Figure(go.Pie(
                labels=['Autoconsumo', 'Prelievo da Rete'],
                values=vals_cons,
                marker_colors=[COLORS["self_consumption"], COLORS["grid_draw"]],
                hole=0.55, textinfo='percent+value',
                texttemplate='%{percent:.1%}<br>%{value:,.0f} kWh',
            ))
            fig_d2.update_layout(
                title='Da dove viene il Consumo', height=340,
                paper_bgcolor=COLORS["bg"], font_color='#CCC',
            )
            st.plotly_chart(fig_d2, use_container_width=True)
        else:
            st.info("Nessun dato di consumo")

with tab4:
    st.plotly_chart(plot_calendar_heatmap(df_all), use_container_width=True)

    st.markdown("### 📊 Medie Giornaliere per Mese")
    daily_avg = df_all.groupby(['MonthName', 'Month']).agg(
        Prod_Media=('Production_kWh', 'mean'),
        Cons_Media=('Consumption_kWh', 'mean'),
        Giorni=('Date', 'count'),
    ).round(1).sort_values('Month').reset_index()

    fig_avg = go.Figure()
    fig_avg.add_trace(go.Bar(
        x=daily_avg['MonthName'], y=daily_avg['Prod_Media'],
        name='Prod. Media', marker_color=COLORS["production"],
        text=daily_avg['Prod_Media'].round(0).astype(str),
        textposition='outside', textfont_size=11,
    ))
    fig_avg.add_trace(go.Bar(
        x=daily_avg['MonthName'], y=daily_avg['Cons_Media'],
        name='Cons. Media', marker_color=COLORS["consumption"],
        text=daily_avg['Cons_Media'].round(0).astype(str),
        textposition='outside', textfont_size=11,
    ))
    fig_avg.update_layout(
        barmode='group', height=340,
        paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["bg"],
        xaxis=dict(showgrid=False),
        yaxis=dict(title='kWh/giorno', gridcolor='rgba(255,255,255,0.06)'),
        legend=dict(orientation='h', yanchor='top', y=1.12),
        font_color='#CCC',
    )
    st.plotly_chart(fig_avg, use_container_width=True)

with tab5:
    st.markdown("### 📋 Dati Giornalieri")
    display_cols = ['Date', 'Production_kWh', 'Consumption_kWh',
                    'SelfConsumption_kWh', 'GridFeedIn_kWh', 'GridDraw_kWh',
                    'Autonomy_Ratio', 'SelfConsumption_Rate', 'Source']

    st.dataframe(
        df_all[display_cols].sort_values('Date', ascending=False),
        use_container_width=True,
        hide_index=True,
        column_config={
            'Date': st.column_config.DateColumn('Data', format='DD/MM/YYYY'),
            'Production_kWh': st.column_config.NumberColumn('Prod. kWh', format='%.1f'),
            'Consumption_kWh': st.column_config.NumberColumn('Cons. kWh', format='%.1f'),
            'SelfConsumption_kWh': st.column_config.NumberColumn('Autocons. kWh', format='%.1f'),
            'GridFeedIn_kWh': st.column_config.NumberColumn('Immessa kWh', format='%.1f'),
            'GridDraw_kWh': st.column_config.NumberColumn('Prelievo kWh', format='%.1f'),
            'Autonomy_Ratio': st.column_config.NumberColumn('Autonomia %', format='%.1f%%'),
            'SelfConsumption_Rate': st.column_config.NumberColumn('Tasso Autoc. %', format='%.1f%%'),
            'Source': 'File Origine',
        }
    )

    excel_data = to_excel(df_all)
    st.download_button(
        label='📥 Scarica Dati Elaborati (Excel)',
        data=excel_data,
        file_name='energy_dashboard_export.xlsx',
        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )

# ═══ FOOTER ═══
st.markdown("---")
st.caption(
    f"📁 {len(dfs_dict)} file caricati • "
    f"📊 {len(df_all):,} giorni di dati • "
    f"📅 {df_all['Date'].min().strftime('%d/%m/%Y')} → {df_all['Date'].max().strftime('%d/%m/%Y')} • "
    f"⚡ Energy Dashboard Pro v1.0"
)
