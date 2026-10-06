import sys
from typing import Dict, Union

import polars as pl


class CBCPipeline:
    """Clean Polars-only CBC pipeline implementing clinical rules and economics."""

    BASE_CBC_PRICE = 10_000
    COST_HB_ELECTROPHORESIS = 25_000
    COST_SERUM_FERRITIN = 15_000
    COST_CRP = 10_000

    # Columns every uploaded file must contain (after name standardization).
    REQUIRED_COLUMNS = ("hgb", "rbc", "mcv", "wbc")
    NUMERIC_COLUMNS = ("rbc", "mcv", "hgb", "wbc", "hct", "mchc")

    # Physiologic plausibility limits: (column, low, high, label).
    # Values outside these are almost certainly entry/instrument errors.
    PLAUSIBLE_RANGES = (
        ("hgb", 3.0, 22.0, "HGB outside 3-22 g/dL"),
        ("rbc", 1.0, 9.0, "RBC outside 1-9 x10^12/L"),
        ("mcv", 50.0, 130.0, "MCV outside 50-130 fL"),
        ("wbc", 0.5, 100.0, "WBC outside 0.5-100 x10^9/L"),
        ("hct", 10.0, 65.0, "HCT outside 10-65 %"),
        ("mchc", 20.0, 45.0, "MCHC outside 20-45 g/dL"),
    )

    ALIAS_MAP = {
        "white_blood_cell": "wbc",
        "white_blood_cells": "wbc",
        "wbc_count": "wbc",
        "red_blood_cell": "rbc",
        "red_blood_cells": "rbc",
        "rbc_count": "rbc",
        "hb": "hgb",
        "hemoglobin": "hgb",
        "haemoglobin": "hgb",
        "hematocrit": "hct",
        "pcv": "hct",
    }

    def __init__(self, source: Union[str, pl.DataFrame], exclude_flagged: bool = False):
        """source: path to a CSV, or an already-loaded Polars DataFrame."""
        self.source = source
        self.exclude_flagged = exclude_flagged
        self.df: pl.DataFrame | None = None
        self.report: Dict[str, object] = {}

    # ------------------------------------------------------------------ load
    def load_and_standardize(self) -> pl.DataFrame:
        if isinstance(self.source, pl.DataFrame):
            df = self.source.clone()
        else:
            df = pl.read_csv(self.source, infer_schema_length=10000, ignore_errors=True)

        # Standardize column names: strip, lowercase, replace spaces with underscores
        df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

        # Map common aliases to canonical names (never overwrite an existing column)
        rename_dict = {
            k: v for k, v in self.ALIAS_MAP.items() if k in df.columns and v not in df.columns
        }
        if rename_dict:
            df = df.rename(rename_dict)

        missing = [c for c in self.REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            found = ", ".join(df.columns) or "none"
            raise ValueError(
                f"Missing required column(s): {', '.join(m.upper() for m in missing)}. "
                f"Columns found in the file: {found}."
            )

        # Spreadsheet row number (header = row 1) so users can find bad rows in their file
        if "source_row" not in df.columns:
            df = df.with_row_index(name="source_row", offset=2)

        self.report = {"rows_loaded": df.height}
        self.df = df
        return df

    # -------------------------------------------------------------- sanitize
    def sanitize_and_filter(self) -> pl.DataFrame:
        if self.df is None:
            raise RuntimeError("Call load_and_standardize() first")

        df = self.df

        # Coerce numeric columns; text like "N/A" becomes null instead of crashing
        unparseable = 0
        for c in self.NUMERIC_COLUMNS:
            if c in df.columns:
                nulls_before = df[c].null_count()
                df = df.with_columns(pl.col(c).cast(pl.Float64, strict=False))
                unparseable += df[c].null_count() - nulls_before

        # Reject rows missing a value the rules need, or with RBC <= 0
        required = ["hgb", "rbc", "mcv"]
        n0 = df.height
        df = df.drop_nulls(subset=required)
        rejected_missing = n0 - df.height

        n1 = df.height
        df = df.filter(pl.col("rbc") > 0)
        rejected_rbc = n1 - df.height

        # Flag (not silently drop) physiologically implausible values
        checks = [
            (label, ((pl.col(col) < lo) | (pl.col(col) > hi)).fill_null(False))
            for col, lo, hi, label in self.PLAUSIBLE_RANGES
            if col in df.columns
        ]
        flag_breakdown: Dict[str, int] = {}
        if checks and df.height > 0:
            counts = df.select(
                [expr.cast(pl.UInt32).sum().alias(label) for label, expr in checks]
            ).row(0)
            flag_breakdown = {
                label: int(n or 0) for (label, _), n in zip(checks, counts) if (n or 0) > 0
            }

        if checks:
            df = df.with_columns(
                pl.concat_str(
                    [
                        pl.when(expr).then(pl.lit(label)).otherwise(pl.lit(None, dtype=pl.Utf8))
                        for label, expr in checks
                    ],
                    separator="; ",
                    ignore_nulls=True,
                ).alias("data_quality_flag")
            ).with_columns(
                pl.when(pl.col("data_quality_flag").fill_null("") == "")
                .then(pl.lit(None, dtype=pl.Utf8))
                .otherwise(pl.col("data_quality_flag"))
                .alias("data_quality_flag")
            )
        else:
            df = df.with_columns(pl.lit(None, dtype=pl.Utf8).alias("data_quality_flag"))

        flagged_rows = int(df["data_quality_flag"].is_not_null().sum())

        excluded_flagged = 0
        if self.exclude_flagged and flagged_rows:
            df = df.filter(pl.col("data_quality_flag").is_null())
            excluded_flagged = flagged_rows

        self.report.update(
            {
                "rows_used": df.height,
                "rejected_missing": rejected_missing,
                "rejected_rbc_nonpositive": rejected_rbc,
                "unparseable_values": unparseable,
                "flagged_rows": flagged_rows,
                "flag_breakdown": flag_breakdown,
                "excluded_flagged": excluded_flagged,
                "wbc_missing": int(df["wbc"].null_count()) if df.height else 0,
            }
        )
        self.df = df
        return df

    # ----------------------------------------------------------------- rules
    def compute_indices_and_rules(self) -> pl.DataFrame:
        if self.df is None:
            raise RuntimeError("Call sanitize_and_filter() first")

        df = self.df.with_columns(
            (pl.col("mcv") / pl.col("rbc")).alias("mentzer_index"),
            (pl.col("hgb") < 12.0).alias("anemia_status"),
        )

        # Clinical flag and reflex order using nested when/then/otherwise
        df = df.with_columns(
            pl.when(pl.col("anemia_status") & (pl.col("mentzer_index") < 13))
            .then(pl.lit("Suspected Thalassemia Trait"))
            .when(pl.col("anemia_status") & (pl.col("mentzer_index") >= 13))
            .then(pl.lit("Suspected Iron Deficiency"))
            .when(pl.col("wbc") > 11)
            .then(pl.lit("Suspected Systemic Inflammation"))
            .otherwise(pl.lit("Normal reference"))
            .alias("clinical_flag"),

            # Reflex order: pick highest-priority single reflex using nested when
            pl.when(pl.col("anemia_status") & (pl.col("mentzer_index") < 13))
            .then(pl.lit("Hb Electrophoresis"))
            .when(pl.col("anemia_status") & (pl.col("mentzer_index") >= 13))
            .then(pl.lit("Serum Ferritin"))
            .when(pl.col("wbc") > 11)
            .then(pl.lit("CRP"))
            .otherwise(pl.lit("None"))
            .alias("reflex_order"),
        )

        self.df = df
        return df

    # ------------------------------------------------------------- economics
    def compute_economics(self) -> pl.DataFrame:
        if self.df is None:
            raise RuntimeError("Call compute_indices_and_rules() first")

        df = self.df.with_columns(
            pl.lit(self.BASE_CBC_PRICE).alias("base_price"),
            pl.when(pl.col("reflex_order") == "Hb Electrophoresis").then(pl.lit(self.COST_HB_ELECTROPHORESIS)).otherwise(
                pl.lit(0)
            )
            .alias("rev_hb_electrophoresis"),
            pl.when(pl.col("reflex_order") == "Serum Ferritin").then(pl.lit(self.COST_SERUM_FERRITIN)).otherwise(pl.lit(0)).alias(
                "rev_serum_ferritin"
            ),
            pl.when(pl.col("reflex_order") == "CRP").then(pl.lit(self.COST_CRP)).otherwise(pl.lit(0)).alias("rev_crp"),
        )

        df = df.with_columns(
            (pl.col("rev_hb_electrophoresis") + pl.col("rev_serum_ferritin") + pl.col("rev_crp")).alias("add_on_revenue")
        ).with_columns((pl.col("base_price") + pl.col("add_on_revenue")).alias("total_ticket_value"))

        self.df = df
        return df

    # --------------------------------------------------------------- summary
    def run(self) -> pl.DataFrame:
        """Run every stage in order and return the final DataFrame."""
        self.load_and_standardize()
        self.sanitize_and_filter()
        self.compute_indices_and_rules()
        return self.compute_economics()

    def summarize(self) -> Dict[str, object]:
        if self.df is None:
            raise RuntimeError("Run the pipeline before summarizing")

        df = self.df

        agg = df.select(
            [
                pl.len().alias("processed"),
                pl.col("anemia_status").cast(pl.UInt32).sum().alias("anemia_count"),
                (pl.col("clinical_flag") == "Suspected Thalassemia Trait").cast(pl.UInt32).sum().alias("thal_count"),
                (pl.col("clinical_flag") == "Suspected Iron Deficiency").cast(pl.UInt32).sum().alias("iron_count"),
                (pl.col("clinical_flag") == "Suspected Systemic Inflammation").cast(pl.UInt32).sum().alias("inflam_count"),
                pl.mean("mentzer_index").alias("mean_mentzer"),
                pl.col("add_on_revenue").sum().alias("total_add_on_revenue"),
                pl.col("total_ticket_value").sum().alias("total_expected_revenue"),
                pl.col("total_ticket_value").mean().alias("avg_ticket_value"),
            ]
        ).row(0)

        return {
            "processed_rows": int(agg[0]) if agg[0] is not None else 0,
            "anemia_count": int(agg[1]) if agg[1] is not None else 0,
            "thal_count": int(agg[2]) if agg[2] is not None else 0,
            "iron_count": int(agg[3]) if agg[3] is not None else 0,
            "inflam_count": int(agg[4]) if agg[4] is not None else 0,
            "mean_mentzer": float(agg[5]) if agg[5] is not None else None,
            "total_add_on_revenue": int(agg[6]) if agg[6] is not None else 0,
            "total_expected_revenue": int(agg[7]) if agg[7] is not None else 0,
            "avg_ticket_value": float(agg[8]) if agg[8] is not None else None,
        }


def main(csv_path: str = "diagnosed_cbc_data_v4.csv") -> int:
    pipeline = CBCPipeline(csv_path)
    try:
        pipeline.run()
        summary = pipeline.summarize()
    except Exception as e:
        print(f"Pipeline failed: {e}", file=sys.stderr)
        return 1

    rep = pipeline.report
    print("Data quality:")
    print(f"  Rows loaded: {rep['rows_loaded']}  used: {rep['rows_used']}")
    print(f"  Rejected (missing/invalid): {rep['rejected_missing'] + rep['rejected_rbc_nonpositive']}")
    print(f"  Flagged as implausible: {rep['flagged_rows']}")
    for label, n in rep["flag_breakdown"].items():
        print(f"    - {label}: {n}")

    print("Pipeline summary:")
    print(f"  Processed rows: {summary['processed_rows']}")
    print(f"  Anemia count: {summary['anemia_count']}")
    print(f"  Suspected Thalassemia: {summary['thal_count']}")
    print(f"  Suspected Iron Deficiency: {summary['iron_count']}")
    print(f"  Suspected Inflammation: {summary['inflam_count']}")
    if summary["mean_mentzer"] is not None:
        print(f"  Mean Mentzer: {summary['mean_mentzer']:.2f}")
    print(f"  Total add-on revenue (IQD): {summary['total_add_on_revenue']}")
    print(f"  Total expected revenue (IQD): {summary['total_expected_revenue']}")
    if summary["avg_ticket_value"] is not None:
        print(f"  Avg ticket value (IQD): {summary['avg_ticket_value']:.2f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())