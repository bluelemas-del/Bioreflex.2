import streamlit as st
import polars as pl
from urllib.parse import quote

from pipeline import CBCPipeline

CSV_PATH = "diagnosed_cbc_data_v4.csv"

PAGE_CSS = """
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

    .pink-header {
        font-size: 2.1rem;
        font-weight: 800;
        letter-spacing: 0.02em;
        color: #0F172A;
        margin-bottom: 0.35rem;
    }

    .section-tag {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.45rem 0.75rem;
        border-radius: 999px;
        background: #FDF2F8;
        border: 1px solid #F9A8D4;
        color: #BE185D;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        margin-bottom: 1rem;
    }

    .panel, .status-card, .action-card {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-top: 3px solid #F472B6;
        border-radius: 12px;
        box-shadow: 0 4px 14px 0 rgba(244, 114, 182, 0.08);
        padding: 1rem 1.1rem;
    }

    .action-card {
        border-left: 4px solid #DC2626;
        background: #FFF7F7;
        color: #7F1D1D;
    }

    .status-badge {
        display: inline-block;
        padding: 0.32rem 0.65rem;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }

    .status-badge.queued {
        background: #FEF3C7;
        color: #92400E;
    }

    .status-badge.dispatched {
        background: #DCFCE7;
        color: #166534;
    }

    .specimen-label {
        color: #64748B;
        font-size: 0.75rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        font-weight: 700;
        margin-bottom: 0.2rem;
    }

    .specimen-value {
        color: #0F172A;
        font-size: 1.05rem;
        font-weight: 700;
        margin-bottom: 0.4rem;
    }

    .metric-row {
        display: grid;
        grid-template-columns: repeat(2, minmax(140px, 1fr));
        gap: 0.75rem;
        margin-top: 0.85rem;
    }

    .metric-box {
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 0.7rem 0.8rem;
    }

    .metric-box strong {
        display: block;
        font-size: 0.72rem;
        color: #64748B;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin-bottom: 0.2rem;
    }

    .metric-box span {
        color: #0F172A;
        font-size: 1.05rem;
        font-weight: 700;
    }

    .stDataFrame {
        border-radius: 12px;
        overflow: hidden;
    }

    [data-testid="stLinkButton"] > a {
        background: linear-gradient(135deg, #F472B6 0%, #EC4899 100%);
        border: 1px solid #F9A8D4;
        border-radius: 12px;
        color: #FFFFFF !important;
        font-weight: 700;
        padding: 0.8rem 1.1rem;
        box-shadow: 0 10px 24px rgba(236, 72, 153, 0.18);
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }

    [data-testid="stLinkButton"] > a:hover {
        transform: translateY(-1px);
        box-shadow: 0 12px 28px rgba(236, 72, 153, 0.22);
    }

    [data-testid="stLinkButton"] > a:focus-visible {
        outline: 3px solid rgba(244, 114, 182, 0.25);
        outline-offset: 2px;
    }
</style>
"""


def load_reflex_queue(csv_path: str = CSV_PATH) -> pl.DataFrame:
    pipeline = CBCPipeline(csv_path)
    pipeline.load_and_standardize()
    pipeline.sanitize_and_filter()
    pipeline.compute_indices_and_rules()
    pipeline.compute_economics()
    df = pipeline.df

    if df is None or df.height == 0:
        return pl.DataFrame({})

    queue = df.filter(
        pl.col("clinical_flag").is_in(["Suspected Iron Deficiency", "Suspected Thalassemia Trait"])
    )

    if queue.height == 0:
        return queue

    queue = queue.with_row_index(name="patient_id").with_columns(
        (pl.col("patient_id") + 1).alias("patient_id")
    )

    queue = queue.with_columns(
        pl.concat_str(
            [
                pl.lit("Patient #"),
                pl.col("patient_id").cast(pl.Utf8),
                pl.lit(" — "),
                pl.col("clinical_flag"),
            ]
        ).alias("display_label")
    )

    return queue


