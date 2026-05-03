import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import plotly.io as pio
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

# ─── TEMA DARK/PRO Plotly ────────────────────────────────────
pio.templates.default = "plotly_dark"

# Colori brand professionali
COLORS = {
    "production": "#FFD700",      # oro
    "consumption": "#FF6B6B",     # rosso corallo
    "self_consumption": "#4ECDC4",# teal
    "grid_feed": "#45B7D1",       # blu cielo
    "grid_draw": "#F77F00",       # arancione
    "bg": "#0E1117",
    "card_bg": "#1A1C23",
    "text": "#FAFAFA",
}

# ─── CSS CUSTOM ──────────────────────────────────────────────
st.markdown("""
<style>
    .main-header { font-size: 2.5rem; font-weight: 800; color: #FFD700; margin-bottom: -1rem; }
    .sub-header { font-size: 1.1rem; color: #8B949E; margin-bottom: 2rem; }
    .kpi-card {
        background: linear-gradient(135deg, #1A1C23 0%, #252830 100%);
        border-radius: 16px; padding: 1.5rem 1.2rem; text-align: center;
        border: 1px solid #2D3139; box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    .kpi-value { font-size: 2rem; font-weight: 700; margin: 0; }
    .kpi-label { font-size: 0.8rem; color: #8B949E; text-transform: uppercase; letter-spacing: 1px; }
    .st-emotion-cache-1v0mbdj { border-radius: 12px; }
</style>
""", unsafe_allow_html=True)

# ─── FUNZIONI UTILITY ────────────────────────────────────────
@st.cache_data
def parse_energy_file(uploaded_file):
    """Parsa il file Excel e restituisce un DataFrame pulito."""
    try:
        # Prova a leggere con pandas (gestisce .xlsx)
        df = pd.read_excel(uploaded_file, engine='openpyxl')
    except:
        # Fallback: prova come CSV con vari delimitatori
        uploaded_file.seek(0)
        content = uploaded_file.read().decode('utf-8', errors='ignore')
        uploaded_file.seek(0)
        df = pd.read_csv(BytesIO(content.encode()), sep=None, engine='python')
    
    # Rinomina colonne in italiano → inglese semplificato
    col_map = {}
    for col in df.columns:
        col_lower = str(col).lower().strip()
        if 'data' in col_lower:
            col_map[col] = 'Date'
        elif 'produzione' in col_lower:
            col_map[col] = 'Production_Wh'
        elif 'consumo' in col_lower:
            col_map[col] = 'Consumption_Wh'
        elif 'autoconsumo' in col_lower:
            col_map[col] = 'SelfConsumption_Wh'
        elif 'alimentata' in col_lower or 'immessa' in col_lower:
            col_map[col] = 'GridFeedIn_Wh'
        elif 'prelevata' in col_lower:
            col_map[col] = 'GridDraw_Wh'
    
    df.rename(columns=col_map, inplace=True)
    
    # Converti la colonna date
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')
    else:
        # Cerca la prima colonna che sembra una data
        for col in df.columns:
            try:
                df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
                if df[col].notna().sum() > 10:
                    df.rename(columns={col: 'Date'}, inplace=True)
                    break
            except:
                continue
    
    # Pulisci colonne numeriche
    num_cols = ['Production_Wh', 'Consumption_Wh', 'SelfConsumption_Wh', 'GridFeedIn_Wh', 'GridDraw_Wh']
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    
    # Converti Wh → kWh
    for c in num_cols:
        if c in df.columns:
            df[c.replace('_Wh', '_kWh')] = df[c] / 1000
    
    # Aggiungi colonne temporali
    if 'Date' in df.columns:
        df['Year'] = df['Date'].dt.year
        df['Month'] = df['Date'].dt.month
        df['MonthName'] = df['Date'].dt.month.apply(lambda x: calendar.month_abbr[x])
        df['DayOfYear'] = df['Date'].dt.dayofyear
        df['Weekday'] = df['Date'].dt.weekday
    
    # Calcola metriche derivate
    df['Autonomy_Ratio'] = np.where(
        df['Consumption_kWh'] > 0,
        (df['SelfConsumption_kWh'] / df['Consumption_kWh'] * 100).round(1),
        0
    )
    df['SelfConsumption_Rate'] = np.where(
        df['Production_kWh'] > 0,
        (df['SelfConsumption_kWh'] / df['Production_kWh'] * 100).round(1),
        0
    )
    
    # Estrai nome file
    df['Source'] = uploaded_file.name
    
    return df.dropna(subset=['Date'])

