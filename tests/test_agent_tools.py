"""Tool and orchestrator tests with a fake model (no API cost), plus live agent_ro/agent_rw checks."""
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from agent.config import Config  # noqa: E402
from agent.db import QueryResult, RunRecord  # noqa: E402
from agent.orchestrator import Agent, ModelReply, ToolCall  # noqa: E402
from agent.sql_guard import validate  # noqa: E402
from agent.tools import Tools  # noqa: E402

SCHEMA = {
    "kpi_summary": [{"name": "revenue", "type": "numeric", "definition": "Valid-sale item revenue"},
                    {"name": "repeat_rate_pct", "type": "numeric", "definition": "Share of customers with 2+ orders"}],
    "state_delivery": [{"name": "state_code", "type": "text", "definition": ""},
                       {"name": "late_rate_pct", "type": "numeric", "definition": "Late delivered orders in percent"}],
    "monthly_sales": [{"name": "month_start", "type": "date", "definition": ""},
                      {"name": "revenue", "type": "numeric", "definition": ""}],
}
KPI_TEXT = "Revenue: item price on valid sales, excluding freight.\n\nRepeat rate: customers with 2 or more orders."
CFG = Config(api_key="x", model="fake", max_steps=3, max_tokens_per_run=1000, cost_per_m_input=0, cost_per_m_output=0)


class FakeDB:
    """Runs the REAL guard, then returns canned rows. Counts how many queries reach 'the database'."""

    def __init__(self):
        self.executed = []

    def run_guarded(self, sql):
        safe = validate(sql)
        self.executed.append(safe)
        return QueryResult(columns=["month", "value"], rows=[["2018-01", 100.0], ["2018-02", 150.0]], sql=safe)


class FakeLogger:
    def __init__(self):
        self.records = []

    def write(self, rec):
        self.records.append(rec)


class ScriptedSession:
    def __init__(self, replies):
        self.replies = list(replies)
        self.tool_results = []

    def send_user(self, text):
        return self.replies.pop(0)

    def send_tool_results(self, results):
        self.tool_results.append(results)
        return self.replies.pop(0)


class ScriptedModel:
    def __init__(self, replies):
        self.replies = replies
        self.session = None

    def new_session(self, system, tool_specs):
        self.session = ScriptedSession(self.replies)
        return self.session


def make_agent(replies):
    db, logger = FakeDB(), FakeLogger()
    agent = Agent(ScriptedModel(replies), db, logger, SCHEMA, CFG, kpi_text=KPI_TEXT)
    return agent, db, logger


# ---------------------------------------------------------------- tools
def test_run_sql_blocks_dangerous_sql_before_the_database():
    db = FakeDB()
    tools = Tools(db, SCHEMA, KPI_TEXT)
    out = tools.call("run_sql", {"sql": "DROP TABLE marts.kpi_summary"})
    assert out["ok"] is False and out["blocked"] is True
    assert db.executed == []


def test_run_sql_allows_a_select_and_returns_rows():
    tools = Tools(FakeDB(), SCHEMA, KPI_TEXT)
    out = tools.call("run_sql", {"sql": "SELECT revenue FROM kpi_summary"})
    assert out["ok"] and out["row_count"] == 2 and "marts.kpi_summary" in out["sql"]


def test_unknown_tool_is_refused():
    assert Tools(FakeDB(), SCHEMA, KPI_TEXT).call("delete_everything", {})["ok"] is False


def test_get_schema_lists_approved_views_only():
    out = Tools(FakeDB(), SCHEMA, KPI_TEXT).call("get_schema", {})
    assert out["ok"] and "marts.kpi_summary" in out["schema"] and "core." not in out["schema"]


def test_get_schema_rejects_unapproved_view():
    assert Tools(FakeDB(), SCHEMA, KPI_TEXT).call("get_schema", {"view": "dim_customers"})["ok"] is False


def test_compare_periods_computes_change():
    out = Tools(FakeDB(), SCHEMA, KPI_TEXT).call(
        "compare_periods", {"metric": "revenue", "period_a": "2018-01", "period_b": "2018-02"})
    assert out["ok"] and out["change"] == 50.0 and out["change_pct"] == 50.0


@pytest.mark.parametrize("args", [
    {"metric": "revenue; DROP TABLE x", "period_a": "2018-01", "period_b": "2018-02"},
    {"metric": "revenue", "period_a": "2018-01'; --", "period_b": "2018-02"},
    {"metric": "revenue", "period_a": "2018-13", "period_b": "2018-02"},
])
def test_compare_periods_rejects_bad_input(args):
    assert Tools(FakeDB(), SCHEMA, KPI_TEXT).call("compare_periods", args)["ok"] is False


