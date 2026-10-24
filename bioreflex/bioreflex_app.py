"""
BioRefleX Dashboard — واجهة لوحة التحكم
Run:  streamlit run bioreflex_app.py
Requires: bioreflex_pipeline.py in the same folder.
"""

from __future__ import annotations

import io
from pathlib import Path

import altair as alt
import polars as pl
import streamlit as st

from bioreflex_pipeline import (
    Config,
    apply_pricing,
    apply_reflex_rules,
    build_kpis,
    engineer_features,
    load_cbc,
    validate,
)

DEFAULT_CSV = Path("diagnosed_cbc_data_v4.csv")

PALETTE = {
    "Suspected Thalassemia Trait": "#8e44ad",
    "Suspected Iron Deficiency": "#e67e22",
    "Anemia (Non-Microcytic) - Clinician Review": "#7f8c8d",
    "Suspected Systemic Inflammation": "#e74c3c",
    "Within Reference Range": "#27ae60",
}
COLOR_SCALE = alt.Scale(domain=list(PALETTE), range=list(PALETTE.values()))

CLEAN_COLS = [
    "transaction_id", "hgb", "mcv", "rbc", "mentzer_index",
    "clinical_flag", "reflex_recommendation", "flag_rationale",
    "total_potential_ticket_iqd", "zaincash_gateway_action",
]

# ------------------------------------------------------------------------------
# Page setup / إعداد الصفحة
# ------------------------------------------------------------------------------
st.set_page_config(page_title="BioRefleX", page_icon="🩸", layout="wide")