def create_kpi_row(df_all):
    """Crea la riga KPI in alto."""
    total = df_all['Production_kWh'].sum()
    consumo = df_all['Consumption_kWh'].sum()
    auto = df_all['SelfConsumption_kWh'].sum()
    immessa = df_all['GridFeedIn_kWh'].sum()
    prelevata = df_all['GridDraw_kWh'].sum()
    
    autonomia = (auto / consumo * 100) if consumo > 0 else 0
    autoconsumo_rate = (auto / total * 100) if total > 0 else 0
    
    cols = st.columns(7)
    kpis = [
        ("⚡ Produzione", f"{total:,.0f}", "kWh", COLORS["production"]),
        ("🔥 Consumo", f"{consumo:,.0f}", "kWh", COLORS["consumption"]),
        ("🏠 Autoconsumo", f"{auto:,.0f}", "kWh", COLORS["self_consumption"]),
        ("📤 In Rete", f"{immessa:,.0f}", "kWh", COLORS["grid_feed"]),
        ("📥 Da Rete", f"{prelevata:,.0f}", "kWh", COLORS["grid_draw"]),
        ("🎯 Autonomia", f"{autonomia:.1f}", "%", "#FFFFFF"),
        ("♻️ Autoconsumo", f"{autoconsumo_rate:.1f}", "%", "#FFFFFF"),
    ]
    
    for col, (label, value, unit, color) in zip(cols, kpis):
        with col:
            st.markdown(f"""
            <div class="kpi-card">
                <p class="kpi-label">{label}</p>
                <p class="kpi-value" style="color:{color}">{value} <span style="font-size:0.9rem;color:#8B949E">{unit}</span></p>
            </div>
            """, unsafe_allow_html=True)

# ─── GRAFICI INTERATTIVI ─────────────────────────────────────

def plot_daily_energy(df, col_y, title, color, show_ma=True):
    """Linea giornaliera con media mobile."""
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=df['Date'], y=df[col_y],
        mode='lines', name='Giornaliero',
        line=dict(color=color, width=1.5),
        fill='tozeroy',
        fillcolor=f'rgba{tuple(list(int(color.lstrip("#")[i:i+2], 16) for i in (0, 2, 4)) + [0.15])}',
        hovertemplate='%{x|%d %b %Y}: <b>%{y:,.1f} kWh</b><extra></extra>'
    ))
    
    if show_ma and len(df) > 7:
        df_temp = df.set_index('Date').sort_index()
        ma7 = df_temp[col_y].rolling(7, center=True).mean()
        fig.add_trace(go.Scatter(
            x=ma7.index, y=ma7.values,
            mode='lines', name='Media 7gg',
            line=dict(color='white', width=2.5, dash='dot'),
            hovertemplate='Media: <b>%{y:,.1f} kWh</b><extra></extra>'
        ))
    
    fig.update_layout(
        title=title, title_font_size=16,
        hovermode='x unified',
        height=380,
        margin=dict(l=20, r=20, t=50, b=20),
        legend=dict(orientation='h', yanchor='top', y=1.15, xanchor='left', x=0),
        xaxis=dict(showgrid=False, dtick='M1', tickformat='%b'),
        yaxis=dict(title='kWh', gridcolor='rgba(255,255,255,0.08)'),
        paper_bgcolor=COLORS["bg"],
        plot_bgcolor=COLORS["bg"],
    )
    return fig

