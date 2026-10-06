import io

import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

import polars as pl

from pipeline import CBCPipeline


CSV_PATH = "diagnosed_cbc_data_v4.csv"

CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"] {
        background: #F8FAFC;
        color: #0F172A;
        font-family: 'Inter', sans-serif;
    }

    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: 1400px;
    }

    h1, h2, h3, h4, p {
        color: #0F172A;
    }

    .stCaption,
    .stMarkdownContainer p,
    .stMarkdownContainer span,
    .stMarkdownContainer div {
        color: #64748B;
    }

    .stMetric {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-top: 3px solid #F472B6;
        border-radius: 12px;
        box-shadow: 0 4px 14px 0 rgba(244, 114, 182, 0.08);
        padding: 0.9rem 1rem;
    }

    .kpi-card, .status-box, .panel {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-top: 3px solid #F472B6;
        border-radius: 12px;
        box-shadow: 0 4px 14px 0 rgba(244, 114, 182, 0.08);
        padding: 1rem 1.1rem;
    }

    .kpi-card {
        min-height: 130px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }

    .kpi-label {
        color: #64748B;
        font-size: 0.8rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }

    .kpi-value {
        color: #0F172A;
        font-size: clamp(1.5rem, 2vw, 2.4rem);
        font-weight: 800;
        margin-top: 0.5rem;
        text-shadow: none;
    }

    .kpi-delta {
        color: #2563EB;
        font-size: 0.8rem;
        font-weight: 600;
    }

    .status-box {
        margin: 0 0 14px 0;
        padding: 1rem 1.1rem;
        display: block;
        border-left: 4px solid #D97706;
        background: #FFFBEB;
        color: #92400E;
    }

    .status-box:last-child {
        margin-bottom: 0;
    }

    .status-box.warning {
        border-left: 4px solid #7C3AED;
        background: #F5F3FF;
        color: #5B21B6;
    }

    .status-box.success {
        border-left: 4px solid #059669;
        background: #ECFDF5;
        color: #065F46;
    }

    .status-box.info {
        border-left: 4px solid #EA580C;
        background: #FFF7ED;
        color: #9A3412;
    }

    .status-label {
        color: inherit;
        font-size: 0.72rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin-bottom: 0.35rem;
        font-weight: 700;
    }

    .status-copy {
        color: inherit;
        font-size: 0.98rem;
        line-height: 1.5;
    }

    .panel-title {
        color: #0F172A;
        font-size: 1.1rem;
        font-weight: 700;
        margin-bottom: 0.5rem;
    }

    .section-header {
        margin-top: 1rem;
        margin-bottom: 0.75rem;
        padding-bottom: 0.35rem;
        border-bottom: 1px solid #E2E8F0;
    }

    .mini-pill {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.4rem 0.7rem;
        border-radius: 999px;
        background: #EFF6FF;
        border: 1px solid #BFDBFE;
        color: #1E3A8A;
        font-size: 0.76rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }

    .stAlert {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
    }

    .brand-title {
        font-size: 3.8rem;
        line-height: 1.1;
        font-weight: 900;
        letter-spacing: 0.04em;
        color: transparent;
        background: linear-gradient(135deg, #EC4899 0%, #F472B6 35%, #C084FC 70%, #818CF8 100%);
        background-size: 300% 300%;
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
        animation: gradientShift 6s ease infinite;
        text-shadow: none;
        margin: 0 0 0.1rem 0;
        padding: 0;
        display: block;
        position: static;
        transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), filter 0.3s ease;
    }

    .brand-title:hover {
        transform: scale(1.02);
        filter: drop-shadow(0 4px 12px rgba(244, 114, 182, 0.35));
    }

    @keyframes gradientShift {
        0% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
    }

    .brand-subtitle {
        font-size: 1.4rem;
        font-weight: 600;
        letter-spacing: 0.02em;
        color: #DB2777;
        text-shadow: none;
        margin: 0 0 1.5rem 0;
        padding: 0;
        display: block;
        position: static;
    }

    .top-spacer {
        margin-top: 0.5rem;
    }

    .chart-block {
        padding-top: 1.25rem;
        margin-top: 0.5rem;
    }

    div[data-testid="stMarkdownContainer"] > div {
        margin-bottom: 16px !important;
        display: block;
    }

    div[data-testid="stMarkdownContainer"] > div:last-child {
        margin-bottom: 0 !important;
    }

    div.stDownloadButton {
        margin-top: 24px !important;
        margin-bottom: 16px !important;
    }

    div.stDownloadButton > button {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 220px;
        width: auto;
        background: #FDF2F8;
        border: 1px solid #F472B6;
        color: #BE185D;
        border-radius: 12px;
        padding: 0.72rem 1.2rem;
        font-weight: 600;
        letter-spacing: 0.02em;
        transition: all 0.2s ease;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    }

    div.stDownloadButton > button:hover {
        background: #FCE7F3;
        color: #BE185D;
        border-color: #F472B6;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    }

    div.stDownloadButton > button > span {
        color: #BE185D;
    }
</style>
"""


TEMPLATE_CSV = "WBC,RBC,HGB,MCV,HCT,MCHC\n7.2,3.97,9.0,77.0,30.5,29.5\n6.0,4.80,13.5,88.0,41.0,33.0\n"


@st.cache_data(show_spinner=False)
def load_dashboard_data(name: str | None = None, data: bytes | None = None, exclude_flagged: bool = False):
    """Run the pipeline on an uploaded file (name + bytes) or on the bundled CSV."""
    if data is None:
        source = CSV_PATH
    else:
        if name.lower().endswith((".xlsx", ".xls")):
            # Round-trip through CSV so odd Excel dtypes can't break Polars
            csv_bytes = pd.read_excel(io.BytesIO(data)).to_csv(index=False).encode("utf-8")
        else:
            csv_bytes = data
        source = pl.read_csv(
            io.BytesIO(csv_bytes), infer_schema_length=10000, ignore_errors=True, encoding="utf8-lossy"
        )
    pipeline = CBCPipeline(source, exclude_flagged=exclude_flagged)
    df = pipeline.run()
    return df, pipeline.summarize(), pipeline.report


def format_iqd(value: float | int) -> str:
    return f"{float(value):,.0f} IQD"


def mentzer_index(rbc: float, mcv: float) -> float:
    if rbc is None or rbc == 0:
        return 0.0
    return float(mcv) / float(rbc)


def evaluate_case(hgb: float, rbc: float, mcv: float, wbc: float):
    index_value = mentzer_index(rbc, mcv)
    anemia = hgb < 12.0

    if anemia and index_value < 13:
        flag = "Suspected Thalassemia Trait"
        reflex = "Hb Electrophoresis"
        tube_alert = "EDTA tube retained for hemoglobinopathy workup; keep sample intact and protected from hemolysis."
        added_value = 25_000
    elif anemia and index_value >= 13:
        flag = "Suspected Iron Deficiency"
        reflex = "Serum Ferritin"
        tube_alert = "Serum tube retained for ferritin/iron studies; ensure sample separation is preserved."
        added_value = 15_000
    elif wbc > 11:
        flag = "Suspected Systemic Inflammation"
        reflex = "CRP"
        tube_alert = "Serum tube retained for inflammatory marker assessment; separate promptly and protect from delay."
        added_value = 10_000
    else:
        flag = "Normal reference"
        reflex = "None"
        tube_alert = "No reflex preservation required; sample can be released for standard processing."
        added_value = 0

    return {
        "mentzer_index": index_value,
        "clinical_flag": flag,
        "reflex_order": reflex,
        "tube_alert": tube_alert,
        "added_value": added_value,
    }


NEXT_STEPS = {
    "Hb Electrophoresis": "Run Hb Electrophoresis to confirm or exclude a hemoglobinopathy. Keep the EDTA tube intact and protected from hemolysis.",
    "Serum Ferritin": "Run Serum Ferritin (with iron studies) to confirm iron deficiency. Keep the serum tube separated and labeled.",
    "CRP": "Run CRP to assess systemic inflammation. Separate the serum promptly.",
    "None": "No reflex order required. Standard CBC processing remains sufficient.",
}


def render_kpi_card(title: str, value: str, delta: str = ""):
    delta_html = f'<div class="kpi-delta">{delta}</div>' if delta else ""
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">{title}</div>
            <div class="kpi-value">{value}</div>
            {delta_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def build_clinical_decision_plot(df):
    plot_df = df.select(["mcv", "rbc", "clinical_flag"]).to_pandas()
    plot_df = plot_df.dropna(subset=["mcv", "rbc", "clinical_flag"]).copy()

    if plot_df.empty:
        return go.Figure()

    x_min, x_max = 40, 130
    y_min, y_max = 1.5, 8.5
    threshold_x = [x_min, x_max]
    threshold_y = [x_min / 13, x_max / 13]

    fig = px.scatter(
        plot_df,
        x="mcv",
        y="rbc",
        color="clinical_flag",
        color_discrete_map={
            "Suspected Thalassemia Trait": "#FF7AC6",
            "Suspected Iron Deficiency": "#8B5CF6",
            "Suspected Systemic Inflammation": "#7DD3FC",
            "Normal reference": "#94A3B8",
        },
        labels={"mcv": "MCV (fL)", "rbc": "RBC (x10^12/L)", "clinical_flag": "Clinical Flag"},
        category_orders={"clinical_flag": [
            "Suspected Thalassemia Trait",
            "Suspected Iron Deficiency",
            "Suspected Systemic Inflammation",
            "Normal reference",
        ]},
    )

    fig.add_trace(
        go.Scatter(
            x=threshold_x,
            y=threshold_y,
            mode="lines",
            name="Mentzer = 13",
            line=dict(color="#111827", width=2, dash="dash"),
            hoverinfo="skip",
        )
    )

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#FFFFFF",
        legend=dict(
            orientation="h",
            y=-0.2,
            x=0.5,
            xanchor="center",
            bgcolor="#FFFFFF",
            bordercolor="#E2E8F0",
            borderwidth=1,
            font=dict(color="#0F172A", size=11),
        ),
        margin=dict(t=20, b=50, l=60, r=40),
        height=450,
        font=dict(color="#0F172A"),
        title=None,
        xaxis=dict(gridcolor="#F1F5F9", zerolinecolor="#E2E8F0"),
        yaxis=dict(gridcolor="#F1F5F9", zerolinecolor="#E2E8F0"),
        annotations=[
            dict(
                text="Below the line = thalassemia pattern<br>Above the line = iron deficiency pattern",
                xref="paper",
                yref="paper",
                x=1.0,
                y=0.0,
                xanchor="right",
                yanchor="bottom",
                showarrow=False,
                font=dict(size=11, color="#0F172A"),
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="#E2E8F0",
                borderwidth=1,
            )
        ],
    )
    fig.update_xaxes(
        range=[x_min, x_max],
        title=dict(text="MCV (fL)", font=dict(color="#111827", size=12)),
        tickfont=dict(color="#111827", size=11),
        gridcolor="#E5E7EB",
        zeroline=False,
        showline=False,
        linecolor="#D1D5DB",
    )
    fig.update_yaxes(
        range=[y_min, y_max],
        title=dict(text="RBC (x10^12/L)", font=dict(color="#111827", size=12)),
        tickfont=dict(color="#111827", size=11),
        gridcolor="#E5E7EB",
        zeroline=False,
        showline=False,
        linecolor="#D1D5DB",
    )
    return fig


def build_reflex_economics_plot(df):
    from plotly.subplots import make_subplots

    category_order = ["CRP", "Serum Ferritin", "Hb Electrophoresis"]
    revenue_map = {
        "Hb Electrophoresis": int(df["rev_hb_electrophoresis"].sum()) if "rev_hb_electrophoresis" in df.columns else 0,
        "Serum Ferritin": int(df["rev_serum_ferritin"].sum()) if "rev_serum_ferritin" in df.columns else 0,
        "CRP": int(df["rev_crp"].sum()) if "rev_crp" in df.columns else 0,
    }
    counts = {test: int((df["reflex_order"] == test).sum()) for test in category_order}
    revenue_values = [revenue_map[test] for test in category_order]
    count_values = [counts[test] for test in category_order]

    fig = make_subplots(
        rows=1,
        cols=2,
        shared_yaxes=True,
        horizontal_spacing=0.12,
        subplot_titles=("Cases Triggered", "Revenue (IQD)"),
    )

    fig.add_trace(
        go.Bar(
            x=count_values,
            y=category_order,
            orientation="h",
            marker=dict(color="#7B2CBF", line=dict(color="#7B2CBF", width=1), opacity=0.9),
            text=count_values,
            texttemplate="%{x}",
            textposition="outside",
            hovertemplate="%{y}<br>Triggered: %{x}<extra></extra>",
            showlegend=False,
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Bar(
            x=revenue_values,
            y=category_order,
            orientation="h",
            marker=dict(color="#E0218A", line=dict(color="#E0218A", width=1), opacity=0.8),
            text=[f"{value:,.0f} IQD" for value in revenue_values],
            texttemplate="%{x:,.0f} IQD",
            textposition="outside",
            hovertemplate="%{y}<br>Revenue: %{x:,.0f} IQD<extra></extra>",
            showlegend=False,
        ),
        row=1,
        col=2,
    )

    fig.update_traces(cliponaxis=False)
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#FFFFFF",
        height=450,
        margin=dict(t=30, b=40, l=120, r=110),
        font=dict(color="#0F172A", family="Inter"),
        showlegend=False,
        xaxis=dict(gridcolor="#F1F5F9", zerolinecolor="#E2E8F0"),
        yaxis=dict(gridcolor="#F1F5F9", zerolinecolor="#E2E8F0"),
    )

    fig.update_xaxes(
        title_text="Cases Triggered",
        title_font=dict(color="#111827", size=12, family="Inter"),
        tickfont=dict(color="#111827", size=11, family="Inter"),
        gridcolor="#E5E7EB",
        zeroline=False,
        showline=False,
        linecolor="#D1D5DB",
        row=1,
        col=1,
    )
    fig.update_xaxes(
        title_text="Revenue (IQD)",
        title_font=dict(color="#111827", size=12, family="Inter"),
        tickfont=dict(color="#111827", size=11, family="Inter"),
        gridcolor="#E5E7EB",
        zeroline=False,
        showline=False,
        linecolor="#D1D5DB",
        row=1,
        col=2,
    )
    fig.update_yaxes(
        tickmode="array",
        tickvals=category_order,
        ticktext=category_order,
        tickfont=dict(color="#111827", size=11, family="Inter"),
        title_text="",
        linecolor="#D1D5DB",
        row=1,
        col=1,
    )
    fig.update_yaxes(
        tickmode="array",
        tickvals=category_order,
        ticktext=category_order,
        tickfont=dict(color="#111827", size=11, family="Inter"),
        title_text="",
        linecolor="#D1D5DB",
        matches="y",
        row=1,
        col=2,
    )
    return fig


def render_status_box(title: str, message: str, tone: str = "warning", last: bool = False):
    margin_style = "margin-bottom: 0 !important; display: block;" if last else "margin-bottom: 14px !important; display: block;"
    st.markdown(
        f"""
        <div class="status-box {tone}" style="{margin_style}">
            <div class="status-label">{title}</div>
            <div class="status-copy">{message}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def build_patient_view(df):
    if df is None or df.height == 0:
        return pl.DataFrame({})

    cols = [
        "hgb",
        "rbc",
        "mcv",
        "wbc",
        "mentzer_index",
        "clinical_flag",
        "reflex_order",
        "base_price",
        "add_on_revenue",
        "total_ticket_value",
    ]
    if "diagnosis" in df.columns:
        cols.insert(0, "diagnosis")
    for extra in ("source_row", "data_quality_flag"):
        if extra in df.columns:
            cols.append(extra)

    patient_df = df.select(cols).with_row_index(name="record_id").with_columns(
        (pl.col("record_id") + 1).alias("record_id")
    )
    return patient_df


st.set_page_config(page_title="Bioreflex CBC Command Center", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

st.markdown('<div class="brand-title">BioRefleX</div>', unsafe_allow_html=True)
st.markdown('<div class="brand-subtitle">CBC Command Center</div>', unsafe_allow_html=True)
st.caption("Integrated hematology triage, reflex-driven economics, and lab-side decision support.")

st.markdown('<div class="top-spacer"></div>', unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### Data")
    uploaded = st.file_uploader(
        "Upload CBC file",
        type=["csv", "xlsx"],
        help="Needs columns WBC, RBC, HGB, MCV. HCT and MCHC are optional.",
    )
    exclude_flagged = st.checkbox(
        "Exclude rows with implausible values",
        value=False,
        help="Rows outside normal physiologic limits are flagged either way; tick this to leave them out of all totals and charts.",
    )
    st.download_button(
        "Download file template",
        data=TEMPLATE_CSV,
        file_name="bioreflex_template.csv",
        mime="text/csv",
        use_container_width=True,
    )
    if uploaded is None:
        st.caption(f"Showing the bundled sample dataset (`{CSV_PATH}`). Upload a file to analyze your own data.")

try:
    df, summary, quality = load_dashboard_data(
        uploaded.name if uploaded else None,
        uploaded.getvalue() if uploaded else None,
        exclude_flagged,
    )
except ValueError as exc:  # missing columns etc. - tell the user what to fix
    st.error(f"Could not analyze this file. {exc}")
    st.stop()
except Exception as exc:  # pragma: no cover - UI guard
    st.error(f"The file could not be read ({type(exc).__name__}: {exc}). Please check it is a valid CSV or Excel file.")
    st.stop()

if df.height == 0:
    st.warning(
        f"No usable rows. {quality['rows_loaded']:,} rows were loaded but all were rejected "
        "(missing HGB/RBC/MCV, non-positive RBC, or excluded as implausible)."
    )
    st.stop()

baseline_revenue = float(df["base_price"].sum()) if "base_price" in df.columns else summary["processed_rows"] * CBCPipeline.BASE_CBC_PRICE
optimized_revenue = float(df["total_ticket_value"].sum()) if "total_ticket_value" in df.columns else summary["total_expected_revenue"]
reflex_candidates = int((df["reflex_order"] != "None").sum()) if "reflex_order" in df.columns else 0
uplift_pct = ((optimized_revenue - baseline_revenue) / baseline_revenue * 100) if baseline_revenue else 0.0

kpis = [
    ("Total Samples", f"{summary['processed_rows']:,}", "Across all CBC records"),
    ("Reflex Candidates Triggered", f"{reflex_candidates:,}", "Lab follow-up tests activated"),
    ("Baseline Lab Revenue (IQD)", format_iqd(baseline_revenue), "CBC-only revenue"),
    ("Optimized Revenue (IQD)", format_iqd(optimized_revenue), "With reflex add-ons"),
    ("Revenue Uplift %", f"{uplift_pct:.1f}%", "Value added through triage"),
]

cols = st.columns(5)
for col, (title, value, delta) in zip(cols, kpis):
    with col:
        render_kpi_card(title, value, delta)

export_col, spacer_col = st.columns([1, 4])
with export_col:
    export_df = build_patient_view(df)
    if export_df.height > 0:
        csv_bytes = export_df.to_pandas().to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Export processed CSV",
            data=csv_bytes,
            file_name="bioreflex_cbc_export.csv",
            mime="text/csv",
            use_container_width=True,
        )

st.markdown("<div class='section-header'></div>", unsafe_allow_html=True)
st.markdown("<div class='panel-title'>Data Quality</div>", unsafe_allow_html=True)

rejected_total = quality["rejected_missing"] + quality["rejected_rbc_nonpositive"]
dq_cols = st.columns(4)
dq_cards = [
    ("Rows loaded", f"{quality['rows_loaded']:,}", "From the file"),
    ("Rows analyzed", f"{quality['rows_used']:,}", "Used in every total and chart"),
    ("Rows rejected", f"{rejected_total:,}", "Missing HGB/RBC/MCV or RBC <= 0"),
    ("Rows flagged", f"{quality['flagged_rows']:,}", "Implausible values (excluded)" if quality["excluded_flagged"] else "Implausible values (still included)"),
]
for col, (title, value, delta) in zip(dq_cols, dq_cards):
    with col:
        render_kpi_card(title, value, delta)

st.markdown("<div style='margin-top: 14px;'></div>", unsafe_allow_html=True)
if quality["flagged_rows"] and not quality["excluded_flagged"]:
    breakdown = "<br>".join(f"&bull; {label}: {n:,} row(s)" for label, n in quality["flag_breakdown"].items())
    render_status_box(
        "Check your data",
        f"{quality['flagged_rows']:,} row(s) contain values outside normal physiologic limits and are still counted in the totals below. "
        f"These distort averages and may trigger wrong reflex orders. Tick &quot;Exclude rows with implausible values&quot; in the sidebar to remove them.<br>{breakdown}",
        "warning",
    )
elif quality["flagged_rows"]:
    render_status_box(
        "Rows excluded",
        f"{quality['excluded_flagged']:,} row(s) with implausible values were left out of all totals and charts.",
        "info",
    )
else:
    render_status_box("Data check passed", "No implausible values were found in the analyzed rows.", "success")
if quality["unparseable_values"]:
    render_status_box(
        "Unreadable values",
        f"{quality['unparseable_values']:,} cell(s) were not numbers (for example text such as N/A) and were treated as empty.",
        "info",
    )
if quality["wbc_missing"]:
    render_status_box(
        "Missing WBC",
        f"{quality['wbc_missing']:,} analyzed row(s) have no WBC, so they cannot trigger the inflammation/CRP rule.",
        "info",
    )
if quality["flagged_rows"] and not quality["excluded_flagged"]:
    with st.expander(f"Show the {quality['flagged_rows']:,} flagged row(s)"):
        flagged_view = (
            df.filter(pl.col("data_quality_flag").is_not_null())
            .select([c for c in ["source_row", "hgb", "rbc", "mcv", "wbc", "hct", "mchc", "data_quality_flag"] if c in df.columns])
            .rename({"source_row": "file_row"})
        )
        st.caption("file_row matches the row number in your spreadsheet (header is row 1).")
        st.dataframe(flagged_view.to_pandas(), use_container_width=True, hide_index=True)

st.markdown("<div class='section-header'></div>", unsafe_allow_html=True)

st.markdown('<div class="chart-block"></div>', unsafe_allow_html=True)
chart_col1, chart_col2 = st.columns(2)
with chart_col1:
    st.markdown("### MCV vs RBC — Mentzer Decision Line")
    st.plotly_chart(build_clinical_decision_plot(df), use_container_width=True)
with chart_col2:
    st.markdown("### Diagnostic Reflex & Economics Breakdown")
    st.plotly_chart(build_reflex_economics_plot(df), use_container_width=True, config={"displayModeBar": False})

st.markdown("<div class='section-header'></div>", unsafe_allow_html=True)

left_col, right_col = st.columns([1.6, 1])

with left_col:
    st.markdown("<div class='panel-title'>Diagnostic Distribution</div>", unsafe_allow_html=True)
    dist_map = {
        "Suspected Thalassemia Trait": summary["thal_count"],
        "Suspected Iron Deficiency": summary["iron_count"],
        "Suspected Systemic Inflammation": summary["inflam_count"],
    }
    dist_df = pl.DataFrame({"Condition": list(dist_map.keys()), "Count": list(dist_map.values())})
    fig = go.Figure(
        data=[go.Bar(
            x=dist_df["Condition"].to_list(),
            y=dist_df["Count"].to_list(),
            marker=dict(
                color=["#C77DFF", "#5A189A", "#7B2CBF"],
                line=dict(color="#7B2CBF", width=1),
            ),
            text=[str(v) for v in dist_df["Count"].to_list()],
            textposition="outside",
        )]
    )
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#FFFFFF",
        margin=dict(t=30, b=40, l=40, r=20),
        font=dict(color="#0F172A"),
        xaxis=dict(
            title=dict(text="Diagnostic Category", font=dict(color="#0F172A", size=12)),
            tickfont=dict(color="#0F172A", size=11),
            linecolor="#E2E8F0",
            gridcolor="#F1F5F9",
            zerolinecolor="#E2E8F0",
        ),
        yaxis=dict(
            title=dict(text="Count", font=dict(color="#0F172A", size=12)),
            tickfont=dict(color="#0F172A", size=11),
            linecolor="#E2E8F0",
            gridcolor="#F1F5F9",
            zerolinecolor="#E2E8F0",
            zeroline=False,
        ),
        bargap=0.4,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

with right_col:
    st.markdown("<div class='panel-title'>Clinical Summary</div>", unsafe_allow_html=True)
    st.markdown(
        """
        <div class="panel">
            <div class="mini-pill">Clinical mix</div><br>
            <strong>Thalassemia trait:</strong> %(thal)s cases<br>
            <strong>Iron deficiency:</strong> %(iron)s cases<br>
            <strong>Systemic inflammation:</strong> %(inflammation)s cases<br>
            <strong>Mean Mentzer Index:</strong> %(mentzer).2f
        </div>
        """ % {
            "thal": summary["thal_count"],
            "iron": summary["iron_count"],
            "inflammation": summary["inflam_count"],
            "mentzer": summary["mean_mentzer"] or 0.0,
        },
        unsafe_allow_html=True,
    )

st.markdown("<div class='section-header'></div>", unsafe_allow_html=True)

st.markdown("<div class='panel-title'>Benchtop Lab Console</div>", unsafe_allow_html=True)
bench_col1, bench_col2 = st.columns([1.1, 1.3])

with bench_col1:
    with st.container():
        hgb = st.number_input("HGB (g/dL)", min_value=0.0, max_value=25.0, value=9.2, step=0.1)
        rbc = st.number_input("RBC (x10^12/L)", min_value=0.1, max_value=8.0, value=3.8, step=0.1)
        mcv = st.number_input("MCV (fL)", min_value=40.0, max_value=120.0, value=78.4, step=0.1)
        wbc = st.number_input("WBC (10^9/L)", min_value=1.0, max_value=50.0, value=8.4, step=0.1)

with bench_col2:
    st.markdown(
        "<div style='display: flex; flex-direction: column; gap: 14px;'>",
        unsafe_allow_html=True,
    )
    case_result = evaluate_case(hgb, rbc, mcv, wbc)
    mentzer_value = case_result["mentzer_index"]
    st.markdown(
        f"""
        <div class="panel" style="margin-bottom: 0; display: block; border-left: 4px solid #2563EB; background: #EFF6FF; color: #1E3A8A;">
            <div class="mini-pill" style="background: #DBEAFE; border-color: #93C5FD; color: #1E3A8A;">Mentzer index</div>
            <div class="kpi-value" style="font-size:1.7rem; margin-top: 0.6rem; color: #1E3A8A;">{mentzer_value:.2f}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tone = "warning" if case_result["clinical_flag"] != "Normal reference" else "success"
    render_status_box("Suspected condition", case_result["clinical_flag"], tone)
    render_status_box("Automated reflex order", case_result["reflex_order"], "warning")
    render_status_box("Sample tube preservation", case_result["tube_alert"], "info")
    render_status_box("Unit economics added value", f"+ {case_result['added_value']:,} IQD through reflex triage.", "success")

    reflex = case_result["reflex_order"]
    render_status_box(
        "Recommended next step",
        NEXT_STEPS.get(reflex, NEXT_STEPS["None"]),
        "warning" if reflex != "None" else "success",
        last=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

patient_df = build_patient_view(df)
patient_table = patient_df.to_pandas()

st.markdown("<div class='section-header'></div>", unsafe_allow_html=True)
st.markdown("<div class='panel-title'>Patient Record Drill-Down</div>", unsafe_allow_html=True)

record_filter = st.selectbox(
    "Filter by clinical status",
    ["All records", *sorted(patient_df["clinical_flag"].unique().to_list())],
)

if record_filter == "All records":
    filtered_patient_table = patient_table
else:
    filtered_patient_table = patient_table[patient_table["clinical_flag"] == record_filter]

patient_selector = st.selectbox(
    "Select a patient record to inspect",
    filtered_patient_table["record_id"].astype(int).tolist(),
)

st.markdown("<div style='margin-bottom: 18px;'></div>", unsafe_allow_html=True)

selected_record = filtered_patient_table[filtered_patient_table["record_id"] == patient_selector].iloc[0]

record_col1, record_col2 = st.columns([1.2, 1.3])
with record_col1:
    st.markdown(
        """
        <div class="panel">
            <div class="mini-pill">Record summary</div><br>
            <strong>Record ID:</strong> {record_id}<br>
            <strong>Clinical flag:</strong> {clinical_flag}<br>
            <strong>Reflex order:</strong> {reflex_order}<br>
            <strong>Tube handling:</strong> {tube_handling}<br>
            <strong>Added value:</strong> {added_value} IQD
        </div>
        """.format(
            record_id=int(selected_record["record_id"]),
            clinical_flag=selected_record["clinical_flag"],
            reflex_order=selected_record["reflex_order"],
            tube_handling="EDTA tube retained" if selected_record["reflex_order"] == "Hb Electrophoresis" else "Serum tube retained" if selected_record["reflex_order"] == "Serum Ferritin" or selected_record["reflex_order"] == "CRP" else "Standard release",
            added_value=int(selected_record["add_on_revenue"]),
        ),
        unsafe_allow_html=True,
    )

with record_col2:
    st.markdown(
        """
        <div class="panel">
            <div class="mini-pill">CBC details</div><br>
            <strong>HGB:</strong> {hgb} g/dL<br>
            <strong>RBC:</strong> {rbc} x10^12/L<br>
            <strong>MCV:</strong> {mcv} fL<br>
            <strong>WBC:</strong> {wbc} x10^9/L<br>
            <strong>Mentzer Index:</strong> {mentzer:.2f}
        </div>
        """.format(
            hgb=selected_record["hgb"],
            rbc=selected_record["rbc"],
            mcv=selected_record["mcv"],
            wbc=selected_record["wbc"],
            mentzer=float(selected_record["mentzer_index"]),
        ),
        unsafe_allow_html=True,
    )

st.markdown("<div style='margin-top: 24px;'></div>", unsafe_allow_html=True)
st.dataframe(filtered_patient_table, use_container_width=True)

with st.expander("Pipeline output snapshot"):
    st.dataframe(patient_table.head(10), use_container_width=True)

st.caption("Dashboard is powered by the CBC pipeline in pipeline.py and reflects the actual clinical rules and revenue logic defined there.")