import sys
from typing import Dict

import polars as pl


class CBCPipeline:
    """Clean Polars-only CBC pipeline implementing clinical rules and economics."""

    BASE_CBC_PRICE = 10_000
    COST_HB_ELECTROPHORESIS = 25_000
    COST_SERUM_FERRITIN = 15_000
    COST_CRP = 10_000

    def __init__(self, csv_path: str):
        self.csv_path = csv_path
        self.df: pl.DataFrame | None = None

    def load_and_standardize(self) -> pl.DataFrame:
        # Read with relaxed inference to avoid dtype crashes on mixed columns
        df = pl.read_csv(self.csv_path, infer_schema_length=10000, ignore_errors=True)

        # Standardize column names: strip, lowercase, replace spaces with underscores
        cols = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
        df.columns = cols

        # Map common aliases to canonical names
        alias_map = {
            "wbc": "wbc",
            "white_blood_cell": "wbc",
            "rbc": "rbc",
            "red_blood_cell": "rbc",
            "hgb": "hgb",
            "hemoglobin": "hgb",
            "mcv": "mcv",
        }
        rename_dict = {k: v for k, v in alias_map.items() if k in df.columns and k != v}
        if rename_dict:
            df = df.rename(rename_dict)

        self.df = df
        return df

    def sanitize_and_filter(self) -> pl.DataFrame:
        if self.df is None:
            raise RuntimeError("Call load_and_standardize() first")

        df = self.df

        # Coerce numeric-like columns to Float64 where present
        for c in ["rbc", "mcv", "hgb", "wbc"]:
            if c in df.columns:
                df = df.with_columns(pl.col(c).cast(pl.Float64))

        # Keep rows where hgb, rbc, mcv are present and rbc > 0
        required = [c for c in ["hgb", "rbc", "mcv"] if c in df.columns]
        df = df.drop_nulls(subset=required)
        if "rbc" in df.columns:
            df = df.filter(pl.col("rbc") > 0)

        self.df = df
        return df

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

    def summarize(self) -> Dict[str, object]:
        if self.df is None:
            raise RuntimeError("Run the pipeline before summarizing")

        df = self.df
        total = df.height

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
        pipeline.load_and_standardize()
        pipeline.sanitize_and_filter()
        pipeline.compute_indices_and_rules()
        pipeline.compute_economics()
        summary = pipeline.summarize()
    except Exception as e:
        print(f"Pipeline failed: {e}", file=sys.stderr)
        return 1

    # Print concise summary
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
    rc = main()
    sys.exit(rc)
