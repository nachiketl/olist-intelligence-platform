"""Day 7 (part A): tests for the Excel inputs, the validators, the ref tables and the target views."""
import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python" / "etl"))
import excel_validation as ev  # noqa: E402

CATS = {"health_beauty", "Other"}
FIRST, LAST = "2017-01-01", "2018-08-01"


# ---------- 1. Validators accept good data and reject bad data (no database) ----------
def good_targets():
    return pd.DataFrame({"month": ["2017-01-01", "2017-02-01"], "category": ["health_beauty", "Other"],
                         "target_revenue": [1000.0, 2000.0], "target_orders": [10, 20], "target_delivery_days": [10.0, 10.0]})


def good_rules():
    return pd.DataFrame({"rule_id": ["R1", "R2"], "metric": ["seller.risk_score", "kpi.late_rate_pct"],
                         "operator": [">=", ">"], "threshold": [50, 10], "severity": ["High", "Medium"],
                         "recommended_action": ["Review the seller", "Review carriers"], "active": ["Y", "N"]})


def good_dictionary():
    return pd.DataFrame({"schema": ["core"], "table": ["dim_date"], "column": ["date"],
                         "definition": ["Calendar date of the row"], "data_type": ["date"],
                         "owner": ["Data Analytics"], "sensitivity": ["internal"]})


def test_good_files_pass():
    assert ev.validate_targets(good_targets(), CATS, FIRST, LAST) == []
    assert ev.validate_rules(good_rules()) == []
    assert ev.validate_dictionary(good_dictionary()) == []


@pytest.mark.parametrize("change,expected", [
    (lambda d: d.assign(month=["2017-01-15", "2017-02-01"]), "first day"),
    (lambda d: d.assign(month=["2016-01-01", "2017-02-01"]), "outside the analysis window"),
    (lambda d: d.assign(category=["not_a_category", "Other"]), "unknown category"),
    (lambda d: d.assign(target_revenue=[-5.0, 2000.0]), "target_revenue"),
    (lambda d: d.assign(target_orders=[10.5, 20]), "whole number"),
    (lambda d: d.assign(target_delivery_days=[0, 10.0]), "target_delivery_days"),
    (lambda d: pd.concat([d, d.iloc[[0]]], ignore_index=True), "duplicate"),
    (lambda d: d.drop(columns=["target_orders"]), "missing columns"),
])
def test_bad_targets_are_rejected(change, expected):
    errs = ev.validate_targets(change(good_targets()), CATS, FIRST, LAST)
    assert errs and any(expected in e for e in errs), errs


@pytest.mark.parametrize("change,expected", [
    (lambda d: d.assign(operator=["!=", ">"]), "operator"),
    (lambda d: d.assign(rule_id=["R1", "R1"]), "duplicate rule_id"),
    (lambda d: d.assign(metric=["bad.metric", "kpi.late_rate_pct"]), "unknown metric"),
    (lambda d: d.assign(threshold=["abc", 10]), "threshold"),
    (lambda d: d.assign(severity=["Critical", "Medium"]), "severity"),
    (lambda d: d.assign(active=["Maybe", "N"]), "active"),
    (lambda d: d.assign(recommended_action=["", "Review carriers"]), "recommended_action"),
])
def test_bad_rules_are_rejected(change, expected):
    errs = ev.validate_rules(change(good_rules()))
    assert errs and any(expected in e for e in errs), errs


@pytest.mark.parametrize("change,expected", [
    (lambda d: d.assign(definition=["short"]), "definition"),
    (lambda d: d.assign(sensitivity=["secret"]), "sensitivity"),
    (lambda d: pd.concat([d, d], ignore_index=True), "duplicate"),
    (lambda d: d.assign(owner=[""]), "owner"),
])
def test_bad_dictionary_is_rejected(change, expected):
    errs = ev.validate_dictionary(change(good_dictionary()))
    assert errs and any(expected in e for e in errs), errs


# ---------- 2. Excel files exist and are valid ---------------------------------------
@pytest.mark.parametrize("name", ["sales_targets.xlsx", "business_rules.xlsx", "data_dictionary.xlsx"])
def test_excel_file_exists_with_data_sheet(name):
    df = pd.read_excel(ROOT / "excel" / name, sheet_name="data")
    assert len(df) > 0


# ---------- 3. ref tables match the Excel files ----------------------------------------
def test_ref_tables_match_excel_row_counts(scalar):
    for name, table in [("sales_targets.xlsx", "sales_targets"), ("business_rules.xlsx", "business_rules"),
                        ("data_dictionary.xlsx", "data_dictionary")]:
        rows = len(pd.read_excel(ROOT / "excel" / name, sheet_name="data"))
        assert scalar(f"SELECT count(*) FROM ref.{table}") == rows, name


def test_latest_excel_loads_succeeded(scalar):
    assert scalar("""SELECT count(*) FROM (SELECT DISTINCT ON (file_name) file_name, status FROM audit.excel_load_log
                     ORDER BY file_name, id DESC) l WHERE status <> 'LOADED'""") == 0
    assert scalar("SELECT count(DISTINCT file_name) FROM audit.excel_load_log") == 3