def plot_monthly_comparison(df):
    """Bar chart mensile produzione vs consumo."""
    monthly = df.groupby(['Year', 'Month', 'MonthName']).agg(
        Production=('Production_kWh', 'sum'),
        Consumption=('Consumption_kWh', 'sum'),
        SelfConsumption=('SelfConsumption_kWh', 'sum'),
        GridFeedIn=('GridFeedIn_kWh', 'sum'),
        GridDraw=('GridDraw_kWh', 'sum'),
    ).reset_index()
    monthly['MonthSort'] = monthly['Year'].astype(str) + '-' + monthly['Month'].astype(str).str.zfill(2)
    monthly = monthly.sort_values('MonthSort')
    
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=monthly['MonthName'] + ' ' + monthly['Year'].astype(str),
        y=monthly['Production'], name='Produzione',
        marker_color=COLORS["production"], marker_line_width=0,
        hovertemplate='%{x}: <b>%{y:,.0f} kWh</b><extra></extra>'
    ))
    fig.add_trace(go.Bar(
        x=monthly['MonthName'] + ' ' + monthly['Year'].astype(str),
        y=monthly['Consumption'], name='Consumo',
        marker_color=COLORS["consumption"], marker_line_width=0,
        hovertemplate='%{x}: <b>%{y:,.0f} kWh</b><extra></extra>'
    ))
    
    fig.update_layout(
        title='📊 Produzione vs Consumo Mensile',
        barmode='group', bargap=0.15, bargroupgap=0.1,
        height=400,
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='top', y=1.12, xanchor='left', x=0),
        xaxis=dict(showgrid=False, tickangle=-45),
        yaxis=dict(title='kWh', gridcolor='rgba(255,255,255,0.08)'),
        paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["bg"],
    )
    return fig

def plot_energy_flow_sankey(df):
    """Diagramma Sankey del flusso energetico."""
    total_prod = df['Production_kWh'].sum()
    total_cons = df['Consumption_kWh'].sum()
    self_cons = df['SelfConsumption_kWh'].sum()
    grid_feed = df['GridFeedIn_kWh'].sum()
    grid_draw = df['GridDraw_kWh'].sum()
    
    fig = go.Figure(go.Sankey(
        arrangement='snap',
        node=dict(
            pad=20, thickness=30,
            line=dict(color='rgba(255,255,255,0.3)', width=1.5),
            label=['☀️ Fotovoltaico', '🏠 Casa', '🔌 Rete Elettrica', '⚡ Consumo Totale'],
            color=[COLORS["production"], COLORS["self_consumption"], '#5A6377', COLORS["consumption"]],
            x=[0.05, 0.35, 0.5, 0.8],
            y=[0.4, 0.3, 0.7, 0.5],
        ),
        link=dict(
            source=[0, 0, 2],
            target=[1, 2, 3],
            value=[self_cons, grid_feed, grid_draw],
            color=[f'rgba(78,205,196,0.35)', f'rgba(69,183,209,0.35)', f'rgba(247,127,0,0.35)'],
            label=['Autoconsumo', 'Immessa in Rete', 'Prelievo da Rete'],
        )
    ))
    
    fig.update_layout(
        title='🔀 Flusso Energetico Annuale',
        height=380,
        paper_bgcolor=COLORS["bg"],
        font=dict(size=13),
    )
    return fig

def plot_calendar_heatmap(df):
    """Heatmap calendario della produzione."""
    if 'Date' not in df.columns:
        return go.Figure()
    
    df_cal = df.copy()
    df_cal['Week'] = df_cal['Date'].dt.isocalendar().week.astype(int)
    df_cal['DayOfWeek'] = df_cal['Date'].dt.dayofweek  # 0=Lunedì
    
    # Gestisci anno nuovo
    for idx, row in df_cal.iterrows():
        if row['Month'] == 1 and row['Week'] > 50:
            df_cal.at[idx, 'Week'] = 0
    
    # Pivot
    pivot = df_cal.pivot_table(
        values='Production_kWh', index='DayOfWeek', columns='Week', aggfunc='sum'
    ).fillna(0)
    
    days_it = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom']
    pivot.index = [days_it[i] for i in pivot.index]
    
    fig = go.Figure(go.Heatmap(
        z=pivot.values,
        x=[f'W{w}' for w in pivot.columns],
        y=pivot.index.tolist(),
        colorscale='YlOrRd',
        hovertemplate='Week %{x}, %{y}: <b>%{z:,.1f} kWh</b><extra></extra>',
        colorbar=dict(title='kWh', thickness=15),
    ))
    
    fig.update_layout(
        title='🗓️ Heatmap Produzione Giornaliera',
        height=280,
        xaxis=dict(showgrid=False, tickfont_size=9),
        yaxis=dict(showgrid=False, tickfont_size=11),
        paper_bgcolor=COLORS["bg"],
        plot_bgcolor=COLORS["bg"],
    )
    return fig

