# BioRefleX — النسخة المقسّمة إلى مراحل (للتشغيل خطوة بخطوة في VS Code)
# كل سطر "# %%" يبدأ خلية مستقلة. اضغط "Run Cell" فوق كل خلية بالترتيب.
# إذا ظهر خطأ في خلية، أصلحه فيها وأعد تشغيلها فقط دون الرجوع للبداية.

# %% [markdown]
# ## المرحلة 0: الإعدادات والمكتبات

# %%
import re
import uuid
from pathlib import Path

import polars as pl

CSV_PATH = Path("diagnosed_cbc_data_v4.csv")   # غيّر المسار إذا لزم
OUT_DIR = Path("output")
OUT_DIR.mkdir(exist_ok=True)

REQUIRED_COLS = ["hgb", "rbc", "mcv"]
NUMERIC_COLS = ["hgb", "rbc", "mcv", "mch", "mchc", "plt", "wbc", "hct"]

PLAUSIBLE = {              # حدود منطقية فسيولوجياً
    "hgb": (2.0, 25.0),
    "rbc": (1.0, 9.0),
    "mcv": (40.0, 140.0),
    "wbc": (0.1, 200.0),
    "plt": (5.0, 2000.0),
}

HGB_FEMALE, HGB_MALE, HGB_DEFAULT = 12.0, 13.0, 12.0
MICROCYTIC_MCV = 80.0
MENTZER_CUTOFF = 13.0
WBC_HIGH = 11.0

BASE_CBC_PRICE = 10_000
PRICE_FERRITIN = 15_000
PRICE_ELECTROPHORESIS = 25_000
PRICE_CRP = 10_000
ZAINCASH_LABEL = "Enabled - ZainCash 15% Preventive Subsidy"

print("polars", pl.__version__, "| الإعدادات جاهزة")

# %% [markdown]
# ## المرحلة 1: قراءة الملف

# %%
print("الملف موجود؟", CSV_PATH.exists(), "|", CSV_PATH.resolve())

df_raw = pl.read_csv(
    CSV_PATH,
    infer_schema_length=10_000,
    null_values=["", "NA", "N/A", "NaN", "nan", "null", "-"],
)
print("الشكل:", df_raw.shape)
print("الأعمدة الأصلية:", df_raw.columns)
df_raw.head(3)

# %% [markdown]
# ## المرحلة 2: توحيد أسماء الأعمدة وفحص الأعمدة المطلوبة

