"""Create the three Excel input workbooks in the excel folder.

Run once from the project root:  python python/etl/make_excel_inputs.py
Then edit the files in Excel and load them with:  python python/etl/load_excel.py
Targets are ILLUSTRATIVE (invented by a documented rule), not real company targets.
"""
import math
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()
engine = create_engine(os.environ["DATABASE_URL"])
OUT = Path("excel")
OUT.mkdir(exist_ok=True)


def save(df, name, about):
    with pd.ExcelWriter(OUT / name, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name="data", index=False)
        pd.DataFrame({"about": about}).to_excel(xw, sheet_name="about", index=False)
        for sheet in ("data", "about"):
            ws = xw.sheets[sheet]
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(max(len(str(c.value or "")) for c in col) + 2, 70)
    print(f"wrote {name}: {len(df)} rows")


# ---------- 1. sales targets (illustrative) ---------------------------------
act = pd.read_sql("""
    WITH cat AS (SELECT category_en, CASE WHEN abc_class = 'A' THEN category_en ELSE 'Other' END AS grp
                 FROM marts.category_pareto)
    SELECT i.month_start AS month, c.grp AS category, sum(i.price) AS revenue, count(DISTINCT i.order_id) AS orders
    FROM marts.v_sales_items i JOIN cat c USING (category_en)
    GROUP BY 1, 2 ORDER BY 1, 2""", engine)
months = sorted(act["month"].unique())
pos = {m: i for i, m in enumerate(months)}
factor = act["month"].map(lambda m: 1.03 + 0.06 * math.sin(pos[m] * 0.9))
targets = pd.DataFrame({
    "month": act["month"],
    "category": act["category"],
    "target_revenue": ((act["revenue"].astype(float) * factor) / 10).round() * 10,
    "target_orders": (act["orders"] * factor).round().astype(int),
    "target_delivery_days": 10.0,
})
save(targets, "sales_targets.xlsx", [
    "ILLUSTRATIVE targets. They are not real company targets.",
    "Rule: target = actual x (1.03 + 0.06 x sin(0.9 x month_index)), so attainment varies between about 92 and 103 percent.",
    "Categories: the 18 class A categories (Pareto) plus 'Other'. Delivery target: 10 days for every row.",
    "Replace with real targets when available. Keep the column names and the sheet name 'data'."])

# ---------- 2. business rules -------------------------------------------------
rules = pd.DataFrame([
    ("R001", "state.late_rate_pct", ">", 12, "High", "Review carrier performance and delivery estimates in the affected state", "Y"),
    ("R002", "state.avg_review", "<", 4.0, "Medium", "Investigate review drivers (delays, product issues) in the state", "Y"),
    ("R003", "seller.risk_score", ">=", 50, "High", "Put the seller on performance review", "Y"),
    ("R004", "seller.risk_score", ">=", 25, "Medium", "Monitor the seller weekly", "Y"),
    ("R005", "seller.cancel_rate_pct", ">", 5, "High", "Contact the seller about cancellations and stock accuracy", "Y"),
    ("R006", "month.mom_pct", "<", -10, "Medium", "Investigate the revenue drop by category and state", "Y"),
    ("R007", "month.target_attainment_pct", "<", 90, "Medium", "Review the sales plan for the month and category", "Y"),
    ("R008", "kpi.repeat_rate_pct", "<", 5, "Low", "Launch retention campaigns for new and lapsed high-value customers", "Y"),
    ("R009", "kpi.avg_delivery_days", ">", 15, "Medium", "Review logistics capacity and carrier mix", "Y"),
    ("R010", "pipeline.failed_tests", ">", 0, "High", "Stop the dashboard refresh and fix data quality before publishing", "Y"),
    ("R011", "seller.late_rate_pct", ">", 30, "Medium", "Ask the seller for a delivery improvement plan", "N"),
], columns=["rule_id", "metric", "operator", "threshold", "severity", "recommended_action", "active"])
save(rules, "business_rules.xlsx", [
    "Thresholds used for alerts and recommendations by SQL, Power BI and the AI agent.",
    "operator: > >= < <= =    severity: Low, Medium, High    active: Y or N",
    "When several rules match, the highest severity is used. R011 is inactive as an example."])

