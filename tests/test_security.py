"""Day 7 (part B): prove each database role can do its job and nothing more.

The tests log in as each role (passwords come from .env) and try allowed and forbidden actions.
Every attempt runs in a transaction that is rolled back, so nothing is ever changed.
"""
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
BASE = make_url(os.environ["DATABASE_URL"]) if "DATABASE_URL" in os.environ else None
ROLE_VARS = {"bi_ro": "BI_RO_PASSWORD", "agent_ro": "AGENT_RO_PASSWORD",
             "agent_rw": "AGENT_RW_PASSWORD", "approver_rw": "APPROVER_RW_PASSWORD"}


def make_engine(role):
    pw = os.environ.get(ROLE_VARS[role])
    if not pw:
        pytest.skip(f"{ROLE_VARS[role]} is not set in .env (run python python/etl/create_db_users.py)")
    return create_engine(BASE.set(username=role, password=pw))


@pytest.fixture(scope="module")
def bi_ro():
    return make_engine("bi_ro")


@pytest.fixture(scope="module")
def agent_ro():
    return make_engine("agent_ro")


@pytest.fixture(scope="module")
def agent_rw():
    return make_engine("agent_rw")


@pytest.fixture(scope="module")
def approver_rw():
    return make_engine("approver_rw")


def attempt(engine, sql):
    """Run one statement and always roll back. Returns (succeeded, value_or_error_text)."""
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            result = conn.execute(text(sql))
            return True, (result.scalar() if result.returns_rows else None)
        except Exception as exc:  # noqa: BLE001
            return False, str(getattr(exc, "orig", exc)).lower()
        finally:
            trans.rollback()


def assert_denied(engine, sql):
    ok, msg = attempt(engine, sql)
    assert not ok, f"should have been denied but succeeded: {sql}"
    assert "permission denied" in msg or "read-only" in msg or "must be owner" in msg, msg


def assert_allowed(engine, sql):
    ok, msg = attempt(engine, sql)
    assert ok, f"should have worked: {sql} -> {msg}"


# ---------- 1. The roles themselves ----------------------------------------------------
@pytest.mark.parametrize("role", ["bi_ro", "agent_ro", "agent_rw", "approver_rw"])
def test_role_has_no_dangerous_attributes(scalar, role):
    assert scalar(f"SELECT count(*) FROM pg_roles WHERE rolname = '{role}' AND NOT rolsuper AND NOT rolcreatedb "
                  f"AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls") == 1


def test_database_is_closed_to_public(scalar):
    assert scalar("SELECT has_database_privilege('public', current_database(), 'CONNECT')") is False


def test_secrets_are_not_in_git():
    gitignore = (ROOT / ".gitignore").read_text()
    assert ".env" in gitignore
    for name in ("create_db_users.py", "09_roles_and_permissions.sql"):
        path = next(ROOT.rglob(name))
        assert "PASSWORD '" not in path.read_text().replace("WITH LOGIN PASSWORD '{pw", "")


# ---------- 2. agent_ro: reads marts and approved context only -----------------------------
@pytest.mark.parametrize("sql", [
    "SELECT revenue FROM marts.kpi_summary",
    "SELECT count(*) FROM marts.monthly_sales",
    "SELECT count(*) FROM marts.customer_rfm",
    "SELECT count(*) FROM marts.target_vs_actual",
    "SELECT count(*) FROM ref.data_dictionary",
    "SELECT count(*) FROM ref.business_rules",
])
def test_agent_ro_can_read_marts_and_context(agent_ro, sql):
    assert_allowed(agent_ro, sql)


@pytest.mark.parametrize("table", ["raw.orders", "staging.orders", "core.fact_orders", "core.dim_customers",
                                   "audit.load_log", "audit.test_results", "agent.run_log", "agent.action_queue"])
def test_agent_ro_cannot_read_anything_else(agent_ro, table):
    assert_denied(agent_ro, f"SELECT count(*) FROM {table}")


@pytest.mark.parametrize("sql", [
    "CREATE TABLE marts.evil (a int)",
    "DROP VIEW marts.kpi_summary",
    "TRUNCATE ref.sales_targets",
    "UPDATE ref.business_rules SET threshold = 1",
    "DELETE FROM ref.sales_targets",
    "INSERT INTO agent.run_log (user_question) VALUES ('x')",
    "ALTER TABLE ref.business_rules ADD COLUMN x int",
    "CREATE TEMP TABLE scratch (a int)",
    "CREATE ROLE intruder",
    "GRANT SELECT ON ref.business_rules TO public",
])
def test_agent_ro_cannot_change_anything(agent_ro, sql):
    assert_denied(agent_ro, sql)


def test_agent_ro_limits(agent_ro):
    assert attempt(agent_ro, "SHOW statement_timeout") == (True, "10s")
    assert attempt(agent_ro, "SHOW default_transaction_read_only") == (True, "on")
    assert attempt(agent_ro, "SHOW search_path")[1] == "marts, ref"


