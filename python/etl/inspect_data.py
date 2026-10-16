from pathlib import Path
import pandas as pd

for f in sorted(Path("data/raw").glob("*.csv")):
    df = pd.read_csv(f)
    print("=" * 70)
    print(f.name, "| rows, cols:", df.shape)
    print("Columns:", list(df.columns))
    nulls = df.isna().sum()
    nulls = nulls[nulls > 0]
    print("Nulls:", nulls.to_dict() if len(nulls) else "none")
    print("Fully duplicated rows:", int(df.duplicated().sum()))
    for c in df.columns:
        if "timestamp" in c or c.endswith("_date"):
            d = pd.to_datetime(df[c], errors="coerce")
            print(f"  {c}: {d.min()} -> {d.max()}")