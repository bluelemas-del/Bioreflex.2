#!/usr/bin/env python3
"""
BioRefleX — Clinical Decision Support (CDS) Reflex-Testing Engine
محرك BioRefleX لدعم القرار السريري والفحوصات الانعكاسية

Pipeline: Ingest -> Validate -> Feature Engineering -> Rule Engine -> Pricing -> KPIs

Design principles / مبادئ التصميم:
  * Explainable rules only (no black-box ML): every flag carries a human-readable rationale.
    قواعد مفسَّرة فقط، وكل توصية معها سبب واضح.
  * Configuration-driven: thresholds and prices live in `Config`, not inside the logic.
    الإعدادات منفصلة عن المنطق.
  * Fully vectorised Polars expressions (no Python row loops except UUID generation).
  * Nothing is dropped silently: every rejected row is quarantined with a reason.
    لا يُحذف أي سجل بصمت.
  * De-identified: random UUID4 per record; no patient identifiers are carried forward.
    معرّفات عشوائية بلا أي بيانات تعريفية للمريض.

DISCLAIMER: Decision-support screening tool. Flags are *suspicions* that prompt a confirmatory
test; they are not diagnoses. Final interpretation belongs to a licensed clinician.
تنبيه: أداة فرز داعمة للقرار، والتشخيص النهائي من اختصاص الطبيب.

Usage:
    python bioreflex_pipeline.py diagnosed_cbc_data_v4.csv \
        --out-dir output
"""

from __future__ import annotations

import argparse
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

log = logging.getLogger("bioreflex")


# ==============================================================================
# Configuration / الإعدادات
# ==============================================================================
@dataclass(frozen=True)
class Config:
    # --- Required CBC inputs -------------------------------------------------
    required_cols: tuple[str, ...] = ("hgb", "rbc", "mcv")
    numeric_cols: tuple[str, ...] = (
        "hgb", "rbc", "mcv", "mch", "mchc", "plt", "wbc", "hct",
    )

    # --- Physiological plausibility ranges (units as in the source file) -----
    # Values outside are treated as entry/analyser errors and quarantined.
    plausible_ranges: dict[str, tuple[float, float]] = field(default_factory=lambda: {
        "hgb": (2.0, 25.0),     # g/dL
        "rbc": (1.0, 9.0),      # 10^6/uL
        "mcv": (40.0, 140.0),   # fL
        "wbc": (0.1, 200.0),    # 10^3/uL
        "plt": (5.0, 2000.0),   # 10^3/uL
    })

    # --- Clinical thresholds -------------------------------------------------
    # WHO adult anaemia cut-offs. If no `sex` column exists, `hgb_default_threshold`
    # is used (12.0 preserves the original behaviour).
    hgb_threshold_female: float = 12.0
    hgb_threshold_male: float = 13.0
    hgb_default_threshold: float = 12.0
    microcytic_mcv_cutoff: float = 80.0   # fL; Mentzer is only meaningful when microcytic
    mentzer_cutoff: float = 13.0          # <13 favours thalassaemia trait, >=13 favours IDA
    wbc_high_cutoff: float = 11.0         # 10^3/uL (leukocytosis)

    # --- Business model (illustrative IQD pricing) ---------------------------
    base_cbc_price_iqd: int = 10_000
    reflex_prices_iqd: dict[str, int] = field(default_factory=lambda: {
        "Serum Ferritin Test": 15_000,
        "Hemoglobin Electrophoresis": 25_000,
        "C-Reactive Protein (CRP)": 10_000,
    })
    zaincash_action_label: str = "Enabled - ZainCash 15% Preventive Subsidy"


# ==============================================================================
# Stage 1 — Ingestion & Integrity / الاستيعاب والتدقيق
# ==============================================================================
def normalise_column_name(name: str) -> str:
    """'  Hgb (g/dL) ' -> 'hgb_g_dl' ; robust snake_case."""
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip().lower())
    return name.strip("_")


