import os, sys, time
from pathlib import Path
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()
engine = create_engine(os.environ["DATABASE_URL"])
path = Path(sys.argv[1])
sql = path.read_text(encoding="utf-8")

conn = engine.raw_connection()
try:
    start = time.time()
    cur = conn.cursor()
    cur.execute(sql)
    conn.commit()
    print(f"OK: {path.name} finished in {time.time() - start:.1f}s")
except Exception:
    conn.rollback()
    raise
finally:
    conn.close()