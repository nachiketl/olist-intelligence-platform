"""Validate the three Excel workbooks and load them into the ref schema (all or nothing).

Usage (project root):  python python/etl/load_excel.py
If any file fails validation, nothing is loaded and the problems are listed.
"""
import hashlib
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

import excel_validation as ev

load_dotenv()
engine = create_engine(os.environ["DATABASE_URL"])
EXCEL = Path("excel")
FILES = ["sales_targets.xlsx", "business_rules.xlsx", "data_dictionary.xlsx"]

with engine.connect() as conn:
    cats = {r[0] for r in conn.execute(text("SELECT category_en FROM marts.category_pareto WHERE abc_class = 'A'"))} | {"Other"}
    first, last = conn.execute(text("SELECT min(month_start), max(month_start) FROM core.dim_date WHERE in_analysis_window")).one()

frames = {f: pd.read_excel(EXCEL / f, sheet_name="data") for f in FILES}
sha = {f: hashlib.sha256((EXCEL / f).read_bytes()).hexdigest() for f in FILES}
errors = {
    "sales_targets.xlsx": ev.validate_targets(frames["sales_targets.xlsx"], cats, first, last),
    "business_rules.xlsx": ev.validate_rules(frames["business_rules.xlsx"]),
    "data_dictionary.xlsx": ev.validate_dictionary(frames["data_dictionary.xlsx"]),
}


def log(conn, name, status, message):
    conn.execute(text("INSERT INTO audit.excel_load_log (file_name, rows_in_file, sha256, status, message) "
                      "VALUES (:f, :r, :s, :st, :m)"),
                 dict(f=name, r=len(frames[name]), s=sha[name], st=status, m=message))


if any(errors.values()):
    with engine.begin() as conn:
        for f in FILES:
            log(conn, f, "REJECTED", "; ".join(errors[f][:5]) if errors[f] else "not loaded because another file failed")
    for f, errs in errors.items():
        print(f"{f}: {'OK' if not errs else str(len(errs)) + ' problem(s)'}")
        for e in errs[:20]:
            print("   -", e)
    print("\nNothing was loaded. Fix the file(s) and run again.")
    sys.exit(1)

t = frames["sales_targets.xlsx"].copy()
t["month"] = pd.to_datetime(t["month"]).dt.date
r = frames["business_rules.xlsx"].copy()
r["active"] = r["active"].eq("Y")
d = frames["data_dictionary.xlsx"].rename(columns={"schema": "schema_name", "table": "table_name", "column": "column_name"})

with engine.begin() as conn:
    conn.execute(text("TRUNCATE ref.sales_targets, ref.business_rules, ref.data_dictionary"))
    t.to_sql("sales_targets", conn, schema="ref", if_exists="append", index=False, method="multi")
    r.to_sql("business_rules", conn, schema="ref", if_exists="append", index=False, method="multi")
    d.to_sql("data_dictionary", conn, schema="ref", if_exists="append", index=False, method="multi", chunksize=200)
    for f in FILES:
        log(conn, f, "LOADED", "validated and loaded")
        print(f"{f}: LOADED {len(frames[f])} rows")