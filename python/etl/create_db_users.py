"""Give the database roles their passwords. Run once after sql/09_roles_and_permissions.sql:

    python python/etl/create_db_users.py

Missing passwords are generated and appended to .env (they are never printed or committed).
"""
import os
import secrets
from pathlib import Path

from dotenv import dotenv_values, load_dotenv
from sqlalchemy import create_engine

load_dotenv()
ENV = Path(".env")
ROLES = {"bi_ro": "BI_RO_PASSWORD", "agent_ro": "AGENT_RO_PASSWORD",
         "agent_rw": "AGENT_RW_PASSWORD", "approver_rw": "APPROVER_RW_PASSWORD"}

existing = dotenv_values(ENV)
passwords, new_lines = {}, []
for role, var in ROLES.items():
    pw = existing.get(var)
    if not pw:
        pw = secrets.token_urlsafe(24)
        new_lines.append(f"{var}={pw}")
    passwords[role] = pw

if new_lines:
    text_now = ENV.read_text(encoding="utf-8")
    with ENV.open("a", encoding="utf-8") as f:
        if text_now and not text_now.endswith("\n"):
            f.write("\n")
        f.write("\n".join(new_lines) + "\n")
    print(f"Added {len(new_lines)} new password(s) to .env (not shown).")

engine = create_engine(os.environ["DATABASE_URL"])
with engine.begin() as conn:
    for role, pw in passwords.items():
        conn.exec_driver_sql(f"ALTER ROLE {role} WITH LOGIN PASSWORD '{pw.replace(chr(39), chr(39) * 2)}'")
        print(f"{role}: login enabled")