"""Validation rules for the three Excel input workbooks. No database access, so it is easy to test."""
import pandas as pd

TARGET_COLS = ["month", "category", "target_revenue", "target_orders", "target_delivery_days"]
RULE_COLS = ["rule_id", "metric", "operator", "threshold", "severity", "recommended_action", "active"]
DICT_COLS = ["schema", "table", "column", "definition", "data_type", "owner", "sensitivity"]

OPERATORS = {">", ">=", "<", "<=", "="}
SEVERITIES = {"Low", "Medium", "High"}
SENSITIVITY = {"public", "internal", "restricted"}
METRICS = {
    "state.late_rate_pct", "state.avg_review", "seller.risk_score", "seller.cancel_rate_pct",
    "seller.late_rate_pct", "month.mom_pct", "month.target_attainment_pct",
    "kpi.repeat_rate_pct", "kpi.avg_delivery_days", "kpi.late_rate_pct", "pipeline.failed_tests",
}


def _columns(df, expected):
    missing = [c for c in expected if c not in df.columns]
    extra = [c for c in df.columns if c not in expected]
    errs = []
    if missing:
        errs.append(f"missing columns: {missing}")
    if extra:
        errs.append(f"unexpected columns: {extra}")
    return errs


def _blank(series):
    return series.isna() | (series.astype(str).str.strip() == "")


def validate_targets(df, valid_categories, first_month, last_month):
    errs = _columns(df, TARGET_COLS)
    if errs:
        return errs
    months = pd.to_datetime(df["month"], errors="coerce")
    for i in df.index[months.isna()]:
        errs.append(f"row {i + 2}: month is not a valid date")
    good = months.notna()
    for i in df.index[good & (months.dt.day != 1)]:
        errs.append(f"row {i + 2}: month must be the first day of a month")
    for i in df.index[good & ((months < pd.Timestamp(first_month)) | (months > pd.Timestamp(last_month)))]:
        errs.append(f"row {i + 2}: month is outside the analysis window")
    dup = df.assign(_m=months).duplicated(subset=["_m", "category"], keep=False)
    for i in df.index[dup]:
        errs.append(f"row {i + 2}: duplicate month and category")
    for i in df.index[~df["category"].isin(valid_categories)]:
        errs.append(f"row {i + 2}: unknown category '{df.at[i, 'category']}'")
    for col in ("target_revenue", "target_orders"):
        num = pd.to_numeric(df[col], errors="coerce")
        for i in df.index[num.isna() | (num <= 0)]:
            errs.append(f"row {i + 2}: {col} must be a number above 0")
    orders = pd.to_numeric(df["target_orders"], errors="coerce")
    for i in df.index[orders.notna() & (orders != orders.round())]:
        errs.append(f"row {i + 2}: target_orders must be a whole number")
    days = pd.to_numeric(df["target_delivery_days"], errors="coerce")
    for i in df.index[days.isna() | (days < 1) | (days > 60)]:
        errs.append(f"row {i + 2}: target_delivery_days must be between 1 and 60")
    return errs


def validate_rules(df):
    errs = _columns(df, RULE_COLS)
    if errs:
        return errs
    for i in df.index[_blank(df["rule_id"])]:
        errs.append(f"row {i + 2}: rule_id is empty")
    for i in df.index[df["rule_id"].duplicated(keep=False) & ~_blank(df["rule_id"])]:
        errs.append(f"row {i + 2}: duplicate rule_id '{df.at[i, 'rule_id']}'")
    for i in df.index[~df["metric"].isin(METRICS)]:
        errs.append(f"row {i + 2}: unknown metric '{df.at[i, 'metric']}'")
    for i in df.index[~df["operator"].isin(OPERATORS)]:
        errs.append(f"row {i + 2}: operator must be one of {sorted(OPERATORS)}")
    thr = pd.to_numeric(df["threshold"], errors="coerce")
    for i in df.index[thr.isna()]:
        errs.append(f"row {i + 2}: threshold must be a number")
    for i in df.index[~df["severity"].isin(SEVERITIES)]:
        errs.append(f"row {i + 2}: severity must be Low, Medium or High")
    for i in df.index[_blank(df["recommended_action"])]:
        errs.append(f"row {i + 2}: recommended_action is empty")
    for i in df.index[~df["active"].isin(["Y", "N"])]:
        errs.append(f"row {i + 2}: active must be Y or N")
    return errs


def validate_dictionary(df):
    errs = _columns(df, DICT_COLS)
    if errs:
        return errs
    key = df.duplicated(subset=["schema", "table", "column"], keep=False)
    for i in df.index[key]:
        errs.append(f"row {i + 2}: duplicate {df.at[i, 'schema']}.{df.at[i, 'table']}.{df.at[i, 'column']}")
    for col in ("schema", "table", "column", "data_type", "owner"):
        for i in df.index[_blank(df[col])]:
            errs.append(f"row {i + 2}: {col} is empty")
    for i in df.index[_blank(df["definition"]) | (df["definition"].astype(str).str.len() < 10)]:
        errs.append(f"row {i + 2}: definition is missing or too short")
    for i in df.index[~df["sensitivity"].isin(SENSITIVITY)]:
        errs.append(f"row {i + 2}: sensitivity must be public, internal or restricted")
    return errs