@st.cache_data(show_spinner=False)
def get_reflex_queue(csv_path: str = CSV_PATH) -> pl.DataFrame:
    return load_reflex_queue(csv_path)


def get_status(patient_id: int) -> str:
    state = st.session_state.setdefault("reflex_dispatch_status", {})
    return state.get(int(patient_id), "Queued")


def get_reflex_directive(row: dict) -> dict:
    flag = row.get("clinical_flag", "")
    if flag == "Suspected Iron Deficiency":
        return {
            "tube_directive": "⚠️ TUBE ACTION: Retain Serum/Gel tube in cold rack. Direct to automated Immunoassay track for Ferritin.",
            "ordered_test": "Serum Ferritin",
            "added_value": 15_000,
            "narrative": "Microcytic anemia with Mentzer > 13 is most consistent with iron deficiency; ferritin confirmation will help avoid unnecessary extended workup.",
        }
    if flag == "Suspected Thalassemia Trait":
        return {
            "tube_directive": "⚠️ TUBE ACTION: Retain existing EDTA whole blood tube on analyzer. Direct to HPLC / Hemoglobin Electrophoresis track.",
            "ordered_test": "Hb Electrophoresis",
            "added_value": 25_000,
            "narrative": "Microcytic anemia with Mentzer < 13 is most compatible with thalassemia trait; confirmatory hemoglobinopathy testing should be performed without delay.",
        }
    return {
        "tube_directive": "⚠️ TUBE ACTION: Retain specimen and standard processing pathway remains unchanged.",
        "ordered_test": "Not required",
        "added_value": 0,
        "narrative": "Routine CBC processing continues; no reflex retention required.",
    }


def build_whatsapp_message(row: dict) -> str:
    patient_id = row.get("patient_id", "-")
    clinical_flag = row.get("clinical_flag", "Suspected Iron Deficiency")
    reflex_plan = get_reflex_directive(row)
    reflex_order = reflex_plan["ordered_test"]
    mentzer = row.get("mentzer_index", 0.0)
    hgb = row.get("hgb", 0.0)
    mcv = row.get("mcv", 0.0)
    rbc = row.get("rbc", 0.0)
    sample_id = row.get("sample_id") or f"CBC-{patient_id}"
    warning_text = reflex_plan["tube_directive"]
    revenue = reflex_plan["added_value"]

    return f"""Hello Clinical Team,\n\nWe have an active CBC specimen for Patient #{patient_id} ({sample_id}) that is currently preserved and requires immediate secondary reflex confirmation to avoid a second visit and second venipuncture.\n\nClinical assessment:\n- Pattern: {clinical_flag}\n- HGB: {hgb} g/dL\n- MCV: {mcv} fL\n- RBC: {rbc} x10^12/L\n- Mentzer Index: {mentzer:.2f}\n- Recommended reflex: {reflex_order}\n- Added billable value: {revenue:,.0f} IQD\n\n{warning_text}\n\nThis is the best time to proceed with confirmation now because it prevents an additional clinic visit, consultation fee, and repeat blood draw. A same-day confirmatory study improves patient convenience and preserves specimen integrity while supporting accurate diagnosis and management.\n\nPlease confirm consent and proceed with the reflex panel immediately.\n\nالسلام عليكم،\n\nلدى فريقنا عينة CBC نشطة للمريض #{patient_id} ({sample_id}) وهي محجوزة حاليا ويجب إكمال الفحص الارتجاعي فوراً لتجنب زيارة ثانية وسحب دم ثانٍ، بالإضافة إلى توفير الرسوم الاستشارية الإضافية.\n\nالتقييم السريري:\n- النمط: {clinical_flag}\n- HGB: {hgb} g/dL\n- MCV: {mcv} fL\n- RBC: {rbc} x10^12/L\n- مؤشر Mentzer: {mentzer:.2f}\n- الفحص الارتجاعي المقترح: {reflex_order}\n- القيمة المضافة القابلة للفوترة: {revenue:,.0f} IQD\n\n{warning_text}\n\nهذا هو الوقت الأنسب لإجراء التأكيد الآن لأنه يمنع الزيارة الإضافية، ورسوم الاستشارة، وسحب الدم الثاني. كما يحسن راحة المريض ويضمن سلامة العينة ويؤدي إلى تشخيص دقيق وإدارة مناسبة.\n\nيرجى تأكيد الموافقة ومباشرة الفحص الارتجاعي فوراً.\n"""


