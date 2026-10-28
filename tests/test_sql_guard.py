"""SQL guard tests: no database, no API, cost nothing."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from agent.sql_guard import GuardError, check, validate  # noqa: E402

ALLOWED = [
    "SELECT revenue FROM marts.kpi_summary",
    "select * from kpi_summary",
    "SELECT state_code, late_rate_pct FROM state_delivery ORDER BY late_rate_pct DESC LIMIT 5",
    "SELECT * FROM ref.business_rules",
    "WITH t AS (SELECT month_start, revenue FROM marts.monthly_sales) SELECT * FROM t",
    "SELECT revenue FROM marts.monthly_sales UNION ALL SELECT revenue FROM marts.monthly_sales",
    "SELECT s.state_code, k.revenue FROM marts.state_delivery s CROSS JOIN marts.kpi_summary k",
    "SELECT to_char(month_start, 'YYYY-MM') AS m, revenue FROM monthly_sales WHERE revenue > 0;",
    "SELECT seller_key, risk_score FROM seller_scorecard ORDER BY risk_score DESC",
]

BLOCKED = [
    ("", "empty"),
    ("   ", "blank"),
    ("DROP TABLE marts.kpi_summary", "drop"),
    ("UPDATE ref.business_rules SET threshold = 1", "update"),
    ("DELETE FROM ref.business_rules", "delete"),
    ("INSERT INTO ref.business_rules VALUES (1)", "insert"),
    ("TRUNCATE ref.sales_targets", "truncate"),
    ("CREATE ROLE hacker LOGIN", "create role"),
    ("CREATE TABLE marts.x AS SELECT 1", "create table"),
    ("ALTER TABLE marts.kpi_summary ADD COLUMN x int", "alter"),
    ("SELECT 1; SELECT 2", "two statements"),
    ("SELECT revenue FROM kpi_summary; DROP TABLE kpi_summary", "stacked drop"),
    ("SELECT * FROM core.dim_customers", "core table"),
    ("SELECT * FROM core.fact_orders", "core fact"),
    ("SELECT * FROM raw.orders", "raw table"),
    ("SELECT * FROM staging.orders", "staging table"),
    ("SELECT * FROM audit.test_results", "audit table"),
    ("SELECT * FROM agent.run_log", "agent table"),
    ("SELECT * FROM orders", "unapproved bare name"),
    ("SELECT * FROM information_schema.tables", "information_schema"),
    ("SELECT * FROM pg_catalog.pg_user", "pg_catalog"),
    ("SELECT * FROM pg_roles", "pg_roles"),
    ("SELECT pg_sleep(30)", "pg_sleep"),
    ("SELECT pg_read_file('/etc/passwd')", "pg_read_file"),
    ("SELECT current_setting('server_version')", "current_setting"),
    ("SELECT set_config('statement_timeout', '0', false)", "set_config"),
    ("SELECT * FROM generate_series(1, 1000000)", "table function"),
    ("SELECT revenue FROM kpi_summary -- hidden", "line comment"),
    ("SELECT revenue /* x */ FROM kpi_summary", "block comment"),
    ("SELECT * INTO new_table FROM kpi_summary", "select into"),
    ("SELECT * FROM kpi_summary FOR UPDATE", "for update"),
    ("COPY kpi_summary TO '/tmp/x.csv'", "copy"),
    ("SET statement_timeout = 0", "set"),
    ("SELECT customer_unique_id FROM marts.customer_rfm", "restricted column"),
    ("SELECT lat, lng FROM marts.state_delivery", "restricted coordinates"),
    ("WITH d AS (DELETE FROM ref.business_rules RETURNING *) SELECT * FROM d", "writing CTE"),
    ("SELECT * FROM marts.kpi_summary, core.dim_date", "join to core"),
    ("SELECT * FROM ref.kpi_summary", "wrong schema for view"),
    ("not sql at all", "garbage"),
    ("SELECT " + "x" * 5000, "too long"),
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allowed_queries_pass(sql):
    result = check(sql)
    assert result.ok, result.reason
    assert "LIMIT" in result.sql.upper()


@pytest.mark.parametrize("sql,why", BLOCKED, ids=[b[1] for b in BLOCKED])
def test_blocked_queries_are_refused(sql, why):
    result = check(sql)
    assert not result.ok, f"should be blocked ({why}): {sql[:60]}"
    assert result.reason


def test_validate_raises_guard_error():
    with pytest.raises(GuardError):
        validate("DROP TABLE marts.kpi_summary")


def test_unqualified_view_gets_its_schema():
    assert "marts.kpi_summary" in validate("SELECT revenue FROM kpi_summary")
    assert "ref.business_rules" in validate("SELECT * FROM business_rules")


def test_limit_is_forced_when_missing():
    assert "LIMIT 200" in validate("SELECT * FROM marts.monthly_sales")


def test_small_limit_is_kept():
    out = validate("SELECT * FROM marts.monthly_sales LIMIT 5")
    assert "LIMIT 5" in out and "LIMIT 200" not in out


def test_huge_limit_is_reduced():
    out = validate("SELECT * FROM marts.monthly_sales LIMIT 100000")
    assert "LIMIT 200" in out and "100000" not in out


def test_cte_name_is_not_treated_as_a_table():
    assert check("WITH x AS (SELECT revenue FROM kpi_summary) SELECT * FROM x").ok