def plot_multi_file_comparison(dfs_dict):
    """Compara produzione mensile tra più file."""
    fig = go.Figure()
    
    for name, df in dfs_dict.items():
        monthly = df.groupby('Month').agg({'Production_kWh': 'sum'}).reset_index()
        monthly['MonthName'] = monthly['Month'].apply(lambda x: calendar.month_abbr[x])
        
        fig.add_trace(go.Scatter(
            x=monthly['MonthName'], y=monthly['Production_kWh'],
            mode='lines+markers', name=name[:25],
            line=dict(width=2.5), marker=dict(size=8),
            hovertemplate='%{x}: <b>%{y:,.0f} kWh</b><extra>%{fullData.name}</extra>'
        ))
    
    fig.update_layout(
        title='🏆 Comparazione Multi-File: Produzione Mensile',
        height=420,
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='top', y=1.12, xanchor='left', x=0),
        xaxis=dict(showgrid=False),
        yaxis=dict(title='kWh', gridcolor='rgba(255,255,255,0.08)'),
        paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["bg"],
    )
    return fig

def plot_stacked_area(df):
    """Area chart stacked: autoconsumo + immessa + prelievo."""
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=df['Date'], y=df['SelfConsumption_kWh'],
        mode='none', stackgroup='one', name='Autoconsumo',
        fillcolor=COLORS["self_consumption"],
        hovertemplate='%{x}: <b>%{y:,.1f} kWh</b><extra>Autoconsumo</extra>'
    ))
    fig.add_trace(go.Scatter(
        x=df['Date'], y=df['GridFeedIn_kWh'],
        mode='none', stackgroup='one', name='Immessa',
        fillcolor=COLORS["grid_feed"],
        hovertemplate='%{x}: <b>%{y:,.1f} kWh</b><extra>Immessa</extra>'
    ))
    fig.add_trace(go.Scatter(
        x=df['Date'], y=df['GridDraw_kWh'],
        mode='none', stackgroup='two', name='Prelievo',
        fillcolor=COLORS["grid_draw"],
        hovertemplate='%{x}: <b>%{y:,.1f} kWh</b><extra>Prelievo</extra>'
    ))
    
    fig.update_layout(
        title='📈 Ripartizione Giornaliera Flussi',
        height=380,
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='top', y=1.12, xanchor='left', x=0),
        xaxis=dict(showgrid=False),
        yaxis=dict(title='kWh', gridcolor='rgba(255,255,255,0.08)'),
        paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["bg"],
    )
    return fig

# ─── EXCEL EXPORT ────────────────────────────────────────────
@st.cache_data
def to_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='EnergyData')
    return output.getvalue()

# ═══════════════════════════════════════════════════════════════
# 🚀 MAIN APP
# ═══════════════════════════════════════════════════════════════

st.markdown('<p class="main-header">⚡ Energy Dashboard Pro</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Monitora, analizza e compara i tuoi dati energetici da fotovoltaico</p>', unsafe_allow_html=True)

