"""General lab-result engine: reference ranges (sex/age aware), critical values,
unit conversion, editable pattern rules and reflex revenue.

Pure pandas/numpy so it is easy to test. Ranges and rules live in CSV files so a lab
can edit them without touching code. Starter values are DRAFTS and must be reviewed
by a qualified clinician before real-patient use.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RANGES_PATH = HERE / "reference_ranges.csv"
RULES_PATH = HERE / "rules.csv"

RANGE_COLUMNS = [
    "test", "aliases", "panel", "unit", "sex", "age_min", "age_max",
    "low", "high", "crit_low", "crit_high", "alt_unit", "alt_factor",
]
RULE_COLUMNS = ["priority", "rule_name", "condition", "reflex_order", "price_iqd"]
STATUSES = ("Critical Low", "Low", "Normal", "High", "Critical High")
KEYWORDS = {"and", "or", "not", "True", "False"}
DERIVED = ["mentzer_index"]


# ----------------------------------------------------------------- loading
def load_ranges(source=RANGES_PATH) -> pd.DataFrame:
    df = pd.read_csv(source) if not isinstance(source, pd.DataFrame) else source.copy()
    missing = [c for c in RANGE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Reference ranges are missing column(s): {', '.join(missing)}")
    df = df[RANGE_COLUMNS].dropna(subset=["test"]).copy()
    df["test"] = df["test"].map(norm_name)
    df["sex"] = df["sex"].fillna("any").astype(str).str.strip().str.lower()
    for c in ("age_min", "age_max", "low", "high", "crit_low", "crit_high", "alt_factor"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["age_min"] = df["age_min"].fillna(0)
    df["age_max"] = df["age_max"].fillna(120)
    return df[df["test"] != ""].reset_index(drop=True)


def load_rules(source=RULES_PATH) -> pd.DataFrame:
    df = pd.read_csv(source) if not isinstance(source, pd.DataFrame) else source.copy()
    missing = [c for c in RULE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Rules are missing column(s): {', '.join(missing)}")
    df = df[RULE_COLUMNS].copy()
    df["priority"] = pd.to_numeric(df["priority"], errors="coerce").fillna(999)
    df["price_iqd"] = pd.to_numeric(df["price_iqd"], errors="coerce").fillna(0)
    df["reflex_order"] = df["reflex_order"].fillna("").astype(str).str.strip()
    df = df.dropna(subset=["condition"])
    return df.sort_values("priority", kind="stable").reset_index(drop=True)


# ----------------------------------------------------------- column matching
def norm_name(name) -> str:
    s = str(name).lower()
    s = re.sub(r"[\(\[].*?[\)\]]", "", s)  # drop "(mg/dL)" style units
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def _alias_table(ranges: pd.DataFrame) -> dict[str, str]:
    table: dict[str, str] = {}
    for _, r in ranges.drop_duplicates("test").iterrows():
        table.setdefault(r["test"], r["test"])
        for a in str(r["aliases"]).split("|"):
            a = norm_name(a)
            if a and a != "nan":
                table.setdefault(a, r["test"])
    return table


def match_columns(columns, ranges: pd.DataFrame) -> dict[str, str]:
    """Map each uploaded column to a known test id (first column wins per test)."""
    table = _alias_table(ranges)
    result: dict[str, str] = {}
    used: set[str] = set()
    for col in columns:
        key = norm_name(col)
        tokens = key.split("_")
        found = None
        for k in range(len(tokens), 0, -1):  # "wbc_x10_9_l" -> "wbc"
            cand = "_".join(tokens[:k])
            if cand in table and (k == len(tokens) or len(cand) >= 3):
                found = table[cand]
                break
        if found and found not in used:
            result[col] = found
            used.add(found)
    return result


def find_column(columns, names) -> str | None:
    wanted = {norm_name(n) for n in names}
    for c in columns:
        if norm_name(c) in wanted:
            return c
    return None


# -------------------------------------------------------------- sex and age
def normalize_sex(series: pd.Series) -> np.ndarray:
    s = series.astype(str).str.strip().str.lower()
    out = np.full(len(s), "unknown", dtype=object)
    out[s.str.startswith(("m", "ذ")).to_numpy()] = "male"
    out[s.str.startswith(("f", "ان", "أن")).to_numpy()] = "female"
    return out


def _bounds(test_rows: pd.DataFrame, sex: np.ndarray, age: np.ndarray):
    n = len(sex)
    b = {k: np.full(n, np.nan) for k in ("low", "high", "crit_low", "crit_high")}
    covered = np.zeros(n, bool)
    covered_any = np.zeros(n, bool)
    spec = (test_rows["sex"] != "any").astype(int) + (
        (test_rows["age_min"] > 0) | (test_rows["age_max"] < 120)
    ).astype(int)
    for _, r in test_rows.iloc[np.argsort(spec.to_numpy(), kind="stable")].iterrows():
        age_ok = (age >= r["age_min"]) & (age <= r["age_max"])
        sex_ok = np.ones(n, bool) if r["sex"] == "any" else (sex == r["sex"])
        m = age_ok & sex_ok
        for k in b:
            b[k][m] = r[k]
        covered |= m
        if r["sex"] == "any":
            covered_any |= m
    # Unknown sex and only sex-specific rows: use the widest (union) range so we
    # never over-flag because a sex column is missing.
    for _, r in test_rows[test_rows["sex"] != "any"].iterrows():
        m = (sex == "unknown") & ~covered_any & (age >= r["age_min"]) & (age <= r["age_max"])
        if m.any():
            b["low"][m] = np.fmin(b["low"][m], r["low"])
            b["high"][m] = np.fmax(b["high"][m], r["high"])
            b["crit_low"][m] = np.fmin(b["crit_low"][m], r["crit_low"])
            b["crit_high"][m] = np.fmax(b["crit_high"][m], r["crit_high"])
            covered |= m
    return b, covered


def _status(values: np.ndarray, b: dict, covered: np.ndarray) -> np.ndarray:
    has = ~np.isnan(values)
    out = np.full(len(values), "", dtype=object)
    with np.errstate(invalid="ignore"):
        out[has & covered] = "Normal"
        out[has & covered & (values < b["low"])] = "Low"
        out[has & covered & (values > b["high"])] = "High"
        out[has & covered & (values < b["crit_low"])] = "Critical Low"
        out[has & covered & (values > b["crit_high"])] = "Critical High"
    out[has & ~covered] = "No range for age"
    return out


# ------------------------------------------------------------------- rules
def validate_condition(cond: str, columns) -> set[str]:
    """Only allow comparisons / and / or / not over known column names."""
    if not re.fullmatch(r"[A-Za-z0-9_\s<>=!().+\-*/]+", cond) or "__" in cond:
        raise ValueError("contains characters that are not allowed")
    idents = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", cond)) - KEYWORDS
    unknown = idents - set(columns)
    if unknown:
        raise ValueError(f"unknown name(s): {', '.join(sorted(unknown))}")
    stripped = re.sub(r"\b(and|or|not)\b", " ", cond)
    if re.search(r"[A-Za-z0-9_]\s*\(", stripped):
        raise ValueError("function calls are not allowed")
    return idents


# ---------------------------------------------------------------- analysis
@dataclass
class Analysis:
    annotated: pd.DataFrame
    summary: pd.DataFrame
    rules_summary: pd.DataFrame
    matched: pd.DataFrame
    report: dict


def analyze(
    df: pd.DataFrame,
    ranges: pd.DataFrame | None = None,
    rules: pd.DataFrame | None = None,
    sex_col: str | None = None,
    age_col: str | None = None,
    default_sex: str = "unknown",
    default_age: float = 30.0,
    alt_units: set[str] | None = None,
    base_price: float = 0.0,
) -> Analysis:
    ranges = load_ranges() if ranges is None else ranges
    rules = load_rules() if rules is None else rules
    alt_units = alt_units or set()
    n = len(df)
    df = df.reset_index(drop=True)

    colmap = match_columns([c for c in df.columns if c not in (sex_col, age_col)], ranges)
    if not colmap:
        raise ValueError(
            "No known blood-test columns were found. Expected names like WBC, HGB, Glucose, "
            "Creatinine, ALT, TSH... Download the template to see all supported tests."
        )

    sex = normalize_sex(df[sex_col]) if sex_col else np.full(n, default_sex, dtype=object)
    age = (
        pd.to_numeric(df[age_col], errors="coerce").fillna(default_age).to_numpy(float)
        if age_col else np.full(n, float(default_age))
    )

    report: dict = {
        "rows": n, "unparseable": {}, "no_range": {}, "unit_warnings": [],
        "inactive_rules": [], "failed_rules": {},
        "unmatched_columns": [c for c in df.columns if c not in colmap and c not in (sex_col, age_col)],
        "sex_source": sex_col or f"default ({default_sex})",
        "age_source": age_col or f"default ({default_age:g})",
    }

    work = pd.DataFrame(index=range(n))
    out = df.copy()
    status_cols: dict[str, np.ndarray] = {}
    matched_rows, summary_rows = [], []

    for col, test in colmap.items():
        trows = ranges[ranges["test"] == test]
        raw = df[col]
        vals = pd.to_numeric(raw, errors="coerce")
        bad = int((raw.notna() & vals.isna() & (raw.astype(str).str.strip() != "")).sum())
        if bad:
            report["unparseable"][col] = bad
        v = vals.to_numpy(float)
        unit = trows["unit"].iloc[0]
        if test in alt_units and trows["alt_factor"].notna().any():
            v = v * float(trows["alt_factor"].dropna().iloc[0])
        work[test] = v
        b, covered = _bounds(trows, sex, age)
        st = _status(v, b, covered)
        status_cols[test] = st
        out[f"{test}_status"] = st
        nr = int((st == "No range for age").sum())
        if nr:
            report["no_range"][test] = nr
        present = int((st != "").sum())
        crit = int(np.isin(st, ["Critical Low", "Critical High"]).sum())
        if present >= 5 and crit / present > 0.5:
            report["unit_warnings"].append(
                f"{col}: {crit} of {present} values are critical - check the unit selected for this column."
            )
        matched_rows.append({
            "your_column": col, "test": test, "panel": trows["panel"].iloc[0], "unit": unit,
            "converted_from": trows["alt_unit"].iloc[0] if test in alt_units else "",
        })
        summary_rows.append({
            "test": test, "panel": trows["panel"].iloc[0], "unit": unit, "n": present,
            "normal": int((st == "Normal").sum()),
            "low": int((st == "Low").sum()), "high": int((st == "High").sum()),
            "critical": crit,
            "pct_abnormal": round(100 * (present - int((st == "Normal").sum()) - nr) / present, 1) if present else 0.0,
        })

    # helper columns for rules: every known test gets _low/_high (False when absent)
    for test in ranges["test"].unique():
        st = status_cols.get(test)
        work[f"{test}_low"] = np.isin(st, ["Low", "Critical Low"]) if st is not None else False
        work[f"{test}_high"] = np.isin(st, ["High", "Critical High"]) if st is not None else False
    if "mcv" in work and "rbc" in work:
        with np.errstate(divide="ignore", invalid="ignore"):
            work["mentzer_index"] = np.where(work["rbc"] > 0, work["mcv"] / work["rbc"], np.nan)
    else:
        work["mentzer_index"] = np.nan

    # rules
    flag_lists = [[] for _ in range(n)]
    reflex_masks: dict[str, np.ndarray] = {}
    reflex_price: dict[str, float] = {}
    rule_rows = []
    first_flag = np.full(n, "Normal reference", dtype=object)
    assigned = np.zeros(n, bool)
    present_tests = set(colmap.values())
    for _, rule in rules.iterrows():
        name, cond = str(rule["rule_name"]), str(rule["condition"])
        try:
            idents = validate_condition(cond, work.columns)
        except ValueError as e:
            report["failed_rules"][name] = str(e)
            continue
        bases = {re.sub(r"_(low|high)$", "", i) for i in idents if i != "mentzer_index"}
        if "mentzer_index" in idents:
            bases |= {"mcv", "rbc"}
        if not (bases & present_tests):
            report["inactive_rules"].append(name)
            rule_rows.append({"rule_name": name, "matches": 0, "reflex_order": rule["reflex_order"], "revenue": 0.0})
            continue
        try:
            mask = work.eval(cond, engine="python")
            mask = pd.Series(mask).fillna(False).astype(bool).to_numpy()
            if len(mask) != n:
                raise ValueError("condition did not give one result per row")
        except Exception as e:  # noqa: BLE001 - report, don't crash the page
            report["failed_rules"][name] = f"{type(e).__name__}: {e}"
            continue
        for i in np.flatnonzero(mask):
            flag_lists[i].append(name)
        first_flag[mask & ~assigned] = name
        assigned |= mask
        rx = str(rule["reflex_order"]).strip()
        if rx:
            reflex_masks[rx] = reflex_masks.get(rx, np.zeros(n, bool)) | mask
            reflex_price.setdefault(rx, float(rule["price_iqd"]))
        rule_rows.append({
            "rule_name": name, "matches": int(mask.sum()), "reflex_order": rx,
            "revenue": float(rule["price_iqd"]) * int(mask.sum()) if rx else 0.0,
        })

    reflex_lists = [[] for _ in range(n)]
    add_on = np.zeros(n)
    for rx, m in reflex_masks.items():
        add_on += m * reflex_price[rx]
        for i in np.flatnonzero(m):
            reflex_lists[i].append(rx)

    status_matrix = pd.DataFrame(status_cols) if status_cols else pd.DataFrame(index=range(n))
    abnormal = status_matrix.isin(["Low", "High", "Critical Low", "Critical High"]).sum(axis=1)
    crit_mask = status_matrix.isin(["Critical Low", "Critical High"])
    crit_tests = [
        "; ".join(f"{t} ({status_matrix.at[i, t].split()[1].lower()})" for t in status_matrix.columns if crit_mask.at[i, t])
        for i in range(n)
    ]

    out.insert(0, "source_row", np.arange(2, n + 2))
    out["abnormal_count"] = abnormal.to_numpy()
    out["critical_values"] = crit_tests
    out["clinical_flag"] = first_flag
    out["all_flags"] = ["; ".join(f) for f in flag_lists]
    out["reflex_orders"] = ["; ".join(r) for r in reflex_lists]
    out["add_on_revenue"] = add_on
    out["total_ticket_value"] = add_on + float(base_price)

    return Analysis(
        annotated=out,
        summary=pd.DataFrame(summary_rows),
        rules_summary=pd.DataFrame(rule_rows),
        matched=pd.DataFrame(matched_rows),
        report=report,
    )
