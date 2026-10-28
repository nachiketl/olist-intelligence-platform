"""Builds the approved context the model may see: marts and ref views only,
restricted columns removed, definitions from ref.data_dictionary and kpi_definitions.md."""
from __future__ import annotations

from .config import ALLOWED_RELATIONS, RESTRICTED_COLUMNS, ROOT

KPI_DOC = ROOT / "docs" / "kpi_definitions.md"

_COLUMNS_SQL = """
SELECT n.nspname AS schema_name, c.relname AS view_name, a.attname AS column_name,
       format_type(a.atttypid, a.atttypmod) AS data_type
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname IN ('marts', 'ref')
  AND c.relkind IN ('r', 'v', 'm')
  AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY n.nspname, c.relname, a.attnum
"""


def _pick(row: dict, *names: str):
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return None


def load_schema(db) -> dict[str, list[dict]]:
    """{view_name: [{'name', 'type', 'definition'}]} for approved views, restricted columns removed."""
    definitions: dict[tuple[str, str], str] = {}
    try:
        for row in db.internal("SELECT * FROM ref.data_dictionary"):
            table = _pick(row, "table_name", "table")
            column = _pick(row, "column_name", "column")
            definition = _pick(row, "definition", "description")
            if table and column and definition:
                definitions[(str(table), str(column))] = str(definition)
    except Exception:  # context still works without definitions
        definitions = {}

    schema: dict[str, list[dict]] = {}
    for row in db.internal(_COLUMNS_SQL):
        view, column = row["view_name"], row["column_name"]
        if ALLOWED_RELATIONS.get(view) != row["schema_name"]:
            continue
        if column.lower() in RESTRICTED_COLUMNS:
            continue
        schema.setdefault(view, []).append(
            {"name": column, "type": row["data_type"], "definition": definitions.get((view, column), "")}
        )
    return schema


def read_kpi_doc(limit: int = 6000) -> str:
    if KPI_DOC.exists():
        return KPI_DOC.read_text(encoding="utf-8", errors="ignore")[:limit]
    return ""


def render_context(schema: dict[str, list[dict]], kpi_text: str = "") -> str:
    lines = ["Approved views (use these names; schema is added automatically):"]
    for view in sorted(schema):
        schema_name = ALLOWED_RELATIONS[view]
        lines.append(f"\n{schema_name}.{view}")
        for col in schema[view]:
            extra = f": {col['definition']}" if col["definition"] else ""
            lines.append(f"  - {col['name']} ({col['type']}){extra}")
    if kpi_text:
        lines.append("\nKPI definitions (authoritative):\n" + kpi_text)
    return "\n".join(lines)