# ─── SIDEBAR ─────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📂 Carica File")
    st.markdown("Carica fino a **10 file** Excel/CSV dei tuoi dati energetici.")
    
    uploaded_files = st.file_uploader(
        "Trascina qui i file",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=True,
        key="file_uploader",
        help="Formato atteso: colonne Data, Produzione, Consumo, Autoconsumo, Energia immessa, Energia prelevata"
    )
    
    if uploaded_files and len(uploaded_files) > 10:
        st.warning("⚠️ Massimo 10 file. Verranno usati solo i primi 10.")
        uploaded_files = uploaded_files[:10]
    
    st.divider()
    
    # Filtri data
    if uploaded_files:
        st.markdown("### 🔍 Filtri")
        date_range = st.date_input(
            "Intervallo date",
            value=(pd.to_datetime("2023-01-01"), pd.to_datetime("2023-12-31")),
            key="date_filter"
        )
        
        st.divider()
        st.markdown("### 📥 Export")
        st.caption("Scarica i dati elaborati in Excel")
        
        st.divider()
        st.markdown("### ℹ️ Info")
        st.markdown("""
        **Colonne attese:**
        - Data e ora
        - Produzione totale [Wh]
        - Consumo totale [Wh]
        - Autoconsumo [Wh]
        - Energia alimentata nella rete [Wh]
        - Energia prelevata dalla rete [Wh]
        """)

