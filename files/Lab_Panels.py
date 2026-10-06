"""All-blood-tests analysis page (sex/age-aware ranges, critical values, rules, reflex revenue)."""
import io
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lab_engine import (  # noqa: E402
    RANGES_PATH, RULES_PATH, analyze, find_column, load_ranges, load_rules, match_columns,
)

DISCLAIMER = (
    "Decision support only - not a diagnosis. Reference ranges and rules are starter drafts and "
    "must be reviewed and approved by your laboratory director or a qualified clinician before use "
    "with real patients."
)

st.set_page_config(page_title="Bioreflex - All Blood Tests", page_icon="🧪", layout="wide")
st.title("All Blood Tests")
st.caption("Upload any lab results file. Values are checked against sex- and age-specific ranges, critical values are surfaced, and your reflex rules are applied.")
st.warning(DISCLAIMER)


# ------------------------------------------------------------------ helpers
@st.cache_data(show_spinner=False)
def read_table(name: str, data: bytes) -> pd.DataFrame:
    if name.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(data))
    return pd.read_csv(io.BytesIO(data), encoding="utf-8-sig", encoding_errors="replace")


def template_csv(ranges: pd.DataFrame) -> str:
    units = ranges.drop_duplicates("test").set_index("test")["unit"]
    cols = ["Patient ID", "Sex", "Age"] + [f"{t} ({u})" for t, u in units.items()]
    return pd.DataFrame(columns=cols).to_csv(index=False)


# ---------------------------------------------- editable ranges / rules state
if "ranges_df" not in st.session_state:
    st.session_state.ranges_df = load_ranges(RANGES_PATH)
    st.session_state.rules_df = load_rules(RULES_PATH)

tab_sum, tab_pat, tab_crit, tab_cfg = st.tabs(["Summary", "Patients", "Critical values", "Ranges, rules & prices"])

# Editors run first (code order) so edits apply to this same run's analysis.
with tab_cfg:
    st.markdown("**Reference ranges.** One row per test, sex and age band. `alt_factor` converts the alternative unit into the standard unit.")
    edited_ranges = st.data_editor(st.session_state.ranges_df, num_rows="dynamic", use_container_width=True, key="ranges_editor")
    st.markdown("**Rules and prices.** Conditions use `<test>_low` / `<test>_high` (for example `hgb_low and mentzer_index < 13`). Lower priority number runs first. Price is what you charge for the reflex test (IQD).")
    edited_rules = st.data_editor(st.session_state.rules_df, num_rows="dynamic", use_container_width=True, key="rules_editor")
    try:
        ranges_df, rules_df = load_ranges(edited_ranges), load_rules(edited_rules)
    except ValueError as exc:
        st.error(f"{exc}. Using the last valid settings.")
        ranges_df, rules_df = st.session_state.ranges_df, st.session_state.rules_df
    st.info("Edits here apply to your current session only. To make them permanent for everyone, download the files and replace `reference_ranges.csv` / `rules.csv` in the repository.")
    c1, c2 = st.columns(2)
    c1.download_button("Download reference_ranges.csv", ranges_df.to_csv(index=False), "reference_ranges.csv", "text/csv", use_container_width=True)
    c2.download_button("Download rules.csv", rules_df.to_csv(index=False), "rules.csv", "text/csv", use_container_width=True)

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown("### Data")
    upload = st.file_uploader("Upload results (CSV or Excel)", type=["csv", "xlsx"])
    st.download_button("Download file template", template_csv(ranges_df), "bioreflex_lab_template.csv", "text/csv", use_container_width=True)

if upload is not None:
    try:
        raw = read_table(upload.name, upload.getvalue())
    except Exception as exc:  # noqa: BLE001
        st.error(f"The file could not be read ({type(exc).__name__}: {exc}).")
        st.stop()
else:
    raw = pd.read_csv(ROOT / "sample_multi_panel.csv")
    st.info("Showing a sample dataset. Upload your own file in the sidebar.")

if raw.empty:
    st.warning("The file has no rows.")
    st.stop()

with st.sidebar:
    cols = ["(none)"] + list(raw.columns)
    sex_guess = find_column(raw.columns, ["sex", "gender"])
    age_guess = find_column(raw.columns, ["age"])
    sex_col = st.selectbox("Sex column", cols, index=cols.index(sex_guess) if sex_guess else 0)
    age_col = st.selectbox("Age column", cols, index=cols.index(age_guess) if age_guess else 0)
    default_sex = st.selectbox("Sex if no column", ["unknown", "male", "female"], help="Unknown uses the widest range, so fewer false flags.")
    default_age = st.number_input("Age if no column", 1, 120, 30)
    base_price = st.number_input("Base price per sample (IQD)", 0, 10_000_000, 10_000, step=1_000)

    colmap = match_columns([c for c in raw.columns if c not in (sex_col, age_col)], ranges_df)
    convertible = [
        (c, t, ranges_df[ranges_df["test"] == t].iloc[0])
        for c, t in colmap.items()
        if ranges_df[(ranges_df["test"] == t)]["alt_factor"].notna().any()
    ]
    alt_units = set()
    if convertible:
        with st.expander("Units - tick if your column uses the alternative unit"):
            for c, t, r in convertible:
                if st.checkbox(f"{c} is in {r['alt_unit']} (standard: {r['unit']})", key=f"unit_{t}"):
                    alt_units.add(t)

