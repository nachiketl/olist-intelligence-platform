"""SQL guard: layer 1 of the three protection layers.

Allows exactly one read-only SELECT on approved marts/ref views, blocks dangerous
functions and comments, and forces a row limit. The database role (layer 2) and the
statement timeout (layer 3) still protect the data if this guard ever has a gap.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from .config import ALLOWED_RELATIONS, ALLOWED_SCHEMAS, MAX_ROWS, MAX_SQL_CHARS, RESTRICTED_COLUMNS

_SETOP = getattr(exp, "SetOperation", exp.Union)

_FORBIDDEN_NODE_NAMES = [
    "Insert", "Update", "Delete", "Drop", "Create", "Alter", "AlterTable", "Command",
    "Merge", "TruncateTable", "Copy", "Set", "Into", "Lock", "Pragma", "Use",
    "Grant", "Revoke", "Transaction", "Commit", "Rollback",
]
_FORBIDDEN_NODES = tuple(getattr(exp, n) for n in _FORBIDDEN_NODE_NAMES if hasattr(exp, n))

_FORBIDDEN_FUNCTIONS = {
    "set_config", "current_setting", "generate_series", "query_to_xml", "table_to_xml",
    "database_to_xml", "dblink", "dblink_exec", "version",
}
_FORBIDDEN_FUNCTION_PREFIXES = ("pg_", "lo_", "dblink")
_FUNCTION_REGEX = re.compile(r"\b(pg_[a-z_0-9]*|lo_[a-z_0-9]*|dblink[a-z_0-9]*)\s*\(", re.IGNORECASE)
_SYSTEM_SCHEMA_REGEX = re.compile(r"\b(information_schema|pg_catalog|pg_toast)\b", re.IGNORECASE)


class GuardError(ValueError):
    """Raised when a query is not allowed. The message is safe to show to the model."""


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    sql: str = ""
    reason: str = ""


def validate(sql: str) -> str:
    """Return a safe, schema-qualified SQL string with a forced LIMIT, or raise GuardError."""
    if not isinstance(sql, str) or not sql.strip():
        raise GuardError("Empty query.")
    if len(sql) > MAX_SQL_CHARS:
        raise GuardError(f"Query is longer than {MAX_SQL_CHARS} characters.")
    if "--" in sql or "/*" in sql or "*/" in sql:
        raise GuardError("SQL comments are not allowed.")
    if _FUNCTION_REGEX.search(sql):
        raise GuardError("System functions (pg_*, lo_*, dblink) are not allowed.")
    if _SYSTEM_SCHEMA_REGEX.search(sql):
        raise GuardError("System schemas are not allowed.")

    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except SqlglotError as exc:
        raise GuardError(f"Could not parse the query: {str(exc)[:150]}") from exc

    if len(statements) != 1:
        raise GuardError("Exactly one statement is allowed.")

    stmt = statements[0]
    while isinstance(stmt, exp.Subquery):
        stmt = stmt.this
    if not isinstance(stmt, (exp.Select, _SETOP)):
        raise GuardError("Only SELECT queries are allowed.")

    for node in stmt.walk():
        node = node[0] if isinstance(node, tuple) else node
        if isinstance(node, _FORBIDDEN_NODES):
            raise GuardError(f"Not allowed in a query: {type(node).__name__}.")

    cte_names = {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE)}

    for table in stmt.find_all(exp.Table):
        name = (table.name or "").lower()
        schema = (table.db or "").lower()
        if not name:
            raise GuardError("Table functions and unnamed sources are not allowed.")
        if table.catalog:
            raise GuardError("Database-qualified names are not allowed.")
        if not schema and name in cte_names:
            continue
        if schema and schema not in ALLOWED_SCHEMAS:
            raise GuardError(f"Schema '{schema}' is not allowed. Use only marts and ref views.")
        expected = ALLOWED_RELATIONS.get(name)
        if expected is None:
            raise GuardError(f"'{name}' is not an approved view.")
        if schema and schema != expected:
            raise GuardError(f"'{name}' lives in '{expected}', not '{schema}'.")
        if not schema:
            table.set("db", exp.to_identifier(expected))

    for func in stmt.find_all(exp.Func):
        fname = (func.name if isinstance(func, exp.Anonymous) else func.sql_name()).lower()
        if fname in _FORBIDDEN_FUNCTIONS or fname.startswith(_FORBIDDEN_FUNCTION_PREFIXES):
            raise GuardError(f"Function '{fname}' is not allowed.")

    for col in stmt.find_all(exp.Column):
        if col.name.lower() in RESTRICTED_COLUMNS:
            raise GuardError(f"Column '{col.name}' is restricted.")

    _force_limit(stmt)
    return stmt.sql(dialect="postgres")


def check(sql: str) -> GuardResult:
    """Non-raising version of validate(), handy for tests and logging."""
    try:
        return GuardResult(True, validate(sql))
    except GuardError as exc:
        return GuardResult(False, "", str(exc))


def _force_limit(stmt: exp.Expression) -> None:
    stmt.set("fetch", None)
    existing = stmt.args.get("limit")
    if existing is not None:
        try:
            if int(existing.expression.name) <= MAX_ROWS:
                return
        except (AttributeError, ValueError, TypeError):
            pass
    stmt.set("limit", exp.Limit(expression=exp.Literal.number(MAX_ROWS)))