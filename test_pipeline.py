"""Run with:  pip install pytest  &&  pytest -q"""
import polars as pl
import pytest

from pipeline import CBCPipeline


def run(rows, **kw):
    p = CBCPipeline(pl.DataFrame(rows), **kw)
    df = p.run()
    return p, df


def test_thalassemia_pattern():
    _, df = run({"WBC": [7.0], "RBC": [5.5], "HGB": [9.0], "MCV": [65.0]})
    assert df["clinical_flag"][0] == "Suspected Thalassemia Trait"
    assert df["reflex_order"][0] == "Hb Electrophoresis"
    assert df["total_ticket_value"][0] == 35_000


def test_iron_deficiency_pattern():
    _, df = run({"WBC": [7.0], "RBC": [3.9], "HGB": [9.0], "MCV": [77.0]})
    assert df["clinical_flag"][0] == "Suspected Iron Deficiency"
    assert df["reflex_order"][0] == "Serum Ferritin"


def test_inflammation_and_normal():
    _, df = run({"WBC": [15.0, 7.0], "RBC": [4.8, 4.8], "HGB": [13.5, 13.5], "MCV": [88.0, 88.0]})
    assert df["reflex_order"].to_list() == ["CRP", "None"]


def test_missing_required_column_gives_clear_error():
    with pytest.raises(ValueError, match="WBC"):
        CBCPipeline(pl.DataFrame({"RBC": [4.0], "HGB": [12.0], "MCV": [80.0]})).run()


def test_implausible_rows_flagged_and_optionally_excluded():
    rows = {"WBC": [7.0, 7.0], "RBC": [4.5, 90.8], "HGB": [13.0, 13.0], "MCV": [85.0, 85.0]}
    p, df = run(rows)
    assert p.report["flagged_rows"] == 1 and df.height == 2
    p2, df2 = run(rows, exclude_flagged=True)
    assert df2.height == 1 and p2.report["excluded_flagged"] == 1


def test_text_cells_do_not_crash():
    p, df = run({"WBC": ["7", "7"], "RBC": ["4.5", "N/A"], "HGB": ["13", "13"], "MCV": ["85", "85"]})
    assert df.height == 1 and p.report["unparseable_values"] == 1


def test_bundled_dataset():
    p = CBCPipeline("diagnosed_cbc_data_v4.csv")
    p.run()
    assert p.report["rows_loaded"] == 1281
    assert p.report["flagged_rows"] > 0