try:
    result = analyze(
        raw, ranges_df, rules_df,
        sex_col=None if sex_col == "(none)" else sex_col,
        age_col=None if age_col == "(none)" else age_col,
        default_sex=default_sex, default_age=float(default_age),
        alt_units=alt_units, base_price=float(base_price),
    )
except ValueError as exc:
    st.error(str(exc))
    st.stop()

out, rep = result.annotated, result.report

# ----------------------------------------------------------------- summary
with tab_sum:
    n = len(out)
    n_crit = int((out["critical_values"] != "").sum())
    n_flag = int((out["all_flags"] != "").sum())
    k = st.columns(5)
    k[0].metric("Patients", f"{n:,}")
    k[1].metric("Tests recognised", len(result.matched))
    k[2].metric("With critical values", n_crit)
    k[3].metric("With a pattern flag", n_flag)
    k[4].metric("Reflex add-on revenue", f"{out['add_on_revenue'].sum():,.0f} IQD")

    for msg in rep["unit_warnings"]:
        st.error(msg)
    if rep["no_range"]:
        st.warning("Some values have no reference range for the patient's age (the starter ranges cover adults 18+): " + ", ".join(f"{t} ({c})" for t, c in rep["no_range"].items()))
    if rep["unparseable"]:
        st.info("Cells that were not numbers were treated as empty: " + ", ".join(f"{c} ({v})" for c, v in rep["unparseable"].items()))
    if rep["failed_rules"]:
        for name, why in rep["failed_rules"].items():
            st.error(f"Rule '{name}' was skipped: {why}")
    if rep["unmatched_columns"]:
        st.caption("Ignored columns (not recognised as tests): " + ", ".join(map(str, rep["unmatched_columns"])))
    st.caption(f"Sex from: {rep['sex_source']}. Age from: {rep['age_source']}.")

    s = result.summary
    long = s.melt(id_vars="test", value_vars=["low", "high", "critical"], var_name="status", value_name="count")
    fig = px.bar(long, x="test", y="count", color="status", title="Abnormal results per test",
                 color_discrete_map={"low": "#4F8FF7", "high": "#F59E0B", "critical": "#DC2626"})
    fig.update_layout(height=380, margin=dict(t=50, b=20), xaxis_title=None, yaxis_title="Patients")
    st.plotly_chart(fig, use_container_width=True)

    left, right = st.columns(2)
    with left:
        st.markdown("**Per-test summary**")
        st.dataframe(s.rename(columns={"pct_abnormal": "% abnormal"}), use_container_width=True, hide_index=True)
    with right:
        st.markdown("**Rules and reflex orders**")
        rs = result.rules_summary.rename(columns={"revenue": "add-on revenue (IQD)"})
        st.dataframe(rs, use_container_width=True, hide_index=True)
        if rep["inactive_rules"]:
            st.caption("Not applicable to this file (needed tests missing): " + ", ".join(rep["inactive_rules"]))

# ---------------------------------------------------------------- patients
with tab_pat:
    only_abn = st.checkbox("Only patients with abnormal results", value=False)
    query = st.text_input("Search (any text in the row)", "")
    view = out.drop(columns=[c for c in out.columns if c.endswith("_status")])
    if only_abn:
        view = view[out["abnormal_count"] > 0]
    if query:
        hay = out.astype(str).agg(" ".join, axis=1).str.lower()
        view = view[hay.loc[view.index].str.contains(query.lower(), regex=False)]
    st.caption(f"{len(view):,} of {len(out):,} patients. `source_row` is the row number in your file (header = row 1).")
    st.dataframe(view, use_container_width=True, hide_index=True)
    st.download_button("Download full results (CSV)", out.to_csv(index=False).encode("utf-8-sig"), "bioreflex_results.csv", "text/csv")

# ---------------------------------------------------------------- critical
with tab_crit:
    crit = out[out["critical_values"] != ""]
    if crit.empty:
        st.success("No critical values in this file.")
    else:
        st.error(f"{len(crit)} patient(s) have critical values. These usually need immediate clinician notification according to your lab's policy.")
        id_cols = [c for c in raw.columns if c not in result.matched["your_column"].tolist()]
        st.dataframe(crit[["source_row"] + id_cols + ["critical_values"]], use_container_width=True, hide_index=True)
