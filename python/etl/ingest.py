import os, hashlib

from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
engine = create_engine(os.environ["DATABASE_URL"])
RAW = Path("data/raw")

with engine.begin() as c:
    for s in ["raw", "staging", "core", "marts", "audit", "agent"]:
        c.execute(text(f"CREATE SCHEMA IF NOT EXISTS {s}"))
    c.execute(text("""
        CREATE TABLE IF NOT EXISTS audit.load_log (
            id serial PRIMARY KEY, file_name text, table_name text,
            rows_in_file int, rows_loaded int, sha256 text,
            status text, loaded_at timestamptz DEFAULT now())"""))

for f in sorted(RAW.glob("*.csv")):
    table = f.stem.replace("olist_", "").replace("_dataset", "")
    sha = hashlib.sha256(f.read_bytes()).hexdigest()
    df = pd.read_csv(f, dtype=str)
    df.to_sql(table, engine, schema="raw", if_exists="replace",
              index=False, chunksize=5000, method="multi")
    with engine.begin() as c:
        loaded = c.execute(text(f"SELECT count(*) FROM raw.{table}")).scalar()
        status = "OK" if loaded == len(df) else "MISMATCH"
        c.execute(text("""INSERT INTO audit.load_log
            (file_name, table_name, rows_in_file, rows_loaded, sha256, status)
            VALUES (:f,:t,:a,:b,:s,:st)"""),
            dict(f=f.name, t=table, a=len(df), b=loaded, s=sha, st=status))
    print(f"{table:40s} file={len(df):>9,} loaded={loaded:>9,} {status}")