# ─── BODY ────────────────────────────────────────────────────
if not uploaded_files:
    # Stato vuoto
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("""
        <div style="text-align:center; padding:4rem 2rem; background:#1A1C23; border-radius:20px; border:2px dashed #2D3139; margin-top:3rem;">
            <h2 style="color:#8B949E;">📁 Nessun file caricato</h2>
            <p style="color:#5A6377;">Carica i tuoi file Excel nella sidebar<br>per visualizzare dashboard e analisi.</p>
            <p style="color:#FFD700; font-size:0.85rem;">Supporta fino a 10 file simultaneamente</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Demo
        st.markdown("---")
        st.markdown("### 📋 Formato file atteso")
        st.markdown("""
        Il tuo file Excel deve contenere queste colonne (in italiano):
        ```
        Data e ora | Produzione totale [Wh] | Consumo totale [Wh] | Autoconsumo [Wh] | Energia alimentata nella rete [Wh] | Energia prelevata dalla rete [Wh]
        18.01.2023 | 2832                  | 15702               | 3731             | 52                                 | 11971
        ...
        ```
        """)
else:
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
                    dfs_dict[f.name] = df
                else:
                    errors.append(f"⚠️ {f.name}: nessun dato valido trovato")
            except Exception as e:
                errors.append(f"❌ {f.name}: {str(e)}")
    
    if errors:
        for err in errors:
            st.warning(err)
    
    if not all_dfs:
        st.error("Nessun file valido processato. Controlla il formato.")
        st.stop()
    
    # ═══ UNISCI DATI ═══
    df_all = pd.concat(all_dfs, ignore_index=True)
    
    # Applica filtro date
    if 'date_filter' in st.session_state and len(date_range) == 2:
        start_date, end_date = date_range
        df_all = df_all[(df_all['Date'] >= pd.Timestamp(start_date)) & 
                        (df_all['Date'] <= pd.Timestamp(end_date))]
    
    if df_all.empty:
        st.error("Nessun dato nell'intervallo selezionato.")
        st.stop()
    
    # ═══ KPI ROW ═══
    create_kpi_row(df_all)
    
    # ═══ TABS ═══
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📈 Trend", "📊 Mensile", "🔀 Flussi", "🗓️ Calendario", "📋 Dati"
    ])
    
    with tab1:
        st.markdown("### Andamento Giornaliero")
        
        col_left, col_right = st.columns(2)
        with col_left:
            st.plotly_chart(
                plot_daily_energy(df_all, 'Production_kWh', '☀️ Produzione Giornaliera', COLORS["production"]),
                use_container_width=True
            )
        with col_right:
            st.plotly_chart(
                plot_daily_energy(df_all, 'Consumption_kWh', '🔥 Consumo Giornaliero', COLORS["consumption"]),
                use_container_width=True
            )
        
        col_left2, col_right2 = st.columns(2)
        with col_left2:
            st.plotly_chart(
                plot_daily_energy(df_all, 'GridFeedIn_kWh', '📤 Energia Immessa in Rete', COLORS["grid_feed"], show_ma=False),
                use_container_width=True
            )
        with col_right2:
            st.plotly_chart(
                plot_daily_energy(df_all, 'GridDraw_kWh', '📥 Energia Prelevata dalla Rete', COLORS["grid_draw"], show_ma=False),
                use_container_width=True
            )
        
        # Stacked area
        st.plotly_chart(plot_stacked_area(df_all), use_container_width=True)
    
    with tab2:
        col_m1, col_m2 = st.columns([3, 2])
        with col_m1:
            st.plotly_chart(plot_monthly_comparison(df_all), use_container_width=True)
        
        with col_m2:
            # Metriche mensili in tabella
            monthly_table = df_all.groupby(['MonthName', 'Year']).agg(
                Produzione_kWh=('Production_kWh', 'sum'),
                Consumo_kWh=('Consumption_kWh', 'sum'),
                Autoconsumo_kWh=('SelfConsumption_kWh', 'sum'),
                Autonomia_pct=('Autonomy_Ratio', 'mean'),
            ).round(1).reset_index()
            monthly_table['Mese'] = monthly_table['MonthName'] + ' ' + monthly_table['Year'].astype(str)
            monthly_table = monthly_table.sort_values(['Year', 'MonthName'], 
                                key=lambda x: pd.to_datetime(x, format='%b %Y', errors='coerce') if x.name == 'Mese' else x)
            
            st.markdown("#### 📋 Riepilogo Mensile")
            st.dataframe(
                monthly_table[['Mese', 'Produzione_kWh', 'Consumo_kWh', 'Autoconsumo_kWh', 'Autonomia_pct']],
                use_container_width=True,
                hide_index=True,
                column_config={
                    'Mese': 'Mese',
                    'Produzione_kWh': st.column_config.NumberColumn('Prod. kWh', format='%.0f'),
                    'Consumo_kWh': st.column_config.NumberColumn('Cons. kWh', format='%.0f'),
                    'Autoconsumo_kWh': st.column_config.NumberColumn('Autocons. kWh', format='%.0f'),
                    'Autonomia_pct': st.column_config.NumberColumn('Autonomia %', format='%.1f%%'),
                }
            )
        
        # Comparazione multi-file
        if len(dfs_dict) > 1:
            st.plotly_chart(plot_multi_file_comparison(dfs_dict), use_container_width=True)
    
    with tab3:
        col_s1, col_s2 = st.columns([1, 1])
        with col_s1:
            st.plotly_chart(plot_energy_flow_sankey(df_all), use_container_width=True)
        
        with col_s2:
            # Gauge indicatori
            autonomia = (df_all['SelfConsumption_kWh'].sum() / df_all['Consumption_kWh'].sum() * 100) if df_all['Consumption_kWh'].sum() > 0 else 0
            autoconsumo = (df_all['SelfConsumption_kWh'].sum() / df_all['Production_kWh'].sum() * 100) if df_all['Production_kWh'].sum() > 0 else 0
            
            fig_gauge = make_subplots(rows=2, cols=1, specs=[[{'type': 'indicator'}], [{'type': 'indicator'}]],
                                       vertical_spacing=0.15)
            
            fig_gauge.add_trace(go.Indicator(
                mode='gauge+number+delta',
                value=autonomia,
                title={'text': '🎯 Grado di Autonomia', 'font': {'size': 16}},
                number={'suffix': '%', 'font': {'size': 40, 'color': '#4ECDC4'}},
                gauge={
                    'axis': {'range': [0, 100], 'tickwidth': 1},
                    'bar': {'color': '#4ECDC4', 'thickness': 0.2},
                    'steps': [
                        {'range': [0, 30], 'color': 'rgba(247,127,0,0.3)'},
                        {'range': [30, 60], 'color': 'rgba(255,215,0,0.3)'},
                        {'range': [60, 100], 'color': 'rgba(78,205,196,0.3)'},
                    ],
                    'threshold': {'line': {'color': 'white', 'width': 3}, 'value': autonomia, 'thickness': 0.8}
                }
            ), row=1, col=1)
            
            fig_gauge.add_trace(go.Indicator(
                mode='gauge+number+delta',
                value=autoconsumo,
                title={'text': '♻️ Tasso Autoconsumo', 'font': {'size': 16}},
                number={'suffix': '%', 'font': {'size': 40, 'color': '#FFD700'}},
                gauge={
                    'axis': {'range': [0, 100], 'tickwidth': 1},
                    'bar': {'color': '#FFD700', 'thickness': 0.2},
                    'steps': [
                        {'range': [0, 30], 'color': 'rgba(247,127,0,0.3)'},
                        {'range': [30, 60], 'color': 'rgba(255,215,0,0.3)'},
                        {'range': [60, 100], 'color': 'rgba(78,205,196,0.3)'},
                    ],
                }
            ), row=2, col=1)
            
            fig_gauge.update_layout(
                height=500,
                paper_bgcolor=COLORS["bg"],
                margin=dict(t=30, b=10),
            )
            st.plotly_chart(fig_gauge, use_container_width=True)
        
        # Distribuzione percentuale
        st.markdown("### 🥧 Ripartizione Energetica")
        col_p1, col_p2 = st.columns(2)
        
        with col_p1:
            labels_prod = ['Autoconsumo', 'Immessa in Rete']
            values_prod = [df_all['SelfConsumption_kWh'].sum(), df_all['GridFeedIn_kWh'].sum()]
            fig_prod_pie = go.Figure(go.Pie(
                labels=labels_prod, values=values_prod,
                marker_colors=[COLORS["self_consumption"], COLORS["grid_feed"]],
                hole=0.55, textinfo='percent+value',
                texttemplate='%{percent:.1%}<br>%{value:,.0f} kWh',
            ))
            fig_prod_pie.update_layout(
                title='Dove va la Produzione',
                height=350,
                paper_bgcolor=COLORS["bg"],
            )
            st.plotly_chart(fig_prod_pie, use_container_width=True)
        
        with col_p2:
            labels_cons = ['Autoconsumo', 'Prelievo da Rete']
            values_cons = [df_all['SelfConsumption_kWh'].sum(), df_all['GridDraw_kWh'].sum()]
            fig_cons_pie = go.Figure(go.Pie(
                labels=labels_cons, values=values_cons,
                marker_colors=[COLORS["self_consumption"], COLORS["grid_draw"]],
                hole=0.55, textinfo='percent+value',
                texttemplate='%{percent:.1%}<br>%{value:,.0f} kWh',
            ))
            fig_cons_pie.update_layout(
                title='Da dove viene il Consumo',
                height=350,
                paper_bgcolor=COLORS["bg"],
            )
            st.plotly_chart(fig_cons_pie, use_container_width=True)
    
    with tab4:
        st.plotly_chart(plot_calendar_heatmap(df_all), use_container_width=True)
        
        # Statistiche mensili veloci
        st.markdown("### 📊 Medie Giornaliere per Mese")
        daily_avg = df_all.groupby(['MonthName', 'Month']).agg(
            Prod_Media=('Production_kWh', 'mean'),
            Cons_Media=('Consumption_kWh', 'mean'),
            Auto_Media=('SelfConsumption_kWh', 'mean'),
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
            barmode='group', height=350,
            paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["bg"],
            xaxis=dict(showgrid=False),
            yaxis=dict(title='kWh/giorno', gridcolor='rgba(255,255,255,0.08)'),
            legend=dict(orientation='h', yanchor='top', y=1.12),
        )
        st.plotly_chart(fig_avg, use_container_width=True)
    
    with tab5:
        st.markdown("### 📋 Dati Grezzi")
        st.dataframe(
            df_all.sort_values('Date', ascending=False),
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
                'SelfConsumption_Rate': st.column_config.NumberColumn('Tasso Autocons. %', format='%.1f%%'),
            },
            column_order=['Date', 'Production_kWh', 'Consumption_kWh', 'SelfConsumption_kWh', 
                          'GridFeedIn_kWh', 'GridDraw_kWh', 'Autonomy_Ratio', 'SelfConsumption_Rate', 'Source'],
        )
        
        # Bottone export
        excel_data = to_excel(df_all)
        st.download_button(
            label='📥 Scarica Dati Elaborati (Excel)',
            data=excel_data,
            file_name='energy_dashboard_export.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
    
    # ═══ FOOTER ═══
    st.markdown("---")
    st.caption(f"📁 {len(dfs_dict)} file caricati • 📊 {len(df_all)} giorni di dati • ⚡ Energy Dashboard Pro v1.0")
