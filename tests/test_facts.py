"""Day 5: tests for the fact tables in the core schema."""
import pytest

FACTS = [
    ("fact_order_items", "order_id, order_item_id", "staging.order_items"),
    ("fact_orders", "order_id", "staging.orders"),
    ("fact_payments", "order_id, payment_sequential", "staging.order_payments"),
    ("fact_reviews", "order_id", "staging.order_reviews"),
]


# ---------- 1. Grain: row counts and unique keys -------------------------
@pytest.mark.parametrize("fact,key,source", FACTS)
def test_row_count_matches_staging(scalar, fact, key, source):
    assert scalar(f"SELECT count(*) FROM core.{fact}") == scalar(f"SELECT count(*) FROM {source}")


@pytest.mark.parametrize("fact,key,source", FACTS)
def test_primary_key_is_unique(scalar, fact, key, source):
    dup = scalar(f"SELECT count(*) FROM (SELECT {key} FROM core.{fact} GROUP BY {key} HAVING count(*) > 1) d")
    assert dup == 0, f"{fact}: {dup} duplicated keys"


# ---------- 2. Keys are filled ---------------------------------------------
NOT_NULL = [
    ("fact_order_items", "purchase_date_key"), ("fact_order_items", "customer_key"),
    ("fact_order_items", "product_key"), ("fact_order_items", "seller_key"), ("fact_order_items", "price"),
    ("fact_orders", "customer_key"), ("fact_orders", "purchase_date_key"),
    ("fact_orders", "estimated_date_key"), ("fact_orders", "item_revenue"),
    ("fact_payments", "customer_key"), ("fact_payments", "payment_value"),
    ("fact_reviews", "review_score"), ("fact_reviews", "review_date_key"),
]


@pytest.mark.parametrize("fact,col", NOT_NULL)
def test_column_not_null(scalar, fact, col):
    assert scalar(f"SELECT count(*) FROM core.{fact} WHERE {col} IS NULL") == 0


# ---------- 3. Every key finds its dimension row -----------------------------
DIM_KEYS = [
    ("fact_order_items", "customer_key", "dim_customers"),
    ("fact_order_items", "product_key", "dim_products"),
    ("fact_order_items", "seller_key", "dim_sellers"),
    ("fact_orders", "customer_key", "dim_customers"),
    ("fact_payments", "customer_key", "dim_customers"),
    ("fact_reviews", "customer_key", "dim_customers"),
]


@pytest.mark.parametrize("fact,col,dim", DIM_KEYS)
def test_dimension_key_exists(scalar, fact, col, dim):
    assert scalar(f"SELECT count(*) FROM core.{fact} f WHERE NOT EXISTS "
                  f"(SELECT 1 FROM core.{dim} d WHERE d.{col} = f.{col})") == 0


DATE_KEYS = [
    ("fact_order_items", "purchase_date_key"),
    ("fact_orders", "purchase_date_key"), ("fact_orders", "approved_date_key"),
    ("fact_orders", "carrier_date_key"), ("fact_orders", "delivered_date_key"),
    ("fact_orders", "estimated_date_key"),
    ("fact_payments", "purchase_date_key"),
    ("fact_reviews", "review_date_key"), ("fact_reviews", "answer_date_key"),
]


@pytest.mark.parametrize("fact,col", DATE_KEYS)
def test_date_key_exists(scalar, fact, col):
    assert scalar(f"SELECT count(*) FROM core.{fact} f WHERE f.{col} IS NOT NULL AND NOT EXISTS "
                  f"(SELECT 1 FROM core.dim_date d WHERE d.date_key = f.{col})") == 0


UNKNOWN_USED = [("fact_order_items", "customer_key"), ("fact_order_items", "product_key"),
                ("fact_order_items", "seller_key"), ("fact_orders", "customer_key")]


@pytest.mark.parametrize("fact,col", UNKNOWN_USED)
def test_unknown_member_not_needed(scalar, fact, col):
    # In this dataset every key matches. If this ever fails, new data has unmatched ids.
    assert scalar(f"SELECT count(*) FROM core.{fact} WHERE {col} = -1") == 0


# ---------- 4. Money reconciles to staging -------------------------------------
def _close(a, b):
    return abs(a - b) < 0.01


def test_item_revenue_matches_staging(scalar):
    assert _close(scalar("SELECT sum(price) FROM core.fact_order_items"), scalar("SELECT sum(price) FROM staging.order_items"))


