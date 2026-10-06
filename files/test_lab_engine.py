"""Run with:  python -m pytest -q -p no:cacheprovider"""
import pandas as pd
import pytest

from lab_engine import analyze, load_ranges, load_rules, match_columns, validate_condition


def run(rows, **kw):
    return analyze(pd.DataFrame(rows), **kw)


def test_sex_specific_hemoglobin():
    a = run({"Sex": ["M", "F"], "HGB": [12.5, 12.5]}, sex_col="Sex")
    assert a.annotated["hgb_status"].tolist() == ["Low", "Normal"]


def test_unknown_sex_uses_widest_range():
    a = run({"HGB": [12.5, 11.0]})  # no sex column -> female lower limit, male upper limit
    assert a.annotated["hgb_status"].tolist() == ["Normal", "Low"]


def test_critical_values_listed():
    a = run({"Potassium": [7.2, 4.0], "Glucose": [35, 90]})
    assert a.annotated["potassium_status"][0] == "Critical High"
    assert "potassium (high)" in a.annotated["critical_values"][0]
    assert "glucose (low)" in a.annotated["critical_values"][0]
    assert a.annotated["critical_values"][1] == ""


def test_unit_conversion_glucose_mmol():
    # 5.0 mmol/L is about 90 mg/dL (normal); read as mg/dL it would be critically low
    plain = run({"Glucose": [5.0]})
    conv = run({"Glucose": [5.0]}, alt_units={"glucose"})
    assert plain.annotated["glucose_status"][0] == "Critical Low"
    assert conv.annotated["glucose_status"][0] == "Normal"


def test_column_names_with_units_and_aliases():
    m = match_columns(["WBC (x10^9/L)", "Hemoglobin", "fasting glucose", "Name"], load_ranges())
    assert m == {"WBC (x10^9/L)": "wbc", "Hemoglobin": "hgb", "fasting glucose": "glucose"}


def test_cbc_rules_match_original_dashboard():
    a = run({"WBC": [7, 7, 15], "RBC": [5.5, 3.9, 4.8], "HGB": [9.0, 9.0, 14.0], "MCV": [65, 77, 88]},
            base_price=10_000)
    assert a.annotated["clinical_flag"].tolist() == [
        "Suspected Thalassemia Trait", "Suspected Iron Deficiency", "Suspected Systemic Inflammation"]
    assert a.annotated["total_ticket_value"].tolist() == [35_000, 25_000, 20_000]


def test_rule_with_absent_tests_is_inactive_not_crashing():
    a = run({"WBC": [7.0]})
    assert "Possible Liver Injury" in a.report["inactive_rules"]


def test_text_values_counted_not_crashing():
    a = run({"Glucose": ["90", "N/A", "abc"]})
    assert a.report["unparseable"] == {"Glucose": 2}


def test_age_outside_ranges_is_reported():
    a = run({"Age": [8], "HGB": [12.0]}, age_col="Age")
    assert a.annotated["hgb_status"][0] == "No range for age"
    assert a.report["no_range"] == {"hgb": 1}


def test_unsafe_rule_conditions_rejected():
    cols = ["hgb_low", "wbc_high"]
    for bad in ["__import__('os').system('x')", "hgb_low.__class__", "open('f')", "hgb_low and nope"]:
        with pytest.raises(ValueError):
            validate_condition(bad, cols)
    assert validate_condition("hgb_low and not wbc_high", cols) == {"hgb_low", "wbc_high"}


def test_bad_rule_reported_and_others_still_run():
    rules = pd.DataFrame({"priority": [1, 2], "rule_name": ["bad", "ok"],
                          "condition": ["os.system('x')", "wbc_high"],
                          "reflex_order": ["", "CRP"], "price_iqd": [0, 10_000]})
    a = run({"WBC": [15.0]}, rules=rules)
    assert "bad" in a.report["failed_rules"] and a.annotated["reflex_orders"][0] == "CRP"


def test_no_known_columns_gives_clear_error():
    with pytest.raises(ValueError, match="No known blood-test columns"):
        run({"foo": [1], "bar": [2]})


def test_same_reflex_from_two_rules_billed_once():
    rules = pd.DataFrame({"priority": [1, 2], "rule_name": ["a", "b"],
                          "condition": ["wbc_high", "crp_high"], "reflex_order": ["CRP", "CRP"],
                          "price_iqd": [10_000, 10_000]})
    a = run({"WBC": [15.0], "CRP": [40.0]}, rules=rules)
    assert a.annotated["add_on_revenue"][0] == 10_000
