"""Day 3: automated data-quality tests for the raw -> staging layers.

Each test answers one question and fails loudly if the answer is wrong.
Known, documented problems use a small allowed threshold (see docs/data_quality_policy.md).
"""
import pytest

# ---------- 1. Row counts: staging must reconcile to raw ----------------
SAME_GRAIN = ["customers", "orders", "order_items", "order_payments", "products", "sellers"]


@pytest.mark.parametrize("table", SAME_GRAIN)
def test_row_count_unchanged(scalar, table):
    raw = scalar(f"SELECT count(*) FROM raw.{table}")
    stg = scalar(f"SELECT count(*) FROM staging.{table}")
    assert raw == stg, f"{table}: raw={raw}, staging={stg}"


def test_reviews_one_row_per_order(scalar):
    expected = scalar("SELECT count(DISTINCT order_id) FROM raw.order_reviews")
    assert scalar("SELECT count(*) FROM staging.order_reviews") == expected


def test_geolocation_one_row_per_zip(scalar):
    expected = scalar("SELECT count(DISTINCT lpad(geolocation_zip_code_prefix,5,'0')) FROM raw.geolocation")
    assert scalar("SELECT count(*) FROM staging.geolocation") == expected


# ---------- 2. Keys: unique and not null --------------------------------
KEYS = [
    ("customers", "customer_id"),
    ("orders", "order_id"),
    ("sellers", "seller_id"),
    ("products", "product_id"),
    ("order_items", "order_id, order_item_id"),
    ("order_payments", "order_id, payment_sequential"),
    ("order_reviews", "order_id"),
    ("geolocation", "zip_prefix"),
]


@pytest.mark.parametrize("table,key", KEYS)
def test_key_is_unique(scalar, table, key):
    dup = scalar(f"SELECT count(*) FROM (SELECT {key} FROM staging.{table} "
                 f"GROUP BY {key} HAVING count(*) > 1) d")
    assert dup == 0, f"{table}: {dup} duplicated keys"


@pytest.mark.parametrize("table,column", [
    ("orders", "order_id"), ("orders", "customer_id"), ("orders", "purchase_ts"),
    ("order_items", "product_id"), ("order_items", "seller_id"), ("order_items", "price"),
    ("customers", "customer_unique_id"), ("products", "category_en"),
])
def test_column_not_null(scalar, table, column):
    nulls = scalar(f"SELECT count(*) FROM staging.{table} WHERE {column} IS NULL")
    assert nulls == 0, f"{table}.{column}: {nulls} NULL values"


# ---------- 3. Relationships: no orphan rows ----------------------------
RELATIONS = [
    ("orders", "customer_id", "customers", "customer_id"),
    ("order_items", "order_id", "orders", "order_id"),
    ("order_items", "product_id", "products", "product_id"),
    ("order_items", "seller_id", "sellers", "seller_id"),
    ("order_payments", "order_id", "orders", "order_id"),
    ("order_reviews", "order_id", "orders", "order_id"),
]


@pytest.mark.parametrize("child,ccol,parent,pcol", RELATIONS)
def test_no_orphans(scalar, child, ccol, parent, pcol):
    orphans = scalar(f"SELECT count(*) FROM staging.{child} c WHERE NOT EXISTS "
                     f"(SELECT 1 FROM staging.{parent} p WHERE p.{pcol} = c.{ccol})")
    assert orphans == 0, f"{child}.{ccol}: {orphans} rows without a parent in {parent}"


# ---------- 4. Valid values --------------------------------------------
def test_review_score_between_1_and_5(scalar):
    assert scalar("SELECT count(*) FROM staging.order_reviews WHERE review_score NOT BETWEEN 1 AND 5") == 0


def test_prices_positive(scalar):
    assert scalar("SELECT count(*) FROM staging.order_items WHERE price <= 0") == 0


def test_freight_and_payments_not_negative(scalar):
    assert scalar("SELECT count(*) FROM staging.order_items WHERE freight_value < 0") == 0
    assert scalar("SELECT count(*) FROM staging.order_payments WHERE payment_value < 0") == 0


def test_order_status_known(scalar):
    bad = scalar("SELECT count(*) FROM staging.orders WHERE order_status NOT IN "
                 "('delivered','shipped','canceled','unavailable','invoiced','processing','created','approved')")
    assert bad == 0


def test_payment_type_known(scalar):
    bad = scalar("SELECT count(*) FROM staging.order_payments WHERE payment_type NOT IN "
                 "('credit_card','boleto','voucher','debit_card','not_defined')")
    assert bad == 0


# ---------- 5. Timelines and delivery metrics ---------------------------
def test_approved_not_before_purchase(scalar):
    assert scalar("SELECT count(*) FROM staging.orders WHERE approved_ts < purchase_ts") == 0