def test_freight_matches_staging(scalar):
    assert _close(scalar("SELECT sum(freight_value) FROM core.fact_order_items"), scalar("SELECT sum(freight_value) FROM staging.order_items"))


def test_item_total_is_price_plus_freight(scalar):
    assert scalar("SELECT count(*) FROM core.fact_order_items WHERE item_total <> price + freight_value") == 0


def test_payments_match_staging(scalar):
    assert _close(scalar("SELECT sum(payment_value) FROM core.fact_payments"), scalar("SELECT sum(payment_value) FROM staging.order_payments"))


def test_order_level_revenue_equals_item_level(scalar):
    assert _close(scalar("SELECT sum(item_revenue) FROM core.fact_orders"), scalar("SELECT sum(price) FROM core.fact_order_items"))


def test_order_level_freight_equals_item_level(scalar):
    assert _close(scalar("SELECT sum(freight_total) FROM core.fact_orders"), scalar("SELECT sum(freight_value) FROM core.fact_order_items"))


def test_order_level_payments_equal_payment_fact(scalar):
    assert _close(scalar("SELECT sum(payment_total) FROM core.fact_orders"), scalar("SELECT sum(payment_value) FROM core.fact_payments"))


def test_item_counts_add_up(scalar):
    assert scalar("SELECT sum(item_count) FROM core.fact_orders") == scalar("SELECT count(*) FROM core.fact_order_items")


def test_orders_without_items_have_zero_revenue(scalar):
    assert scalar("SELECT count(*) FROM core.fact_orders WHERE item_count = 0 AND (item_revenue <> 0 OR freight_total <> 0)") == 0
    assert scalar("SELECT count(*) FROM core.fact_orders WHERE item_count = 0") == scalar(
        "SELECT count(*) FROM staging.orders o WHERE NOT EXISTS (SELECT 1 FROM staging.order_items i WHERE i.order_id = o.order_id)")


def test_order_status_agrees_between_facts(scalar):
    assert scalar("SELECT count(*) FROM core.fact_order_items i JOIN core.fact_orders o USING (order_id) "
                  "WHERE i.order_status <> o.order_status") == 0


# ---------- 5. Delivery and review measures --------------------------------------
def test_delivered_count_matches_staging(scalar):
    assert scalar("SELECT count(*) FROM core.fact_orders WHERE is_delivered") == scalar("SELECT count(*) FROM staging.orders WHERE is_delivered")


def test_late_count_matches_staging(scalar):
    assert scalar("SELECT count(*) FROM core.fact_orders WHERE is_late") == scalar("SELECT count(*) FROM staging.orders WHERE is_late")


def test_average_delivery_days_matches_staging(scalar):
    a = scalar("SELECT avg(delivery_days) FROM core.fact_orders")
    b = scalar("SELECT avg(delivery_days) FROM staging.orders")
    assert abs(a - b) < 0.001


def test_delivered_orders_have_delivery_date_key(scalar):
    assert scalar("SELECT count(*) FROM core.fact_orders WHERE is_delivered AND delivered_date_key IS NULL") == 0


def test_average_review_score_matches_staging(scalar):
    a = scalar("SELECT avg(review_score) FROM core.fact_reviews")
    b = scalar("SELECT avg(review_score) FROM staging.order_reviews")
    assert abs(a - b) < 0.0001


def test_review_score_valid(scalar):
    assert scalar("SELECT count(*) FROM core.fact_reviews WHERE review_score NOT BETWEEN 1 AND 5") == 0


# ---------- 6. Why the facts are never joined and summed ----------------------------
def test_naive_join_inflates_revenue_and_payments(scalar):
    # A teaching test: joining items to payments repeats rows, so sums become wrong.
    true_rev = scalar("SELECT sum(price) FROM core.fact_order_items")
    naive_rev = scalar("SELECT sum(i.price) FROM core.fact_order_items i JOIN core.fact_payments p USING (order_id)")
    true_pay = scalar("SELECT sum(payment_value) FROM core.fact_payments")
    naive_pay = scalar("SELECT sum(p.payment_value) FROM core.fact_order_items i JOIN core.fact_payments p USING (order_id)")
    assert naive_rev > true_rev, "naive join should repeat item rows"
    assert naive_pay > true_pay, "naive join should repeat payment rows"


# ---------- 7. Analysis window -----------------------------------------------------
def test_most_revenue_is_inside_analysis_window(scalar):
    share = scalar("SELECT sum(price) FILTER (WHERE purchase_date_key BETWEEN 20170101 AND 20180831) "
                   "/ sum(price) FROM core.fact_order_items")
    assert share > 0.99