# ---------- 3. agent_rw: can only append to the agent log tables -----------------------------
@pytest.mark.parametrize("sql", [
    "INSERT INTO agent.run_log (user_question, status) VALUES ('why did reviews fall', 'ok')",
    "INSERT INTO agent.insights (kpi, severity, insight_text) VALUES ('late_rate', 'High', 'test')",
    "INSERT INTO agent.action_queue (recommended_action, rationale) VALUES ('review seller', 'test')",
    "INSERT INTO agent.eval_results (question_id, passed) VALUES ('Q1', true)",
    "SELECT count(*) FROM agent.run_log",
])
def test_agent_rw_can_log(agent_rw, sql):
    assert_allowed(agent_rw, sql)


@pytest.mark.parametrize("sql", [
    "SELECT count(*) FROM marts.kpi_summary",
    "SELECT count(*) FROM ref.business_rules",
    "SELECT count(*) FROM core.fact_orders",
    "SELECT count(*) FROM raw.orders",
    "UPDATE agent.action_queue SET status = 'approved'",
    "DELETE FROM agent.run_log",
    "TRUNCATE agent.run_log",
    "INSERT INTO ref.business_rules VALUES ('X','kpi.late_rate_pct','>',1,'Low','x',true)",
    "CREATE TABLE agent.evil (a int)",
])
def test_agent_rw_cannot_do_anything_else(agent_rw, sql):
    assert_denied(agent_rw, sql)


def test_agent_cannot_approve_its_own_actions(agent_rw, agent_ro):
    # Neither agent account can change the status of a recommended action.
    assert_denied(agent_rw, "UPDATE agent.action_queue SET status = 'approved', reviewed_by = 'agent'")
    assert_denied(agent_ro, "UPDATE agent.action_queue SET status = 'approved'")


# ---------- 4. approver_rw: humans change only the review columns --------------------------------
@pytest.fixture()
def one_action(engine):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO agent.action_queue (rule_id, recommended_action) VALUES ('TEST', 'security test row')"))
    yield
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM agent.action_queue WHERE rule_id = 'TEST'"))


def test_approver_can_review_an_action(approver_rw, one_action):
    assert_allowed(approver_rw, "UPDATE agent.action_queue SET status = 'approved', reviewed_by = 'analyst', "
                                "reviewed_at = now() WHERE rule_id = 'TEST'")


@pytest.mark.parametrize("sql", [
    "UPDATE agent.action_queue SET recommended_action = 'changed' WHERE rule_id = 'TEST'",
    "UPDATE agent.action_queue SET rule_id = 'OTHER' WHERE rule_id = 'TEST'",
    "DELETE FROM agent.action_queue WHERE rule_id = 'TEST'",
    "INSERT INTO agent.action_queue (recommended_action) VALUES ('forged')",
    "SELECT count(*) FROM marts.kpi_summary",
    "SELECT count(*) FROM agent.run_log",
])
def test_approver_cannot_do_more(approver_rw, one_action, sql):
    assert_denied(approver_rw, sql)


def test_approver_cannot_set_an_invalid_status(approver_rw, one_action):
    ok, msg = attempt(approver_rw, "UPDATE agent.action_queue SET status = 'executed' WHERE rule_id = 'TEST'")
    assert not ok and "check constraint" in msg


# ---------- 5. bi_ro: Power BI reads the model and results, never raw data ---------------------------
@pytest.mark.parametrize("sql", [
    "SELECT count(*) FROM core.fact_orders",
    "SELECT count(*) FROM core.dim_customers",
    "SELECT revenue FROM marts.kpi_summary",
    "SELECT count(*) FROM ref.sales_targets",
    "SELECT count(*) FROM audit.test_results",
    "SELECT count(*) FROM audit.dq_issues",
    "SELECT count(*) FROM agent.insights",
    "SELECT count(*) FROM agent.action_queue",
])
def test_bi_ro_can_read_what_reports_need(bi_ro, sql):
    assert_allowed(bi_ro, sql)


@pytest.mark.parametrize("table", ["raw.orders", "raw.customers", "staging.orders", "agent.run_log"])
def test_bi_ro_cannot_read_raw_staging_or_prompts(bi_ro, table):
    assert_denied(bi_ro, f"SELECT count(*) FROM {table}")


@pytest.mark.parametrize("sql", [
    "UPDATE core.fact_orders SET item_revenue = 0",
    "DELETE FROM core.fact_order_items",
    "INSERT INTO ref.business_rules VALUES ('X','kpi.late_rate_pct','>',1,'Low','x',true)",
    "DROP TABLE core.dim_date",
    "UPDATE agent.action_queue SET status = 'approved'",
])
def test_bi_ro_cannot_change_anything(bi_ro, sql):
    assert_denied(bi_ro, sql)


# ---------- 6. New objects get the right access automatically ---------------------------------------------
def test_default_privileges_cover_rebuilt_marts(scalar):
    for role in ("bi_ro", "agent_ro"):
        assert scalar(f"""SELECT count(*) FROM pg_default_acl d JOIN pg_namespace n ON n.oid = d.defaclnamespace
                          WHERE n.nspname = 'marts' AND d.defaclobjtype = 'r'
                          AND d.defaclacl::text LIKE '%{role}=r/%'""") == 1


def test_agent_ro_cannot_see_core_even_through_default_privileges(scalar):
    assert scalar("SELECT count(*) FROM pg_default_acl d JOIN pg_namespace n ON n.oid = d.defaclnamespace "
                  "WHERE n.nspname IN ('core','raw','staging') AND d.defaclacl::text LIKE '%agent_ro=%'") == 0