def load_cbc(path: Path, cfg: Config) -> pl.DataFrame:
    """Read the CSV, normalise headers, and coerce lab columns to Float64.

    Unlike `ignore_errors=True`, coercion failures are counted and logged.
    """
    df = pl.read_csv(
        path,
        infer_schema_length=10_000,
        null_values=["", "NA", "N/A", "NaN", "nan", "null", "-"],
    )
    df = df.rename({c: normalise_column_name(c) for c in df.columns})

    missing = [c for c in cfg.required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}. Found: {df.columns}")

    for col in (c for c in cfg.numeric_cols if c in df.columns):
        before = df[col].null_count()
        df = df.with_columns(pl.col(col).cast(pl.Float64, strict=False))
        introduced = df[col].null_count() - before
        if introduced:
            log.warning("Column %-5s: %d non-numeric value(s) coerced to null", col, introduced)

    # Random surrogate key: de-identified and untraceable to the patient.
    ids = pl.Series("transaction_id", [str(uuid.uuid4()) for _ in range(df.height)])
    return df.insert_column(0, ids)


def validate(df: pl.DataFrame, cfg: Config) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Split into (valid, quarantined). Quarantined rows carry a `reject_reason`."""
    reasons: list[pl.Expr] = []

    for col in cfg.required_cols:
        reasons.append(pl.when(pl.col(col).is_null()).then(pl.lit(f"missing_{col}")))

    for col, (lo, hi) in cfg.plausible_ranges.items():
        if col in df.columns:
            reasons.append(
                pl.when(pl.col(col).is_not_null() & ~pl.col(col).is_between(lo, hi))
                .then(pl.lit(f"implausible_{col}"))
            )

    tagged = df.with_columns(
        pl.concat_str(reasons, separator=",", ignore_nulls=True).alias("_reject")
    )
    valid = tagged.filter(pl.col("_reject") == "").drop("_reject")
    rejected = (
        tagged.filter(pl.col("_reject") != "")
        .rename({"_reject": "reject_reason"})
    )

    log.info("Rows: %d total | %d valid | %d quarantined", df.height, valid.height, rejected.height)
    return valid, rejected


# ==============================================================================
# Stage 2 — Feature Engineering / هندسة الميزات
# ==============================================================================
def engineer_features(df: pl.DataFrame, cfg: Config) -> pl.DataFrame:
    # Sex-specific anaemia threshold when available (WHO), otherwise the default.
    if "sex" in df.columns:
        sex = pl.col("sex").cast(pl.Utf8).str.to_lowercase().str.strip_chars().str.slice(0, 1)
        hgb_cut = (
            pl.when(sex == "f").then(pl.lit(cfg.hgb_threshold_female))
            .when(sex == "m").then(pl.lit(cfg.hgb_threshold_male))
            .otherwise(pl.lit(cfg.hgb_default_threshold))
        )
    else:
        hgb_cut = pl.lit(cfg.hgb_default_threshold)

    return df.with_columns(
        # RBC is guaranteed > 0 by validation, but guard anyway.
        pl.when(pl.col("rbc") > 0)
        .then((pl.col("mcv") / pl.col("rbc")).round(2))
        .alias("mentzer_index"),
        hgb_cut.alias("hgb_threshold_used"),
    ).with_columns(
        (pl.col("hgb") < pl.col("hgb_threshold_used")).alias("is_anemic"),
        (pl.col("mcv") < cfg.microcytic_mcv_cutoff).alias("is_microcytic"),
        (pl.col("mcv") > 100.0).alias("is_macrocytic"),
        (pl.col("wbc") > cfg.wbc_high_cutoff).fill_null(False).alias("is_leukocytosis")
        if "wbc" in df.columns else pl.lit(False).alias("is_leukocytosis"),
    ).with_columns(
        pl.when(pl.col("is_anemic")).then(pl.lit("Anemic")).otherwise(pl.lit("Normal"))
        .alias("anemia_status")
    )


# ==============================================================================
# Stage 3 — Clinical Reflex Engine / محرك القواعد السريرية
# ==============================================================================
# Each rule is (boolean expression, test ordered). Rules are independent so a
# patient can trigger several tests (e.g. iron-deficiency + inflammation).
def apply_reflex_rules(df: pl.DataFrame, cfg: Config) -> pl.DataFrame:
    is_thal = (
        pl.col("is_anemic") & pl.col("is_microcytic")
        & (pl.col("mentzer_index") < cfg.mentzer_cutoff)
    )
    is_ida = (
        pl.col("is_anemic") & pl.col("is_microcytic")
        & (pl.col("mentzer_index") >= cfg.mentzer_cutoff)
    )
    is_other_anemia = pl.col("is_anemic") & ~pl.col("is_microcytic")
    is_infl = pl.col("is_leukocytosis")

    df = df.with_columns(
        is_thal.alias("rule_thalassemia"),
        is_ida.alias("rule_iron_deficiency"),
        is_other_anemia.alias("rule_other_anemia"),
        is_infl.alias("rule_inflammation"),
    )

    # Primary flag: priority = anaemia pathway > inflammation > reference range.
    primary = (
        pl.when(pl.col("rule_thalassemia")).then(pl.lit("Suspected Thalassemia Trait"))
        .when(pl.col("rule_iron_deficiency")).then(pl.lit("Suspected Iron Deficiency"))
        .when(pl.col("rule_other_anemia")).then(pl.lit("Anemia (Non-Microcytic) - Clinician Review"))
        .when(pl.col("rule_inflammation")).then(pl.lit("Suspected Systemic Inflammation"))
        .otherwise(pl.lit("Within Reference Range"))
    )

    # Human-readable rationale for every decision (explainability / audit trail).
    rationale = (
        pl.when(pl.col("rule_thalassemia")).then(pl.concat_str([
            pl.lit("Hb "), pl.col("hgb").cast(pl.Utf8), pl.lit(" < "),
            pl.col("hgb_threshold_used").cast(pl.Utf8), pl.lit("; MCV "),
            pl.col("mcv").cast(pl.Utf8), pl.lit(" < 80; Mentzer "),
            pl.col("mentzer_index").cast(pl.Utf8), pl.lit(f" < {cfg.mentzer_cutoff:g}"),
        ]))
        .when(pl.col("rule_iron_deficiency")).then(pl.concat_str([
            pl.lit("Hb "), pl.col("hgb").cast(pl.Utf8), pl.lit(" < "),
            pl.col("hgb_threshold_used").cast(pl.Utf8), pl.lit("; MCV "),
            pl.col("mcv").cast(pl.Utf8), pl.lit(" < 80; Mentzer "),
            pl.col("mentzer_index").cast(pl.Utf8), pl.lit(f" >= {cfg.mentzer_cutoff:g}"),
        ]))
        .when(pl.col("rule_other_anemia")).then(pl.concat_str([
            pl.lit("Hb "), pl.col("hgb").cast(pl.Utf8), pl.lit(" below threshold; MCV "),
            pl.col("mcv").cast(pl.Utf8), pl.lit(" not microcytic - Mentzer not applicable"),
        ]))
        .when(pl.col("rule_inflammation")).then(pl.concat_str([
            pl.lit("WBC "), pl.col("wbc").cast(pl.Utf8), pl.lit(f" > {cfg.wbc_high_cutoff:g}"),
        ]))
        .otherwise(pl.lit("All evaluated indices within rule thresholds"))
    )

    # Independent order flags -> comma-separated recommendation list.
    tests = {
        "Hemoglobin Electrophoresis": pl.col("rule_thalassemia"),
        "Serum Ferritin Test": pl.col("rule_iron_deficiency"),
        "C-Reactive Protein (CRP)": pl.col("rule_inflammation"),
    }
    recommendation = pl.concat_str(
        [pl.when(cond).then(pl.lit(name)) for name, cond in tests.items()],
        separator=" + ", ignore_nulls=True,
    )

    return (
        df.with_columns(
            primary.alias("clinical_flag"),
            rationale.alias("flag_rationale"),
            recommendation.alias("_rec"),
        )
        .with_columns(
            pl.when(pl.col("_rec") == "").then(pl.lit("None")).otherwise(pl.col("_rec"))
            .alias("reflex_recommendation")
        )
        .drop("_rec")
    )


# ==============================================================================
# Stage 4 — Unit Economics / الاقتصاديات وتكامل الدفع
# ==============================================================================
def apply_pricing(df: pl.DataFrame, cfg: Config) -> pl.DataFrame:
    p = cfg.reflex_prices_iqd
    reflex_price = (
        pl.when(pl.col("rule_thalassemia")).then(p["Hemoglobin Electrophoresis"]).otherwise(0)
        + pl.when(pl.col("rule_iron_deficiency")).then(p["Serum Ferritin Test"]).otherwise(0)
        + pl.when(pl.col("rule_inflammation")).then(p["C-Reactive Protein (CRP)"]).otherwise(0)
    )
    return (
        df.with_columns(
            pl.lit(cfg.base_cbc_price_iqd, dtype=pl.Int64).alias("base_cbc_price_iqd"),
            reflex_price.cast(pl.Int64).alias("reflex_price_iqd"),
        )
        .with_columns(
            (pl.col("base_cbc_price_iqd") + pl.col("reflex_price_iqd"))
            .alias("total_potential_ticket_iqd"),
            pl.when(pl.col("reflex_price_iqd") > 0)
            .then(pl.lit(cfg.zaincash_action_label))
            .otherwise(pl.lit("Standard Clearance"))
            .alias("zaincash_gateway_action"),
        )
    )


# ==============================================================================
# Stage 5 — KPI Analytics / التحليلات ومؤشرات الأداء
# ==============================================================================
def build_kpis(df: pl.DataFrame) -> tuple[dict, pl.DataFrame]:
    total = df.height
    if total == 0:
        raise ValueError("No valid records to analyse.")

    flagged = df.filter(pl.col("reflex_recommendation") != "None").height
    base_rev = int(df["base_cbc_price_iqd"].sum())
    opt_rev = int(df["total_potential_ticket_iqd"].sum())

    headline = {
        "total_tests": total,
        "flagged_cases": flagged,
        "screening_yield_pct": round(flagged / total * 100, 2),
        "baseline_revenue_iqd": base_rev,
        "optimized_revenue_iqd": opt_rev,
        "basket_uplift_pct": round((opt_rev - base_rev) / base_rev * 100, 2),
    }

    summary = (
        df.group_by(["clinical_flag", "reflex_recommendation"])
        .agg(
            pl.len().alias("sample_count"),
            pl.col("hgb").mean().round(2).alias("avg_hgb"),
            pl.col("mentzer_index").mean().round(2).alias("avg_mentzer_index"),
            pl.col("base_cbc_price_iqd").sum().alias("baseline_revenue_iqd"),
            pl.col("total_potential_ticket_iqd").sum().alias("optimized_revenue_iqd"),
        )
        .with_columns(
            (pl.col("sample_count") / total * 100).round(2).alias("share_pct")
        )
        .sort("sample_count", descending=True)
    )
    return headline, summary


def print_report(h: dict, summary: pl.DataFrame) -> None:
    print("=== BioRefleX Analytics | تقرير الأداء ومحرك الاستدلال المخبري ===")
    print(f"إجمالي العينات الصالحة | Valid samples:             {h['total_tests']:,}")
    print(f"الحالات المحولة للفحص التكميلي | Flagged for reflex:   {h['flagged_cases']:,}")
    print(f"معدل الفرز الاستباقي | Screening yield:              {h['screening_yield_pct']}%")
    print(f"العائد الأساسي (CBC) | Baseline revenue:              {h['baseline_revenue_iqd']:,} IQD")
    print(f"العائد المحتمل | Potential revenue:                  {h['optimized_revenue_iqd']:,} IQD")
    print(f"نمو متوسط الفاتورة | Basket growth:                  +{h['basket_uplift_pct']}%")
    print("\n--- التوزيع التفصيلي | Detailed distribution ---")
    with pl.Config(tbl_rows=50, tbl_cols=-1, fmt_str_lengths=60):
        print(summary)


# ==============================================================================
# Orchestration / التشغيل
# ==============================================================================
def run(path: Path, out_dir: Path, cfg: Config | None = None) -> pl.DataFrame:
    cfg = cfg or Config()
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_cbc(path, cfg)
    df, rejected = validate(df, cfg)
    df = engineer_features(df, cfg)
    df = apply_reflex_rules(df, cfg)
    df = apply_pricing(df, cfg)

    headline, summary = build_kpis(df)
    print_report(headline, summary)

    # Persist artefacts (Parquet for the pipeline, CSV for humans).
    df.write_parquet(out_dir / "bioreflex_results.parquet")
    summary.write_csv(out_dir / "bioreflex_kpi_summary.csv")
    if rejected.height:
        rejected.write_csv(out_dir / "bioreflex_quarantine.csv")

    preview_cols = [
        "transaction_id", "hgb", "mcv", "rbc", "mentzer_index", "clinical_flag",
        "flag_rationale", "reflex_recommendation", "total_potential_ticket_iqd",
        "zaincash_gateway_action",
    ]
    print("\n--- عينة من السجلات المهندسة | Sample engineered records ---")
    with pl.Config(tbl_cols=-1, fmt_str_lengths=50):
        print(df.select(preview_cols).head(5))
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description="BioRefleX CBC reflex-testing pipeline")
    ap.add_argument("csv", type=Path, help="Path to CBC CSV file")
    ap.add_argument("--out-dir", type=Path, default=Path("output"))
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    run(args.csv, args.out_dir)


if __name__ == "__main__":
    main()
