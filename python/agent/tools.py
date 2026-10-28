"""Tools the model may call. Numbers come from these tools, never from the model."""
from __future__ import annotations

import re

from .config import ALLOWED_RELATIONS, MAX_ROWS_TO_MODEL
from .schema_context import read_kpi_doc, render_context
from .sql_guard import GuardError

_PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_METRICS = {"revenue", "orders", "customers", "aov"}  # columns of marts.monthly_sales

TOOL_SPECS = [
    {
        "name": "get_schema",
        "description": "List approved views and their columns. Call first when unsure which view or column to use.",
        "parameters": {
            "type": "object",
            "properties": {"view": {"type": "string", "description": "Optional view name to limit the output."}},
        },
    },
    {
        "name": "run_sql",
        "description": "Run ONE read-only SELECT on approved marts/ref views. Returns at most 200 rows.",
        "parameters": {
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "A single PostgreSQL SELECT statement."}},
            "required": ["sql"],
        },
    },
    {
        "name": "compare_periods",
        "description": "Compare a monthly metric between two months (format YYYY-MM). Metrics: revenue, orders, customers, aov.",
        "parameters": {
            "type": "object",
            "properties": {
                "metric": {"type": "string"},
                "period_a": {"type": "string", "description": "Earlier month, YYYY-MM"},
                "period_b": {"type": "string", "description": "Later month, YYYY-MM"},
            },
            "required": ["metric", "period_a", "period_b"],
        },
    },
    {
        "name": "top_n",
        "description": "Top or bottom N rows of an approved view ordered by one column.",
        "parameters": {
            "type": "object",
            "properties": {
                "view": {"type": "string"},
                "order_by": {"type": "string"},
                "n": {"type": "integer", "description": "1 to 50"},
                "descending": {"type": "boolean"},
            },
            "required": ["view", "order_by"],
        },
    },
    {
        "name": "explain_kpi",
        "description": "Return the written definition of a KPI (for example revenue, repeat rate, late rate).",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
]


class Tools:
    def __init__(self, db, schema: dict[str, list[dict]], kpi_text: str | None = None):
        self.db = db
        self.schema = schema
        self.kpi_text = read_kpi_doc() if kpi_text is None else kpi_text
        self.sql_used: list[str] = []
        self.rows_returned = 0
        self.blocked = 0
        self.succeeded = 0

    # ---- dispatcher -------------------------------------------------
    def call(self, name: str, args: dict) -> dict:
        handler = getattr(self, f"tool_{name}", None)
        if handler is None or name not in {s["name"] for s in TOOL_SPECS}:
            return {"ok": False, "error": f"Unknown tool '{name}'."}
        try:
            return handler(**(args or {}))
        except TypeError as exc:
            return {"ok": False, "error": f"Bad arguments: {exc}"}

    # ---- tools ------------------------------------------------------
    def tool_get_schema(self, view: str | None = None) -> dict:
        schema = {view: self.schema[view]} if view and view in self.schema else self.schema
        if view and view not in self.schema:
            return {"ok": False, "error": f"'{view}' is not an approved view."}
        self.succeeded += 1
        return {"ok": True, "schema": render_context(schema)}

    def tool_run_sql(self, sql: str) -> dict:
        try:
            result = self.db.run_guarded(sql)
        except GuardError as exc:
            self.blocked += 1
            return {"ok": False, "blocked": True, "error": str(exc)}
        except Exception as exc:  # database error (timeout, bad column, ...)
            return {"ok": False, "error": f"Database error: {str(exc)[:200]}"}
        return self._package(result)

    def tool_compare_periods(self, metric: str, period_a: str, period_b: str) -> dict:
        if metric not in _METRICS:
            return {"ok": False, "error": f"metric must be one of {sorted(_METRICS)}."}
        if not (_PERIOD.match(period_a or "") and _PERIOD.match(period_b or "")):
            return {"ok": False, "error": "Periods must look like 2018-03."}
        sql = (
            f"SELECT to_char(month_start, 'YYYY-MM') AS month, {metric} AS value "
            f"FROM monthly_sales WHERE to_char(month_start, 'YYYY-MM') IN ('{period_a}', '{period_b}') "
            f"ORDER BY month"
        )
        out = self.tool_run_sql(sql)
        if not out.get("ok"):
            return out
        values = {row[0]: row[1] for row in out["rows"]}
        if period_a in values and period_b in values and values[period_a]:
            a, b = float(values[period_a]), float(values[period_b])
            out["change"] = round(b - a, 4)
            out["change_pct"] = round(100.0 * (b - a) / a, 2)
        else:
            out["note"] = "One of the months has no data in the analysis window (Jan 2017 to Aug 2018)."
        return out

    def tool_top_n(self, view: str, order_by: str, n: int = 5, descending: bool = True) -> dict:
        if view not in self.schema:
            return {"ok": False, "error": f"'{view}' is not an approved view."}
        columns = {c["name"] for c in self.schema[view]}
        if order_by not in columns:
            return {"ok": False, "error": f"'{order_by}' is not a column of {view}."}
        n = max(1, min(int(n), 50))
        direction = "DESC" if descending else "ASC"
        schema_name = ALLOWED_RELATIONS[view]
        return self.tool_run_sql(
            f"SELECT * FROM {schema_name}.{view} ORDER BY {order_by} {direction} NULLS LAST LIMIT {n}"
        )

    def tool_explain_kpi(self, name: str) -> dict:
        needle = (name or "").strip().lower()
        if not needle:
            return {"ok": False, "error": "Give a KPI name."}
        hits = [p.strip() for p in re.split(r"\n\s*\n", self.kpi_text) if needle in p.lower()]
        if not hits:
            for view, cols in self.schema.items():
                for col in cols:
                    if needle in col["name"].lower() and col["definition"]:
                        hits.append(f"{view}.{col['name']}: {col['definition']}")
        if not hits:
            return {"ok": False, "error": f"No written definition found for '{name}'."}
        self.succeeded += 1
        return {"ok": True, "definition": "\n\n".join(hits)[:1500]}

    # ---- helpers ----------------------------------------------------
    def _package(self, result) -> dict:
        self.sql_used.append(result.sql)
        self.rows_returned += len(result.rows)
        self.succeeded += 1
        shown = result.rows[:MAX_ROWS_TO_MODEL]
        return {
            "ok": True,
            "sql": result.sql,
            "columns": result.columns,
            "rows": shown,
            "row_count": len(result.rows),
            "shown_rows": len(shown),
            "truncated": result.truncated or len(result.rows) > len(shown),
        }