def test_delivered_not_before_purchase(scalar):
    assert scalar("SELECT count(*) FROM staging.orders WHERE delivered_ts < purchase_ts") == 0


def test_known_issue_carrier_before_purchase_is_small(scalar):
    # Known source problem (about 166 orders). Allowed up to 0.5 percent of orders.
    bad = scalar("SELECT count(*) FROM staging.orders WHERE carrier_ts < purchase_ts")
    total = scalar("SELECT count(*) FROM staging.orders")
    assert bad / total < 0.005, f"{bad} orders handed to carrier before purchase"


def test_known_issue_delivered_before_carrier_is_small(scalar):
    # Known source problem (about 23 orders). Allowed up to 0.1 percent of orders.
    bad = scalar("SELECT count(*) FROM staging.orders WHERE delivered_ts < carrier_ts")
    total = scalar("SELECT count(*) FROM staging.orders")
    assert bad / total < 0.001, f"{bad} orders delivered before carrier pickup"


def test_delivery_metrics_only_for_delivered_orders(scalar):
    assert scalar("SELECT count(*) FROM staging.orders WHERE NOT is_delivered "
                  "AND (delivery_days IS NOT NULL OR delay_days IS NOT NULL OR is_late IS NOT NULL)") == 0


def test_delivery_days_not_negative(scalar):
    assert scalar("SELECT count(*) FROM staging.orders WHERE delivery_days < 0") == 0


def test_is_late_agrees_with_delay_days(scalar):
    # delay_days is rounded to 2 decimals, so a very slightly late order can show 0.00.
    # The flag and the number must never point in opposite directions.
    assert scalar("SELECT count(*) FROM staging.orders WHERE is_late AND delay_days < 0") == 0
    assert scalar("SELECT count(*) FROM staging.orders WHERE is_late = false AND delay_days > 0") == 0


def test_delivered_without_date_is_tiny(scalar):
    bad = scalar("SELECT count(*) FROM staging.orders WHERE order_status = 'delivered' AND delivered_ts IS NULL")
    assert bad <= 20, f"{bad} orders say delivered but have no delivery date"


# ---------- 6. Money reconciles to the source ---------------------------
def test_item_revenue_matches_raw(scalar):
    raw = scalar("SELECT sum(price::numeric) FROM raw.order_items")
    stg = scalar("SELECT sum(price) FROM staging.order_items")
    assert abs(raw - stg) < 0.01


def test_freight_matches_raw(scalar):
    raw = scalar("SELECT sum(freight_value::numeric) FROM raw.order_items")
    stg = scalar("SELECT sum(freight_value) FROM staging.order_items")
    assert abs(raw - stg) < 0.01


def test_payments_match_raw(scalar):
    raw = scalar("SELECT sum(payment_value::numeric) FROM raw.order_payments")
    stg = scalar("SELECT sum(payment_value) FROM staging.order_payments")
    assert abs(raw - stg) < 0.01


def test_payments_reconcile_with_items(scalar):
    # Vouchers, rounding and installment interest cause small gaps. Allow under 1 percent of orders.
    bad = scalar("""SELECT count(*) FROM
        (SELECT order_id, sum(payment_value) paid FROM staging.order_payments GROUP BY 1) p
        JOIN (SELECT order_id, sum(price + freight_value) billed FROM staging.order_items GROUP BY 1) i USING (order_id)
        WHERE abs(p.paid - i.billed) > 1""")
    total = scalar("SELECT count(DISTINCT order_id) FROM staging.order_items")
    assert bad / total < 0.01, f"{bad} of {total} orders do not reconcile"


# ---------- 7. Categories and the issue log -----------------------------
def test_unknown_category_share_is_small(scalar):
    unknown = scalar("SELECT count(*) FROM staging.products WHERE category_en = 'unknown'")
    total = scalar("SELECT count(*) FROM staging.products")
    assert unknown / total < 0.02


def test_every_known_category_is_translated(scalar):
    bad = scalar("SELECT count(*) FROM staging.products WHERE category_pt <> 'unknown' AND category_en = 'unknown'")
    assert bad == 0


def test_issue_log_is_populated(scalar):
    assert scalar("SELECT count(*) FROM audit.dq_issues WHERE layer = 'raw->staging'") >= 13


def test_checks_that_must_be_zero_are_zero(scalar):
    bad = scalar("""SELECT count(*) FROM audit.dq_issues WHERE layer = 'raw->staging'
        AND check_name IN ('delivered before purchase','zero or negative price','review score outside 1-5')
        AND issue_count > 0""")
    assert bad == 0


def test_raw_load_log_is_all_ok(scalar):
    assert scalar("""SELECT count(*) FROM (SELECT DISTINCT ON (table_name) table_name, status
        FROM audit.load_log ORDER BY table_name, id DESC) l WHERE status <> 'OK'""") == 0