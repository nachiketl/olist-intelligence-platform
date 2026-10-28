"""Runs guarded SQL as agent_ro (read-only, marts and ref only, 10 s timeout)
and writes run logs as agent_rw (append only)."""
from __future__ import annotations

import datetime as dt
import decimal
import json
from dataclasses import dataclass, field

from .config import MAX_ROWS, build_url
from .sql_guard import validate


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list]
    truncated: bool = False
    sql: str = ""


def _clean(value):
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return "<binary>"
    return value


class AgentDB:
    """Read-only access. Every query passes through the SQL guard first."""

    def __init__(self, engine=None):
        self._engine = engine

    @property
    def engine(self):
        if self._engine is None:
            from sqlalchemy import create_engine

            self._engine = create_engine(build_url("agent_ro"), pool_pre_ping=True)
        return self._engine

    def run_guarded(self, sql: str) -> QueryResult:
        safe_sql = validate(sql)  # raises GuardError if not allowed
        return self._execute(safe_sql)

    def internal(self, sql: str) -> list[dict]:
        """Fixed catalog queries written by us (never model text). Used for schema context."""
        with self.engine.connect() as conn:
            result = conn.exec_driver_sql(sql)
            keys = list(result.keys())
            return [dict(zip(keys, row)) for row in result.fetchall()]

    def execute_unchecked(self, sql: str) -> QueryResult:
        """TEST ONLY: skips the guard to prove the database role blocks it too."""
        return self._execute(sql)

    def _execute(self, sql: str) -> QueryResult:
        with self.engine.connect() as conn:
            # exec_driver_sql: no bind-parameter parsing, so ':' and '%' in text are left alone.
            result = conn.exec_driver_sql(sql)
            columns = list(result.keys())
            rows = result.fetchmany(MAX_ROWS + 1)
        truncated = len(rows) > MAX_ROWS
        rows = [[_clean(v) for v in row] for row in rows[:MAX_ROWS]]
        return QueryResult(columns=columns, rows=rows, truncated=truncated, sql=sql)


@dataclass
class RunRecord:
    run_id: str
    user_question: str
    status: str
    tools_called: list = field(default_factory=list)
    generated_sql: str = ""
    rows_returned: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    error: str | None = None


_INSERT_SQL = """
INSERT INTO agent.run_log
    (run_id, user_question, tools_called, generated_sql, status, rows_returned,
     tokens_in, tokens_out, cost_usd, duration_ms, error)
VALUES
    (CAST(:run_id AS uuid), :user_question, CAST(:tools_called AS jsonb), :generated_sql, :status,
     :rows_returned, :tokens_in, :tokens_out, :cost_usd, :duration_ms, :error)
"""


class RunLogger:
    """Append-only logging through agent_rw."""

    def __init__(self, engine=None):
        self._engine = engine

    @property
    def engine(self):
        if self._engine is None:
            from sqlalchemy import create_engine

            self._engine = create_engine(build_url("agent_rw"), pool_pre_ping=True)
        return self._engine

    @staticmethod
    def params(rec: RunRecord) -> dict:
        return {
            "run_id": rec.run_id,
            "user_question": rec.user_question,
            "tools_called": json.dumps(rec.tools_called, default=str),
            "generated_sql": rec.generated_sql,
            "status": rec.status,
            "rows_returned": rec.rows_returned,
            "tokens_in": rec.tokens_in,
            "tokens_out": rec.tokens_out,
            "cost_usd": rec.cost_usd,
            "duration_ms": rec.duration_ms,
            "error": rec.error,
        }

    def insert(self, conn, rec: RunRecord) -> None:
        from sqlalchemy import text

        conn.execute(text(_INSERT_SQL), self.params(rec))

    def write(self, rec: RunRecord) -> None:
        with self.engine.begin() as conn:
            self.insert(conn, rec)