st.markdown(
    """
    <style>
    [data-testid="stMetric"] {
        background: rgba(128,128,128,0.08);
        border: 1px solid rgba(128,128,128,0.25);
        border-radius: 12px;
        padding: 14px 18px;
    }
    .block-container { padding-top: 2rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🩸 BioRefleX")
st.caption(
    "Clinical Decision Support · Reflex Testing Engine  |  "
    "منصة دعم القرار السريري والفحوصات الانعكاسية"
)

# ------------------------------------------------------------------------------
# Sidebar: data + parameters / الشريط الجانبي
# ------------------------------------------------------------------------------
with st.sidebar:
    st.header("📂 Data | البيانات")
    uploaded = st.file_uploader("Upload CBC CSV | ارفع ملف CSV", type=["csv"])

    st.header("⚙️ Clinical Rules | القواعد")
    mentzer = st.slider("Mentzer cutoff", 8.0, 20.0, 13.0, 0.5,
                        help="< cutoff → thalassemia trait, ≥ cutoff → iron deficiency")
    microcytic = st.slider("Microcytic MCV cutoff (fL)", 70.0, 90.0, 80.0, 1.0)
    wbc_high = st.slider("High WBC cutoff (10³/µL)", 8.0, 20.0, 11.0, 0.5)
    with st.expander("Hemoglobin thresholds (g/dL)"):
        hgb_f = st.number_input("Female", value=12.0, step=0.1)
        hgb_m = st.number_input("Male", value=13.0, step=0.1)
        hgb_d = st.number_input("Default (no sex column)", value=12.0, step=0.1)

    st.header("💰 Pricing | التسعير (IQD)")
    p_base = st.number_input("CBC base", value=10_000, step=1_000)
    p_fer = st.number_input("Serum Ferritin", value=15_000, step=1_000)
    p_hb = st.number_input("Hb Electrophoresis", value=25_000, step=1_000)
    p_crp = st.number_input("CRP", value=10_000, step=1_000)

params = {
    "mentzer": mentzer, "microcytic": microcytic, "wbc": wbc_high,
    "hgb_f": hgb_f, "hgb_m": hgb_m, "hgb_d": hgb_d,
    "p_base": int(p_base), "p_fer": int(p_fer), "p_hb": int(p_hb), "p_crp": int(p_crp),
}

# ------------------------------------------------------------------------------
# Pipeline (cached) / تشغيل المحرك
# ------------------------------------------------------------------------------
@st.cache_data(show_spinner="Running BioRefleX engine…")
def run_pipeline(file_bytes: bytes, p: dict):
    cfg = Config(
        hgb_threshold_female=p["hgb_f"],
        hgb_threshold_male=p["hgb_m"],
        hgb_default_threshold=p["hgb_d"],
        microcytic_mcv_cutoff=p["microcytic"],
        mentzer_cutoff=p["mentzer"],
        wbc_high_cutoff=p["wbc"],
        base_cbc_price_iqd=p["p_base"],
        reflex_prices_iqd={
            "Serum Ferritin Test": p["p_fer"],
            "Hemoglobin Electrophoresis": p["p_hb"],
            "C-Reactive Protein (CRP)": p["p_crp"],
        },
    )
    raw = load_cbc(io.BytesIO(file_bytes), cfg)   # type: ignore[arg-type]
    total_rows = raw.height
    valid, rejected = validate(raw, cfg)
    df = engineer_features(valid, cfg)
    df = apply_reflex_rules(df, cfg)
    df = apply_pricing(df, cfg)
    headline, _ = build_kpis(df)

    by_flag = (
        df.group_by("clinical_flag")
        .agg(
            pl.len().alias("n"),
            pl.col("hgb").mean().round(2).alias("avg_hgb"),
            pl.col("mentzer_index").mean().round(2).alias("avg_mentzer"),
        )
        .with_columns((pl.col("n") / df.height * 100).round(1).alias("share_pct"))
        .sort("n", descending=True)
    )
    by_test = (
        df.group_by("reflex_recommendation")
        .agg(pl.len().alias("n"), pl.col("reflex_price_iqd").sum().alias("reflex_rev_iqd"))
        .sort("n", descending=True)
    )
    return df, rejected, headline, by_flag, by_test, total_rows


if uploaded is not None:
    file_bytes = uploaded.getvalue()
elif DEFAULT_CSV.exists():
    file_bytes = DEFAULT_CSV.read_bytes()
    st.sidebar.caption(f"Using default file: {DEFAULT_CSV.name}")
else:
    st.info("⬅️ Upload a CBC CSV file to start | ارفع ملف CSV من الشريط الجانبي للبدء.")
    st.stop()

try:
    df, rejected, H, by_flag, by_test, total_rows = run_pipeline(file_bytes, params)
except ValueError as e:
    st.error(f"Could not process the file: {e}")
    st.stop()

# ------------------------------------------------------------------------------
# Tabs / التبويبات
# ------------------------------------------------------------------------------
tab_overview, tab_explorer, tab_finance, tab_records, tab_quality = st.tabs([
    "📊 Overview | نظرة عامة",
    "🔬 Mentzer Explorer | المستكشف",
    "💰 Financial | المالي",
    "🧾 Patient Records | السجلات",
    "🛡️ Data Quality | جودة البيانات",
])

# ---- Overview -----------------------------------------------------------------
with tab_overview:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Valid samples", f"{H['total_tests']:,}")
    c2.metric("Flagged for reflex", f"{H['flagged_cases']:,}")
    c3.metric("Screening yield", f"{H['screening_yield_pct']}%")
    c4.metric("Basket growth", f"+{H['basket_uplift_pct']}%")

    st.subheader("Suspected findings | التوزيع التشخيصي")
    left, right = st.columns([3, 2])
    with left:
        chart = (
            alt.Chart(by_flag.to_pandas())
            .mark_bar(cornerRadiusEnd=4)
            .encode(
                y=alt.Y("clinical_flag:N", sort="-x", title=None,
                        axis=alt.Axis(labelLimit=320)),
                x=alt.X("n:Q", title="Samples"),
                color=alt.Color("clinical_flag:N", scale=COLOR_SCALE, legend=None),
                tooltip=["clinical_flag", "n", "share_pct", "avg_hgb", "avg_mentzer"],
            )
            .properties(height=260)
        )
        st.altair_chart(chart, use_container_width=True)
    with right:
        st.dataframe(
            by_flag.rename({
                "clinical_flag": "Flag", "n": "Count", "share_pct": "Share %",
                "avg_hgb": "Avg Hb", "avg_mentzer": "Avg Mentzer",
            }).to_pandas(),
            hide_index=True, use_container_width=True,
        )

    st.subheader("Recommended reflex tests | الفحوصات الموصى بها")
    st.dataframe(
        by_test.rename({
            "reflex_recommendation": "Recommended test(s)", "n": "Count",
            "reflex_rev_iqd": "Reflex revenue (IQD)",
        }).to_pandas(),
        hide_index=True, use_container_width=True,
        column_config={"Reflex revenue (IQD)": st.column_config.NumberColumn(format="%d")},
    )

# ---- Mentzer explorer ---------------------------------------------------------
with tab_explorer:
    st.subheader("MCV vs RBC — Mentzer decision line")
    st.caption(
        "Points below the dashed line have Mentzer index under the cutoff "
        "(thalassemia-trait pattern); above it favour iron deficiency."
    )
    pts = df.select("mcv", "rbc", "hgb", "mentzer_index", "clinical_flag")
    if pts.height > 5000:
        pts = pts.sample(5000, seed=1)
        st.caption("Showing a random sample of 5,000 points.")

    scatter = (
        alt.Chart(pts.to_pandas())
        .mark_circle(size=45, opacity=0.65)
        .encode(
            x=alt.X("mcv:Q", title="MCV (fL)", scale=alt.Scale(zero=False)),
            y=alt.Y("rbc:Q", title="RBC (10⁶/µL)", scale=alt.Scale(zero=False)),
            color=alt.Color("clinical_flag:N", scale=COLOR_SCALE, title="Flag"),
            tooltip=["mcv", "rbc", "hgb", "mentzer_index", "clinical_flag"],
        )
    )
    mcv_lo, mcv_hi = float(df["mcv"].min()), float(df["mcv"].max())
    line_df = pl.DataFrame({
        "mcv": [mcv_lo, mcv_hi],
        "rbc": [mcv_lo / mentzer, mcv_hi / mentzer],
    }).to_pandas()
    rule = (
        alt.Chart(line_df)
        .mark_line(strokeDash=[6, 4], color="gray")
        .encode(x="mcv:Q", y="rbc:Q")
    )
    st.altair_chart((scatter + rule).interactive().properties(height=460),
                    use_container_width=True)

# ---- Financial ----------------------------------------------------------------
with tab_finance:
    st.subheader("Unit economics | الأثر المالي (IQD)")
    uptake = st.slider(
        "Expected reflex-test uptake | نسبة الالتزام المتوقعة بالفحص التكميلي (%)",
        0, 100, 100, 5,
        help="100% = every flagged patient completes the test (upper bound).",
    )
    base = H["baseline_revenue_iqd"]
    reflex_full = H["optimized_revenue_iqd"] - base
    reflex_adj = reflex_full * uptake / 100
    total_adj = base + reflex_adj

    f1, f2, f3, f4 = st.columns(4)
    f1.metric("Baseline (CBC only)", f"{base:,}")
    f2.metric("Reflex revenue", f"{reflex_adj:,.0f}")
    f3.metric("Total potential", f"{total_adj:,.0f}")
    f4.metric("Basket growth", f"+{reflex_adj / base * 100:.2f}%")

    per_test = by_test.filter(pl.col("reflex_rev_iqd") > 0).with_columns(
        (pl.col("reflex_rev_iqd") * uptake / 100).alias("adj_rev")
    )
    if per_test.height:
        rev_chart = (
            alt.Chart(per_test.to_pandas())
            .mark_bar(cornerRadiusEnd=4, color="#2980b9")
            .encode(
                y=alt.Y("reflex_recommendation:N", sort="-x", title=None,
                        axis=alt.Axis(labelLimit=380)),
                x=alt.X("adj_rev:Q", title="Reflex revenue (IQD)"),
                tooltip=["reflex_recommendation", "n", "adj_rev"],
            )
            .properties(height=200)
        )
        st.altair_chart(rev_chart, use_container_width=True)
    st.caption("Figures are illustrative estimates based on the pricing set in the sidebar.")

# ---- Patient records ----------------------------------------------------------
with tab_records:
    st.subheader("Records | السجلات")
    f_left, f_mid, f_right = st.columns([3, 2, 2])
    sel_flags = f_left.multiselect("Filter by flag", list(PALETTE), default=[])
    only_flagged = f_mid.checkbox("Only reflex-flagged", value=False)
    search = f_right.text_input("Search transaction ID")

    view = df
    if sel_flags:
        view = view.filter(pl.col("clinical_flag").is_in(sel_flags))
    if only_flagged:
        view = view.filter(pl.col("reflex_recommendation") != "None")
    if search.strip():
        view = view.filter(pl.col("transaction_id").str.contains(search.strip(), literal=True))

    st.caption(f"{view.height:,} record(s)")
    st.dataframe(
        view.select(CLEAN_COLS).head(2000).to_pandas(),
        hide_index=True, use_container_width=True, height=380,
        column_config={
            "total_potential_ticket_iqd": st.column_config.NumberColumn("Ticket (IQD)", format="%d"),
        },
    )

    st.download_button(
        "⬇️ Download filtered results (CSV)",
        data=view.select(CLEAN_COLS).write_csv().encode("utf-8-sig"),
        file_name="bioreflex_results.csv", mime="text/csv",
    )

    st.divider()
    st.subheader("Explain a case | تفسير حالة")
    ids = view["transaction_id"].head(500).to_list()
    if ids:
        pick = st.selectbox("Transaction ID", ids)
        r = view.filter(pl.col("transaction_id") == pick).row(0, named=True)
        e1, e2, e3, e4 = st.columns(4)
        e1.metric("Hb (g/dL)", r["hgb"])
        e2.metric("MCV (fL)", r["mcv"])
        e3.metric("RBC", r["rbc"])
        e4.metric("Mentzer", r["mentzer_index"])
        st.markdown(f"**Flag:** {r['clinical_flag']}")
        st.markdown(f"**Recommended test:** {r['reflex_recommendation']}")
        st.markdown(f"**Why:** {r['flag_rationale']}")
    else:
        st.info("No records match the filters.")

# ---- Data quality -------------------------------------------------------------
with tab_quality:
    st.subheader("Data quality | جودة البيانات")
    q1, q2, q3 = st.columns(3)
    q1.metric("Rows in file", f"{total_rows:,}")
    q2.metric("Valid", f"{H['total_tests']:,}")
    q3.metric("Quarantined", f"{rejected.height:,}")

    if rejected.height:
        st.write("Reasons for rejection:")
        st.dataframe(
            rejected["reject_reason"].value_counts().sort("count", descending=True).to_pandas(),
            hide_index=True, use_container_width=True,
        )
        st.download_button(
            "⬇️ Download quarantined rows (CSV)",
            data=rejected.write_csv().encode("utf-8-sig"),
            file_name="bioreflex_quarantine.csv", mime="text/csv",
        )
    else:
        st.success("No rows were rejected ✔")

st.divider()
st.caption(
    "Decision-support screening tool — flags are suspicions that prompt a confirmatory test, "
    "not diagnoses. | أداة فرز داعمة للقرار وليست تشخيصاً نهائياً."
)