# %%
def snake(name: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_", name.strip().lower()).strip("_")

df = df_raw.rename({c: snake(c) for c in df_raw.columns})
print("الأعمدة بعد التوحيد:", df.columns)

missing = [c for c in REQUIRED_COLS if c not in df.columns]
assert not missing, f"أعمدة مطلوبة ناقصة: {missing}  <- عدّل REQUIRED_COLS أو أسماء الأعمدة"
print("كل الأعمدة المطلوبة موجودة ✔")

# %% [markdown]
# ## المرحلة 3: تحويل الأعمدة الرقمية

# %%
for col in (c for c in NUMERIC_COLS if c in df.columns):
    before = df[col].null_count()
    df = df.with_columns(pl.col(col).cast(pl.Float64, strict=False))
    added = df[col].null_count() - before
    print(f"{col:5s} | dtype={df[col].dtype} | nulls={df[col].null_count()} | قيم غير رقمية تحولت لـ null: {added}")

# %% [markdown]
# ## المرحلة 4: المعرّف العشوائي (UUID)

# %%
ids = pl.Series("transaction_id", [str(uuid.uuid4()) for _ in range(df.height)])
df = df.insert_column(0, ids)
print("عدد المعرفات الفريدة = عدد الصفوف؟", df["transaction_id"].n_unique() == df.height)
df.select("transaction_id", *REQUIRED_COLS).head(3)

# %% [markdown]
# ## المرحلة 5: التدقيق وعزل السجلات المرفوضة

# %%
reasons = [
    pl.when(pl.col(c).is_null()).then(pl.lit(f"missing_{c}")) for c in REQUIRED_COLS
]
for col, (lo, hi) in PLAUSIBLE.items():
    if col in df.columns:
        reasons.append(
            pl.when(pl.col(col).is_not_null() & ~pl.col(col).is_between(lo, hi))
            .then(pl.lit(f"implausible_{col}"))
        )

tagged = df.with_columns(pl.concat_str(reasons, separator=",", ignore_nulls=True).alias("_reject"))
valid = tagged.filter(pl.col("_reject") == "").drop("_reject")
rejected = tagged.filter(pl.col("_reject") != "").rename({"_reject": "reject_reason"})

print(f"الإجمالي={df.height} | صالح={valid.height} | مرفوض={rejected.height}")
if rejected.height:
    print(rejected["reject_reason"].value_counts())
df = valid

# %% [markdown]
# ## المرحلة 6: هندسة الميزات (Mentzer وحالة الأنيميا)

# %%
if "sex" in df.columns:
    sex = pl.col("sex").cast(pl.Utf8).str.to_lowercase().str.strip_chars().str.slice(0, 1)
    hgb_cut = (
        pl.when(sex == "f").then(pl.lit(HGB_FEMALE))
        .when(sex == "m").then(pl.lit(HGB_MALE))
        .otherwise(pl.lit(HGB_DEFAULT))
    )
else:
    hgb_cut = pl.lit(HGB_DEFAULT)

wbc_flag = (
    (pl.col("wbc") > WBC_HIGH).fill_null(False)
    if "wbc" in df.columns else pl.lit(False)
)

df = (
    df.with_columns(
        pl.when(pl.col("rbc") > 0)
        .then((pl.col("mcv") / pl.col("rbc")).round(2))
        .alias("mentzer_index"),
        hgb_cut.alias("hgb_threshold_used"),
    )
    .with_columns(
        (pl.col("hgb") < pl.col("hgb_threshold_used")).alias("is_anemic"),
        (pl.col("mcv") < MICROCYTIC_MCV).alias("is_microcytic"),
        wbc_flag.alias("is_leukocytosis"),
    )
)
print(df.select("hgb", "mcv", "rbc", "mentzer_index", "is_anemic", "is_microcytic", "is_leukocytosis").head(5))
print("عدد حالات الأنيميا:", df["is_anemic"].sum())

# %% [markdown]
# ## المرحلة 7: قواعد الاستدلال السريري

# %%
df = df.with_columns(
    (pl.col("is_anemic") & pl.col("is_microcytic") & (pl.col("mentzer_index") < MENTZER_CUTOFF)).alias("rule_thalassemia"),
    (pl.col("is_anemic") & pl.col("is_microcytic") & (pl.col("mentzer_index") >= MENTZER_CUTOFF)).alias("rule_iron_deficiency"),
    (pl.col("is_anemic") & ~pl.col("is_microcytic")).alias("rule_other_anemia"),
    pl.col("is_leukocytosis").alias("rule_inflammation"),
)

df = df.with_columns(
    pl.when(pl.col("rule_thalassemia")).then(pl.lit("Suspected Thalassemia Trait"))
    .when(pl.col("rule_iron_deficiency")).then(pl.lit("Suspected Iron Deficiency"))
    .when(pl.col("rule_other_anemia")).then(pl.lit("Anemia (Non-Microcytic) - Clinician Review"))
    .when(pl.col("rule_inflammation")).then(pl.lit("Suspected Systemic Inflammation"))
    .otherwise(pl.lit("Within Reference Range"))
    .alias("clinical_flag"),
    pl.concat_str(
        [
            pl.when(pl.col("rule_thalassemia")).then(pl.lit("Hemoglobin Electrophoresis")),
            pl.when(pl.col("rule_iron_deficiency")).then(pl.lit("Serum Ferritin Test")),
            pl.when(pl.col("rule_inflammation")).then(pl.lit("C-Reactive Protein (CRP)")),
        ],
        separator=" + ", ignore_nulls=True,
    ).alias("_rec"),
).with_columns(
    pl.when(pl.col("_rec") == "").then(pl.lit("None")).otherwise(pl.col("_rec")).alias("reflex_recommendation")
).drop("_rec")

print(df["clinical_flag"].value_counts().sort("count", descending=True))
print(df["reflex_recommendation"].value_counts().sort("count", descending=True))

# %% [markdown]
# ## المرحلة 8: السبب المكتوب لكل توصية (Explainability)

# %%
def s(col):
    return pl.col(col).cast(pl.Utf8)

df = df.with_columns(
    pl.when(pl.col("rule_thalassemia")).then(pl.concat_str([
        pl.lit("Hb "), s("hgb"), pl.lit(" < "), s("hgb_threshold_used"),
        pl.lit("; MCV "), s("mcv"), pl.lit(f" < {MICROCYTIC_MCV:g}; Mentzer "),
        s("mentzer_index"), pl.lit(f" < {MENTZER_CUTOFF:g}"),
    ]))
    .when(pl.col("rule_iron_deficiency")).then(pl.concat_str([
        pl.lit("Hb "), s("hgb"), pl.lit(" < "), s("hgb_threshold_used"),
        pl.lit("; MCV "), s("mcv"), pl.lit(f" < {MICROCYTIC_MCV:g}; Mentzer "),
        s("mentzer_index"), pl.lit(f" >= {MENTZER_CUTOFF:g}"),
    ]))
    .when(pl.col("rule_other_anemia")).then(pl.concat_str([
        pl.lit("Hb "), s("hgb"), pl.lit(" below threshold; MCV "), s("mcv"),
        pl.lit(" not microcytic - Mentzer not applicable"),
    ]))
    .when(pl.col("rule_inflammation")).then(pl.concat_str([
        pl.lit("WBC "), s("wbc"), pl.lit(f" > {WBC_HIGH:g}"),
    ]))
    .otherwise(pl.lit("All evaluated indices within rule thresholds"))
    .alias("flag_rationale")
)
df.select("clinical_flag", "flag_rationale").head(5)

# %% [markdown]
# ## المرحلة 9: التسعير

# %%
reflex_price = (
    pl.when(pl.col("rule_thalassemia")).then(PRICE_ELECTROPHORESIS).otherwise(0)
    + pl.when(pl.col("rule_iron_deficiency")).then(PRICE_FERRITIN).otherwise(0)
    + pl.when(pl.col("rule_inflammation")).then(PRICE_CRP).otherwise(0)
)

df = (
    df.with_columns(
        pl.lit(BASE_CBC_PRICE, dtype=pl.Int64).alias("base_cbc_price_iqd"),
        reflex_price.cast(pl.Int64).alias("reflex_price_iqd"),
    )
    .with_columns(
        (pl.col("base_cbc_price_iqd") + pl.col("reflex_price_iqd")).alias("total_potential_ticket_iqd"),
        pl.when(pl.col("reflex_price_iqd") > 0)
        .then(pl.lit(ZAINCASH_LABEL))
        .otherwise(pl.lit("Standard Clearance"))
        .alias("zaincash_gateway_action"),
    )
)
df.select("clinical_flag", "reflex_price_iqd", "total_potential_ticket_iqd", "zaincash_gateway_action").head(5)

# %% [markdown]
# ## المرحلة 10: حساب المؤشرات

# %%
total_tests = df.height
assert total_tests > 0, "لا توجد سجلات صالحة للتحليل"

flagged_cases = df.filter(pl.col("reflex_recommendation") != "None").height
screening_yield = round(flagged_cases / total_tests * 100, 2)
base_rev = int(df["base_cbc_price_iqd"].sum())
opt_rev = int(df["total_potential_ticket_iqd"].sum())
reflex_rev = opt_rev - base_rev
uplift = round(reflex_rev / base_rev * 100, 2)
avg_ticket_before = base_rev / total_tests
avg_ticket_after = opt_rev / total_tests

# التوزيع حسب التشخيص المشتبه
by_flag = (
    df.group_by("clinical_flag")
    .agg(
        pl.len().alias("n"),
        pl.col("hgb").mean().alias("avg_hgb"),
        pl.col("mentzer_index").mean().alias("avg_mentzer"),
    )
    .sort("n", descending=True)
)

# التوزيع حسب الفحص الموصى به
by_test = (
    df.group_by("reflex_recommendation")
    .agg(
        pl.len().alias("n"),
        pl.col("reflex_price_iqd").sum().alias("reflex_rev"),
    )
    .sort("n", descending=True)
)

print("✔ تم حساب المؤشرات")

# %% [markdown]
# ## المرحلة 11: التقرير النهائي المنظم

# %%
W = 84


def rule(ch="─"):
    return ch * W


def banner(text):
    return ["", rule("═"), f"  {text}", rule("═")]


def section(text):
    return ["", f"■ {text}", rule()]


def kv(rows, key_w=44):
    return [f"  {k.ljust(key_w)}{v}" for k, v in rows]


def fmt(x, nd=2):
    return "-" if x is None else f"{x:.{nd}f}"


def table(headers, rows, aligns):
    """جدول نصي منسّق. aligns: 'l' يسار أو 'r' يمين لكل عمود."""
    widths = [
        max([len(str(h))] + [len(str(r[i])) for r in rows])
        for i, h in enumerate(headers)
    ]

    def cell(v, w, a):
        return str(v).ljust(w) if a == "l" else str(v).rjust(w)

    out = ["  " + "  ".join(cell(h, w, a) for h, w, a in zip(headers, widths, aligns))]
    out.append("  " + "  ".join("─" * w for w in widths))
    for r in rows:
        out.append("  " + "  ".join(cell(v, w, a) for v, w, a in zip(r, widths, aligns)))
    return out


def bar(share, width=24):
    n = round(share / 100 * width)
    return "█" * max(n, 1 if share > 0 else 0)


lines = []

# ── العنوان ──
lines += banner("BioRefleX | تقرير محرك الاستدلال المخبري")

# ── 1. جودة البيانات ──
lines += section("1) Data Quality | جودة البيانات")
lines += kv([
    ("Rows in file", f"{df_raw.height:,}"),
    ("Valid rows analysed", f"{total_tests:,}"),
    ("Quarantined rows", f"{rejected.height:,}"),
])
if rejected.height:
    for r in rejected["reject_reason"].value_counts().sort("count", descending=True).iter_rows():
        lines.append(f"     - {r[0]}: {r[1]:,}")

# ── 2. الملخص التنفيذي ──
lines += section("2) Executive Summary | الملخص التنفيذي")
lines += kv([
    ("Cases flagged for reflex testing", f"{flagged_cases:,} of {total_tests:,}"),
    ("Screening yield", f"{screening_yield}%"),
    ("Cases within reference / no test", f"{total_tests - flagged_cases:,}"),
])

# ── 3. التوزيع التشخيصي ──
lines += section("3) Suspected Findings | التوزيع التشخيصي")
rows = []
for r in by_flag.iter_rows(named=True):
    share = r["n"] / total_tests * 100
    rows.append((
        r["clinical_flag"], f"{r['n']:,}", f"{share:.1f}%",
        fmt(r["avg_hgb"]), fmt(r["avg_mentzer"]), bar(share),
    ))
lines += table(
    ["Clinical flag", "Count", "Share", "Avg Hb", "Avg Mentzer", ""],
    rows, ["l", "r", "r", "r", "r", "l"],
)

# ── 4. الفحوصات الموصى بها ──
lines += section("4) Recommended Reflex Tests | الفحوصات التكميلية الموصى بها")
rows = [
    (r["reflex_recommendation"], f"{r['n']:,}", f"{r['n'] / total_tests * 100:.1f}%", f"{r['reflex_rev']:,}")
    for r in by_test.iter_rows(named=True)
]
lines += table(
    ["Recommended test(s)", "Count", "Share", "Reflex revenue (IQD)"],
    rows, ["l", "r", "r", "r"],
)

# ── 5. الأثر المالي ──
lines += section("5) Financial Impact | الأثر المالي (IQD)")
lines += kv([
    ("Baseline revenue (CBC only)", f"{base_rev:>15,}"),
    ("Reflex revenue (potential)", f"{reflex_rev:>15,}"),
    ("Total potential revenue", f"{opt_rev:>15,}"),
    ("Avg ticket: before -> after", f"{avg_ticket_before:,.0f} -> {avg_ticket_after:,.0f}"),
    ("Basket size growth", f"+{uplift}%"),
])
lines.append("  Note: assumes every flagged patient completes the recommended test (upper bound).")

# ── 6. أمثلة ──
lines += section("6) Sample Flagged Records | أمثلة على الحالات المحوّلة")
sample = df.filter(pl.col("reflex_recommendation") != "None").head(5)
if sample.height == 0:
    lines.append("  (no flagged records)")
for k, r in enumerate(sample.iter_rows(named=True), 1):
    lines += [
        f"  [{k}] ID {r['transaction_id'][:8]}   Hb={r['hgb']}  MCV={r['mcv']}  RBC={r['rbc']}  Mentzer={r['mentzer_index']}",
        f"      Flag : {r['clinical_flag']}",
        f"      Test : {r['reflex_recommendation']}   ({r['total_potential_ticket_iqd']:,} IQD)",
        f"      Why  : {r['flag_rationale']}",
        "",
    ]

lines.append(rule("═"))
lines.append("  Decision-support screening only; not a diagnosis. | أداة فرز داعمة وليست تشخيصاً نهائياً.")
lines.append(rule("═"))

report_text = "\n".join(lines)
print(report_text)

# %% [markdown]
# ## المرحلة 12: حفظ المخرجات

# %%
# تقرير نصي جاهز للإرفاق
(OUT_DIR / "bioreflex_report.txt").write_text(report_text, encoding="utf-8")

# جدول نظيف بأهم الأعمدة (يفتح مباشرة في Excel)
clean_cols = [
    "transaction_id", "hgb", "mcv", "rbc", "mentzer_index",
    "clinical_flag", "reflex_recommendation", "flag_rationale",
    "total_potential_ticket_iqd", "zaincash_gateway_action",
]
df.select(clean_cols).write_csv(OUT_DIR / "bioreflex_clean_results.csv")

# النتائج الكاملة والملخصات
df.write_parquet(OUT_DIR / "bioreflex_results.parquet")
by_flag.write_csv(OUT_DIR / "bioreflex_by_flag.csv")
by_test.write_csv(OUT_DIR / "bioreflex_by_test.csv")
if rejected.height:
    rejected.write_csv(OUT_DIR / "bioreflex_quarantine.csv")

print("تم الحفظ في:", OUT_DIR.resolve())
for f in sorted(OUT_DIR.iterdir()):
    print("  •", f.name)