def test_rules_use_known_metrics(scalar):
    allowed = "','".join(sorted(ev.METRICS))
    assert scalar(f"SELECT count(*) FROM ref.business_rules WHERE metric NOT IN ('{allowed}')") == 0


def test_rule_severities_and_operators_valid(scalar):
    assert scalar("SELECT count(*) FROM ref.business_rules WHERE severity NOT IN ('Low','Medium','High')") == 0
    assert scalar("SELECT count(*) FROM ref.business_rules WHERE operator NOT IN ('>','>=','<','<=','=')") == 0
    assert scalar("SELECT count(*) FROM ref.business_rules WHERE active") >= 1


def test_seller_rules_match_scorecard_tiers(scalar):
    # The seller tier thresholds in the Excel rules must equal the ones built into the scorecard (50 and 25).
    assert scalar("SELECT threshold FROM ref.business_rules WHERE rule_id = 'R003'") == 50
    assert scalar("SELECT threshold FROM ref.business_rules WHERE rule_id = 'R004'") == 25


# ---------- 4. Data dictionary covers the whole warehouse --------------------------------
def test_dictionary_covers_every_core_and_marts_column(engine):
    with engine.connect() as conn:
        db = {tuple(r) for r in conn.execute(text("""
            SELECT n.nspname, c.relname, a.attname FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname IN ('core','marts') AND c.relkind IN ('r','v','m') AND a.attnum > 0 AND NOT a.attisdropped"""))}
        doc = {tuple(r) for r in conn.execute(text("SELECT schema_name, table_name, column_name FROM ref.data_dictionary"))}
    assert db - doc == set(), f"columns without a definition: {sorted(db - doc)[:5]}"
    assert doc - db == set(), f"definitions for columns that no longer exist: {sorted(doc - db)[:5]}"


def test_restricted_columns_are_marked(scalar):
    assert scalar("SELECT count(*) FROM ref.data_dictionary WHERE column_name IN "
                  "('customer_unique_id','zip_prefix','lat','lng') AND sensitivity <> 'restricted'") == 0


# ---------- 5. Targets and actual versus target -----------------------------------------------
def test_targets_cover_the_analysis_window(scalar):
    assert scalar("SELECT count(DISTINCT month) FROM ref.sales_targets") == 20
    assert scalar("SELECT min(month) FROM ref.sales_targets").isoformat() == "2017-01-01"
    assert scalar("SELECT max(month) FROM ref.sales_targets").isoformat() == "2018-08-01"


def test_target_categories_are_class_a_or_other(scalar):
    assert scalar("""SELECT count(*) FROM ref.sales_targets t WHERE t.category <> 'Other' AND NOT EXISTS
                     (SELECT 1 FROM marts.category_pareto c WHERE c.category_en = t.category AND c.abc_class = 'A')""") == 0


def test_target_vs_actual_has_a_row_per_target(scalar):
    assert scalar("SELECT count(*) FROM marts.target_vs_actual") == scalar("SELECT count(*) FROM ref.sales_targets")


def test_actual_revenue_in_target_view_equals_kpi(scalar):
    a = float(scalar("SELECT sum(actual_revenue) FROM marts.target_vs_actual"))
    k = float(scalar("SELECT revenue FROM marts.kpi_summary"))
    assert abs(a - k) < 0.01


def test_attainment_is_calculated_correctly(scalar):
    assert scalar("SELECT count(*) FROM marts.target_vs_actual WHERE abs(attainment_pct - 100 * actual_revenue / target_revenue) > 0.06") == 0
    assert scalar("SELECT count(*) FROM marts.target_vs_actual WHERE abs(revenue_variance - (actual_revenue - target_revenue)) > 0.01") == 0


def test_illustrative_attainment_is_plausible(scalar):
    assert scalar("SELECT count(*) FROM marts.target_vs_actual WHERE attainment_pct NOT BETWEEN 80 AND 120") == 0


def test_monthly_target_rollup(scalar):
    assert scalar("SELECT count(*) FROM marts.target_vs_actual_monthly") == 20
    assert abs(float(scalar("SELECT sum(target_revenue) FROM marts.target_vs_actual_monthly"))
               - float(scalar("SELECT sum(target_revenue) FROM ref.sales_targets"))) < 0.01


# ---------- 6. Agent tables ------------------------------------------------------------------
@pytest.mark.parametrize("table", ["run_log", "insights", "action_queue", "eval_results"])
def test_agent_tables_exist(scalar, table):
    assert scalar(f"SELECT count(*) FROM information_schema.tables WHERE table_schema = 'agent' AND table_name = '{table}'") == 1


def test_action_queue_rejects_invalid_status(engine):
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            with pytest.raises(Exception):
                conn.execute(text("INSERT INTO agent.action_queue (recommended_action, status) VALUES ('x', 'executed')"))
        finally:
            trans.rollback()


def test_action_queue_defaults_to_pending(engine):
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("INSERT INTO agent.action_queue (recommended_action) VALUES ('test')"))
            status = conn.execute(text("SELECT status FROM agent.action_queue WHERE recommended_action = 'test'")).scalar()
            assert status == "pending"
        finally:
            trans.rollback()