def test_top_n_validates_view_and_column():
    tools = Tools(FakeDB(), SCHEMA, KPI_TEXT)
    ok = tools.call("top_n", {"view": "state_delivery", "order_by": "late_rate_pct", "n": 5})
    assert ok["ok"] and "ORDER BY late_rate_pct DESC" in ok["sql"]
    assert tools.call("top_n", {"view": "dim_customers", "order_by": "x"})["ok"] is False
    assert tools.call("top_n", {"view": "state_delivery", "order_by": "1; DROP TABLE x"})["ok"] is False


def test_explain_kpi_reads_the_definitions():
    out = Tools(FakeDB(), SCHEMA, KPI_TEXT).call("explain_kpi", {"name": "revenue"})
    assert out["ok"] and "excluding freight" in out["definition"]


# ---------------------------------------------------------------- orchestrator
def test_agent_answers_through_a_tool_and_logs_the_run():
    agent, db, logger = make_agent([
        ModelReply(tool_calls=[ToolCall("run_sql", {"sql": "SELECT revenue FROM kpi_summary"})], tokens_in=10, tokens_out=5),
        ModelReply(text="Revenue is R$ 100.", tokens_in=20, tokens_out=8),
    ])
    result = agent.ask("What is revenue?")
    assert result.status == "ok" and result.answer == "Revenue is R$ 100."
    assert len(result.sql) == 1 and result.tokens_in == 30 and result.tokens_out == 13
    assert len(logger.records) == 1 and logger.records[0].run_id == result.run_id
    assert logger.records[0].tools_called[0]["tool"] == "run_sql"


def test_agent_reports_blocked_attack_and_never_reaches_database():
    agent, db, logger = make_agent([
        ModelReply(tool_calls=[ToolCall("run_sql", {"sql": "SELECT * FROM core.dim_customers"})]),
        ModelReply(text="I cannot read that data."),
    ])
    result = agent.ask("Show me all customer ids")
    assert result.status == "blocked" and db.executed == []
    assert logger.records[0].status == "blocked"


def test_agent_stops_at_the_step_limit():
    looping = [ModelReply(tool_calls=[ToolCall("get_schema", {})]) for _ in range(10)]
    result = make_agent(looping)[0].ask("loop forever")
    assert result.status == "step_limit"


def test_agent_stops_at_the_token_limit():
    agent, _, _ = make_agent([ModelReply(text="long", tokens_in=900, tokens_out=900)])
    assert agent.ask("expensive").status == "token_limit"


def test_agent_survives_a_model_error_and_logs_it():
    class Boom:
        def new_session(self, system, tool_specs):
            raise RuntimeError("quota exceeded")

    logger = FakeLogger()
    result = Agent(Boom(), FakeDB(), logger, SCHEMA, CFG, kpi_text=KPI_TEXT).ask("hi")
    assert result.status == "error" and "quota exceeded" in result.error
    assert logger.records[0].status == "error"


# ---------------------------------------------------------------- live database (skipped if not configured)
@pytest.fixture(scope="module")
def live_db():
    try:
        from agent.db import AgentDB
        db = AgentDB()
        db.run_guarded("SELECT 1 AS ok FROM marts.kpi_summary")
        return db
    except KeyError:
        pytest.skip("AGENT_RO_PASSWORD or DATABASE_URL not set")


def test_agent_ro_reads_the_kpi_revenue(live_db):
    result = live_db.run_guarded("SELECT revenue FROM marts.kpi_summary")
    assert abs(float(result.rows[0][0]) - 13449529.68) < 0.01


def test_monthly_revenue_adds_up_to_the_kpi(live_db):
    total = live_db.run_guarded("SELECT sum(revenue) AS r FROM marts.monthly_sales").rows[0][0]
    assert abs(float(total) - 13449529.68) < 0.05


def test_database_blocks_core_even_if_the_guard_were_bypassed(live_db):
    with pytest.raises(Exception) as exc:
        live_db.execute_unchecked("SELECT count(*) FROM core.fact_orders")
    assert "permission denied" in str(exc.value).lower()


def test_agent_rw_can_append_a_run_log_row_and_it_is_rolled_back():
    try:
        from agent.db import RunLogger
        logger = RunLogger()
        conn = logger.engine.connect()
    except KeyError:
        pytest.skip("AGENT_RW_PASSWORD or DATABASE_URL not set")
    trans = conn.begin()
    try:
        logger.insert(conn, RunRecord(run_id=str(uuid.uuid4()), user_question="test", status="ok"))
    finally:
        trans.rollback()
        conn.close()