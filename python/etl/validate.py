"""Run all data-quality tests and store the results in audit.test_results.

Usage (from the project root):  python python/etl/validate.py
"""
import os
import sys
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)


class Collector:
    def __init__(self):
        self.rows = []

    def pytest_runtest_logreport(self, report):
        if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
            self.rows.append((report.nodeid.split("::", 1)[-1], report.outcome, round(report.duration, 3)))


collector = Collector()
exit_code = pytest.main(["tests", "-q", "-p", "no:cacheprovider"], plugins=[collector])

engine = create_engine(os.environ["DATABASE_URL"])
run_id = str(uuid.uuid4())[:8]
with engine.begin() as conn:
    conn.execute(text("""CREATE TABLE IF NOT EXISTS audit.test_results (
        id serial PRIMARY KEY, run_id text, run_at timestamptz DEFAULT now(),
        test_name text, outcome text, seconds numeric)"""))
    for name, outcome, secs in collector.rows:
        conn.execute(text("INSERT INTO audit.test_results (run_id, test_name, outcome, seconds) "
                          "VALUES (:r, :n, :o, :s)"), dict(r=run_id, n=name, o=outcome, s=secs))

passed = sum(1 for _, o, _ in collector.rows if o == "passed")
print(f"\nRun {run_id}: {passed} passed, {len(collector.rows) - passed} not passed, saved to audit.test_results")
sys.exit(int(exit_code))