# ---------- 3. data dictionary -------------------------------------------------
DEFINITIONS = {
    "abc_class": "Pareto class: A = categories making the first 80 percent of revenue, B = next 15 percent, C = the rest",
    "active_customers": "Customers from the cohort with a valid order in the given month",
    "actual_orders": "Distinct valid orders in the month and category group",
    "actual_revenue": "Item revenue of valid sales in BRL, excluding freight",
    "answer_date_key": "Date key (YYYYMMDD) when the seller answered the review",
    "aov": "Average order value: revenue divided by orders, in BRL",
    "approval_hours": "Hours between purchase and payment approval",
    "approved_date_key": "Date key (YYYYMMDD) of order approval",
    "attainment_pct": "Actual revenue as a percent of target revenue",
    "avg_delay_days": "Average days delivered after (positive) or before (negative) the estimated date",
    "avg_delivery_days": "Average days from purchase to delivery for delivered orders",
    "avg_freight": "Average freight per order in BRL",
    "avg_installments": "Average number of payment installments",
    "avg_review": "Average review score from 1 to 5",
    "cancel_rate_pct": "Percent of the seller's orders that were canceled or unavailable",
    "carrier_date_key": "Date key (YYYYMMDD) when the order was handed to the carrier",
    "category": "Category group used for targets: a class A category or 'Other'",
    "category_en": "Product category in English",
    "category_pt": "Product category in Portuguese as in the source",
    "city": "City name in lower case",
    "cohort": "Cohort label: month of first valid purchase as YYYY-MM",
    "cohort_month": "First day of the cohort month",
    "cohort_size": "Customers whose first valid order was in the cohort month",
    "cumulative_pct": "Running total of share_pct with categories ordered by revenue",
    "customer_key": "Surrogate key of the customer (a person); -1 means Unknown",
    "customer_unique_id": "Source identifier of a person across all their orders",
    "customers": "Distinct customers (people)",
    "date": "Calendar date",
    "date_key": "Date as an integer YYYYMMDD; joins facts to dim_date",
    "day_name": "Weekday name",
    "day_of_month": "Day number in the month, 1 to 31",
    "day_of_week": "ISO weekday: 1 = Monday to 7 = Sunday",
    "delay_days": "Delivered minus estimated delivery date in days; positive means late",
    "delivered": "Delivered orders among the seller's orders",
    "delivered_date_key": "Date key (YYYYMMDD) of delivery to the customer",
    "delivered_orders": "Delivered orders",
    "delivery_days": "Days from purchase to delivery, delivered orders only",
    "description_length": "Characters in the product description",
    "estimated_date_key": "Date key (YYYYMMDD) of the estimated delivery date",
    "f_score": "Frequency score: 1 order = 1, 2 orders = 3, 3 or more = 5",
    "first_order_date": "Date of the customer's first order",
    "freight": "Freight charged in BRL",
    "freight_total": "Total freight of the order in BRL",
    "freight_value": "Freight charged for the item in BRL",
    "frequency": "Number of valid orders in the analysis window",
    "geography_key": "Surrogate key of the zip prefix in dim_geography; -1 means Unknown",
    "has_comment": "True if the review includes a written comment",
    "in_analysis_window": "True for dates from 2017-01-01 to 2018-08-31",
    "installments": "Number of installments of the payment",
    "is_delivered": "True if status is delivered and a delivery date exists",
    "is_late": "True if delivered after the estimated date; delivered orders only",
    "is_weekend": "True for Saturday or Sunday",
    "iso_week": "ISO week number of the year",
    "item_count": "Items in the order",
    "item_revenue": "Sum of item prices of the order in BRL",
    "item_total": "Item price plus freight in BRL",
    "items": "Items sold",
    "last_purchase": "Date of the customer's last valid order",
    "lat": "Average latitude of the zip prefix",
    "late_rate_pct": "Percent of delivered orders delivered late",
    "lng": "Average longitude of the zip prefix",
    "low_review_rate_pct": "Percent of reviewed orders with a score of 1 or 2",
    "m_score": "Monetary score 1 to 5 where 5 is the highest spend",
    "mom_change": "Change in revenue versus the previous month in BRL",
    "mom_pct": "Percent change in revenue versus the previous month",
    "monetary": "Total item revenue of the customer in BRL",
    "month": "Month number, 1 to 12",
    "month_name": "Month name",
    "month_short": "Three-letter month name",
    "month_start": "First day of the month",
    "months_since": "Months after the cohort month",
    "name_length": "Characters in the product name",
    "order_id": "Order identifier (degenerate dimension)",
    "order_item_id": "Item sequence number within the order",
    "order_status": "Order status: delivered, shipped, canceled, unavailable, invoiced, processing, created or approved",
    "orders": "Distinct valid orders",
    "orders_cancelled": "Orders canceled or unavailable among the seller's orders",
    "orders_total": "All orders containing the seller's items in the window",
    "payment_count": "Payment records of the order",
    "payment_sequential": "Payment sequence number within the order",
    "payment_total": "Total paid for the order in BRL",
    "payment_type": "credit_card, boleto, voucher, debit_card or not_defined",
    "payment_value": "Amount paid in BRL",
    "payments": "Payment records",
    "photos_qty": "Number of product photos",
    "price": "Item price in BRL, excluding freight",
    "product_id": "Source product identifier",
    "product_key": "Surrogate key of the product; -1 means Unknown",
    "product_label": "Short readable label built from the product id",
    "purchase_date": "Date the order was placed",
    "purchase_date_key": "Date key (YYYYMMDD) of the purchase date",
    "quarter": "Calendar quarter, 1 to 4",
    "r_score": "Recency score 1 to 5 where 5 is the most recent",
    "rank": "Rank by revenue where 1 is the highest",
    "recency_days": "Days between the last purchase and the snapshot date 2018-08-31",
    "region": "Brazilian region: North, Northeast, Central-West, Southeast or South",
    "repeat_rate_pct": "Percent of customers with 2 or more valid orders",
    "retention_pct": "Percent of the cohort active in the month",
    "revenue": "Item revenue of valid sales in BRL, excluding freight",
    "revenue_ma3": "Average revenue of the current and previous 2 months",
    "revenue_variance": "Actual revenue minus target revenue in BRL",
    "review_date_key": "Date key (YYYYMMDD) when the review was created",
    "review_id": "Source review identifier",
    "review_score": "Review score from 1 to 5",
    "reviews_for_order": "Reviews the order received; the latest is kept",
    "risk_score": "Seller risk score 0 to 100; empty for sellers with under 20 orders",
    "risk_tier": "Low, Medium, High or Not scored",
    "segment": "RFM customer segment",
    "seller_id": "Source seller identifier",
    "seller_key": "Surrogate key of the seller; -1 means Unknown",
    "seller_label": "Short readable label built from the seller id",
    "share_pct": "Share of the total in percent",
    "state_code": "Two-letter Brazilian state code",
    "state_name": "State name",
    "target_delivery_days": "Illustrative target for average delivery days",
    "target_orders": "Illustrative target for orders",
    "target_revenue": "Illustrative target for item revenue in BRL",
    "volume_cm3": "Product volume in cubic centimetres (length x height x width)",
    "weight_band": "Product weight band",
    "weight_g": "Product weight in grams",
    "year": "Calendar year",
    "year_month": "Year and month as YYYY-MM",
    "yoy_pct": "Percent change versus the same month one year earlier",
    "zip_prefix": "First five digits of the postal code",
}
RESTRICTED = {"customer_unique_id", "zip_prefix", "lat", "lng"}

cols = pd.read_sql("""
    SELECT n.nspname AS "schema", c.relname AS "table", a.attname AS "column",
           format_type(a.atttypid, a.atttypmod) AS data_type
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname IN ('core', 'marts') AND c.relkind IN ('r', 'v', 'm')
      AND a.attnum > 0 AND NOT a.attisdropped
    ORDER BY 1, 2, a.attnum""", engine)
missing = sorted(set(cols["column"]) - set(DEFINITIONS))
if missing:
    sys.exit(f"Add a definition for these columns in make_excel_inputs.py: {missing}")
cols["definition"] = cols["column"].map(DEFINITIONS)
cols["owner"] = "Data Analytics"
cols["sensitivity"] = cols["column"].map(lambda c: "restricted" if c in RESTRICTED else "internal")
save(cols[["schema", "table", "column", "definition", "data_type", "owner", "sensitivity"]], "data_dictionary.xlsx", [
    "Approved descriptions of every column in the core and marts schemas.",
    "The AI agent receives this as its approved context. sensitivity: public, internal or restricted.",
    "Generated from the database catalog; edit definitions in Excel and reload."])