def build_pdf_footnote(row: dict) -> str:
    reflex_plan = get_reflex_directive(row)
    flag = row.get("clinical_flag", "")
    context = "iron deficiency" if flag == "Suspected Iron Deficiency" else "thalassemia trait"
    test_name = reflex_plan["ordered_test"]
    return (
        f"Clinical recommendation: Microcytic pattern with Mentzer index {row.get('mentzer_index', 0.0):.2f} is consistent with {context}. "
        f"Please proceed with {test_name} confirmation at the earliest opportunity to avoid delayed diagnosis and repeat venipuncture."
    )


def normalize_phone_number(raw_phone: str) -> str:
    digits = "".join(ch for ch in (raw_phone or "") if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("964"):
        return f"+{digits}"
    if digits.startswith("0"):
        return f"+964{digits[1:]}"
    return f"+{digits}"


st.set_page_config(page_title="Reflex Triage", layout="wide")
st.markdown(PAGE_CSS, unsafe_allow_html=True)

st.markdown('<div class="pink-header">Reflex Triage Queue</div>', unsafe_allow_html=True)
st.markdown('<div class="section-tag">Active reflex workflow</div>', unsafe_allow_html=True)
st.caption("Microcytic hypochromic CBC specimens requiring secondary reflex review, consent capture, and lab-side retention.")

try:
    queue_df = get_reflex_queue()
except Exception as exc:
    st.error(f"The reflex queue could not be loaded: {exc}")
    st.stop()

if queue_df is None or queue_df.height == 0:
    st.info("No patients currently match the Mentzer-triggered reflex queue.")
    st.stop()

queue_display = queue_df.select([
    "patient_id",
    "display_label",
    "clinical_flag",
    "reflex_order",
    "mentzer_index",
    "hgb",
    "mcv",
    "rbc",
    "wbc",
    "add_on_revenue",
])

queue_display = queue_display.with_columns(
    pl.col("mentzer_index").cast(pl.Float64),
    pl.col("hgb").cast(pl.Float64),
    pl.col("mcv").cast(pl.Float64),
    pl.col("rbc").cast(pl.Float64),
    pl.col("wbc").cast(pl.Float64),
    pl.col("add_on_revenue").cast(pl.Float64),
)

queue_records = queue_display.to_dicts()
for item in queue_records:
    item["status"] = get_status(int(item["patient_id"]))

selector_labels = [item["display_label"] for item in queue_records]
selected_label = st.selectbox("Select a flagged specimen", selector_labels, index=0)
selected_row = next(item for item in queue_records if item["display_label"] == selected_label)
selected_row_id = int(selected_row["patient_id"])
selected_row["status"] = get_status(selected_row_id)
selected_reflex = get_reflex_directive(selected_row)

confirmed_total = sum(
    float(item.get("add_on_revenue", 0) or 0)
    for item in queue_records
    if get_status(int(item["patient_id"])) == "Reflex Confirmed"
)

status_text = get_status(selected_row_id)
status_class = "dispatched" if status_text == "Reflex Confirmed" else "queued"

st.markdown(
    f"<div class='status-card'><span class='status-badge {status_class}'>{status_text}</span></div>",
    unsafe_allow_html=True,
)

st.markdown("### Specimen Action Card")
st.markdown(
    f"""
    <div class='action-card'>
        <div class='specimen-label'>Tube Retention Alert</div>
        <div class='specimen-value'>{selected_reflex['tube_directive']}</div>
        <div class='specimen-label' style='margin-top: 0.8rem;'>Automated Order Generated</div>
        <div class='specimen-value'>{selected_reflex['ordered_test']}</div>
        <div class='specimen-label' style='margin-top: 0.8rem;'>Added Billable Revenue</div>
        <div class='specimen-value'>{selected_reflex['added_value']:,} IQD</div>
    </div>
    """,
    unsafe_allow_html=True,
)

col_left, col_right = st.columns([1.3, 1.1])
with col_left:
    st.markdown("### Patient Snapshot")
    st.markdown(
        f"""
        <div class='panel'>
            <div class='specimen-label'>Matching clinical flag</div>
            <div class='specimen-value'>{selected_row['clinical_flag']}</div>
            <div class='metric-row'>
                <div class='metric-box'><strong>HGB</strong><span>{selected_row.get('hgb', 0.0):.1f} g/dL</span></div>
                <div class='metric-box'><strong>MCV</strong><span>{selected_row.get('mcv', 0.0):.1f} fL</span></div>
                <div class='metric-box'><strong>RBC</strong><span>{selected_row.get('rbc', 0.0):.1f} x10^12/L</span></div>
                <div class='metric-box'><strong>Mentzer</strong><span>{selected_row.get('mentzer_index', 0.0):.2f}</span></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with col_right:
    st.markdown("### Active Reflex Queue")
    st.dataframe(
        pl.DataFrame(queue_records).select([
            "patient_id",
            "clinical_flag",
            "reflex_order",
            "mentzer_index",
            "add_on_revenue",
        ]),
        use_container_width=True,
        hide_index=True,
    )

bill_summary = f"Reflex-confirmed revenue total: {confirmed_total:,.0f} IQD"
st.markdown(
    f"<div class='panel'><div class='specimen-label'>Billing Summary</div><div class='specimen-value'>{bill_summary}</div></div>",
    unsafe_allow_html=True,
)

st.markdown("### WhatsApp Upsell & Clinical Communication Console")
whatsapp_text = build_whatsapp_message(selected_row)

phone_default = "+9647XXXXXXXXX"
phone_number = st.text_input(
    "Patient phone number",
    value=st.session_state.get("selected_phone_number", ""),
    key="selected_phone_number",
    placeholder=phone_default,
    help="Use a valid local mobile number so the dispatch link opens directly in WhatsApp.",
)

normalized_phone = normalize_phone_number(phone_number)
wa_url = ""
if normalized_phone:
    clean_phone = normalized_phone.replace("+", "")
    wa_url = f"https://api.whatsapp.com/send?phone={clean_phone}&text={quote(whatsapp_text, safe='')}"

st.text_area("Ready-to-copy message", whatsapp_text, height=280, key="whatsapp_message")

if normalized_phone:
    st.markdown(
        f'<a href="{wa_url}" target="_blank" rel="noopener noreferrer">'
        '<button style="width: 100%; background: linear-gradient(135deg, #F472B6 0%, #EC4899 100%); '
        'border: 1px solid #F9A8D4; border-radius: 12px; color: white; font-weight: 700; '
        'padding: 0.8rem 1.1rem; cursor: pointer; box-shadow: 0 10px 24px rgba(236, 72, 153, 0.18);">'
        '📲 Open in WhatsApp / إرسال عبر الواتساب'
        '</button></a>',
        unsafe_allow_html=True,
    )
else:
    st.info("Enter the patient phone number to generate the direct WhatsApp dispatch link.")

if st.button("Confirm Patient Consent & Add to Bill", use_container_width=True):
    st.session_state.setdefault("reflex_dispatch_status", {})
    st.session_state["reflex_dispatch_status"][selected_row_id] = "Reflex Confirmed"
    st.success(
        f"Patient #{selected_row_id} has been confirmed for reflex testing and added to the billable queue. "
        f"Revenue added: {selected_reflex['added_value']:,} IQD."
    )

pdf_footnote = build_pdf_footnote(selected_row)
st.markdown("### Clinical PDF Recommendation")
st.code(pdf_footnote, language=None)

st.caption("The reflex status is tracked per patient within this session, and the billable confirmation total updates dynamically.")
