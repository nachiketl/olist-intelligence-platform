"""Day 4: tests for the dimension tables in the core schema."""
import pytest

DIMS = {
    "dim_state": ("state_code", None),
    "dim_date": ("date_key", None),
    "dim_geography": ("geography_key", "zip_prefix"),
    "dim_customers": ("customer_key", "customer_unique_id"),
    "dim_sellers": ("seller_key", "seller_id"),
    "dim_products": ("product_key", "product_id"),
}
WITH_UNKNOWN = ["dim_geography", "dim_customers", "dim_sellers", "dim_products"]


# ---------- 1. Keys ------------------------------------------------------
@pytest.mark.parametrize("dim,cols", [(d, c) for d, c in DIMS.items()])
def test_surrogate_key_is_unique(scalar, dim, cols):
    key = cols[0]
    assert scalar(f"SELECT count(*) - count(DISTINCT {key}) FROM core.{dim}") == 0


@pytest.mark.parametrize("dim,cols", [(d, c) for d, c in DIMS.items() if c[1]])
def test_natural_key_is_unique(scalar, dim, cols):
    nat = cols[1]
    assert scalar(f"SELECT count(*) - count(DISTINCT {nat}) FROM core.{dim}") == 0


@pytest.mark.parametrize("dim", WITH_UNKNOWN)
def test_unknown_member_exists(scalar, dim):
    key = DIMS[dim][0]
    assert scalar(f"SELECT count(*) FROM core.{dim} WHERE {key} = -1") == 1


# ---------- 2. Row counts match staging ----------------------------------
def test_customers_one_row_per_person(scalar):
    expected = scalar("SELECT count(DISTINCT customer_unique_id) FROM staging.customers")
    assert scalar("SELECT count(*) FROM core.dim_customers WHERE customer_key <> -1") == expected


def test_sellers_match_staging(scalar):
    assert scalar("SELECT count(*) FROM core.dim_sellers WHERE seller_key <> -1") == scalar("SELECT count(*) FROM staging.sellers")


def test_products_match_staging(scalar):
    assert scalar("SELECT count(*) FROM core.dim_products WHERE product_key <> -1") == scalar("SELECT count(*) FROM staging.products")


def test_geography_matches_staging(scalar):
    assert scalar("SELECT count(*) FROM core.dim_geography WHERE geography_key <> -1") == scalar("SELECT count(*) FROM staging.geolocation")


def test_all_27_states_present(scalar):
    assert scalar("SELECT count(*) FROM core.dim_state") == 27


# ---------- 3. Every fact value can find its dimension row ----------------
def test_every_ordered_product_in_dimension(scalar):
    assert scalar("SELECT count(*) FROM staging.order_items i WHERE NOT EXISTS "
                  "(SELECT 1 FROM core.dim_products p WHERE p.product_id = i.product_id)") == 0


def test_every_seller_in_dimension(scalar):
    assert scalar("SELECT count(*) FROM staging.order_items i WHERE NOT EXISTS "
                  "(SELECT 1 FROM core.dim_sellers s WHERE s.seller_id = i.seller_id)") == 0


def test_every_customer_in_dimension(scalar):
    assert scalar("SELECT count(*) FROM staging.customers c WHERE NOT EXISTS "
                  "(SELECT 1 FROM core.dim_customers d WHERE d.customer_unique_id = c.customer_unique_id)") == 0


def test_geography_keys_point_to_real_rows(scalar):
    for dim in ("dim_customers", "dim_sellers"):
        assert scalar(f"SELECT count(*) FROM core.{dim} d WHERE NOT EXISTS "
                      f"(SELECT 1 FROM core.dim_geography g WHERE g.geography_key = d.geography_key)") == 0


def test_known_issue_few_customers_without_geography(scalar):
    # Some zip prefixes are missing from the geolocation file; they map to the Unknown member.
    unknown = scalar("SELECT count(*) FROM core.dim_customers WHERE geography_key = -1 AND customer_key <> -1")
    total = scalar("SELECT count(*) FROM core.dim_customers WHERE customer_key <> -1")
    assert unknown / total < 0.01


def test_known_issue_few_sellers_without_geography(scalar):
    unknown = scalar("SELECT count(*) FROM core.dim_sellers WHERE geography_key = -1 AND seller_key <> -1")
    total = scalar("SELECT count(*) FROM core.dim_sellers WHERE seller_key <> -1")
    assert unknown / total < 0.01


# ---------- 4. Attributes are valid ----------------------------------------
@pytest.mark.parametrize("dim,key", [("dim_customers", "customer_key"), ("dim_sellers", "seller_key"), ("dim_geography", "geography_key")])
def test_every_state_is_known(scalar, dim, key):
    assert scalar(f"SELECT count(*) FROM core.{dim} WHERE {key} <> -1 AND region = 'Unknown'") == 0


def test_seller_and_product_labels_unique(scalar):
    assert scalar("SELECT count(*) - count(DISTINCT seller_label) FROM core.dim_sellers") == 0
    assert scalar("SELECT count(*) - count(DISTINCT product_label) FROM core.dim_products") == 0


def test_weight_band_values(scalar):
    assert scalar("SELECT count(*) FROM core.dim_products WHERE weight_band NOT IN "
                  "('1. Light (under 0.5 kg)','2. Medium (0.5 to 2 kg)','3. Heavy (2 to 10 kg)',"
                  "'4. Very heavy (10 kg and over)','Unknown')") == 0


def test_product_numbers_not_negative(scalar):
    assert scalar("SELECT count(*) FROM core.dim_products WHERE weight_g < 0 OR volume_cm3 < 0") == 0


def test_first_order_date_present_and_sensible(scalar):
    assert scalar("SELECT count(*) FROM core.dim_customers WHERE customer_key <> -1 AND first_order_date IS NULL") == 0
    assert scalar("SELECT count(*) FROM core.dim_customers WHERE first_order_date < DATE '2016-01-01'") == 0


# ---------- 5. The date dimension ------------------------------------------
def test_date_has_no_gaps(scalar):
    assert scalar("SELECT count(*) FROM core.dim_date") == scalar("SELECT max(date) - min(date) + 1 FROM core.dim_date")


def test_date_covers_all_order_dates(scalar):
    assert scalar("SELECT count(*) FROM staging.orders o WHERE NOT EXISTS "
                  "(SELECT 1 FROM core.dim_date d WHERE d.date = o.purchase_ts::date)") == 0
    assert scalar("SELECT count(*) FROM staging.orders o WHERE o.delivered_ts IS NOT NULL AND NOT EXISTS "
                  "(SELECT 1 FROM core.dim_date d WHERE d.date = o.delivered_ts::date)") == 0
    assert scalar("SELECT count(*) FROM staging.orders o WHERE NOT EXISTS "
                  "(SELECT 1 FROM core.dim_date d WHERE d.date = o.estimated_ts::date)") == 0


def test_date_covers_review_dates(scalar):
    assert scalar("SELECT count(*) FROM staging.order_reviews r WHERE r.review_answer_ts IS NOT NULL AND NOT EXISTS "
                  "(SELECT 1 FROM core.dim_date d WHERE d.date = r.review_answer_ts::date)") == 0


def test_date_key_matches_date(scalar):
    assert scalar("SELECT count(*) FROM core.dim_date WHERE date_key <> to_char(date,'YYYYMMDD')::int") == 0


def test_weekend_flag_is_correct(scalar):
    assert scalar("SELECT count(*) FROM core.dim_date WHERE is_weekend <> (day_of_week IN (6,7))") == 0
    assert scalar("SELECT count(*) FROM core.dim_date WHERE day_of_week NOT BETWEEN 1 AND 7") == 0


def test_analysis_window_is_20_months(scalar):
    assert scalar("SELECT count(DISTINCT year_month) FROM core.dim_date WHERE in_analysis_window") == 20
    assert scalar("SELECT min(date) FROM core.dim_date WHERE in_analysis_window") == __import__("datetime").date(2017, 1, 1)
    assert scalar("SELECT max(date) FROM core.dim_date WHERE in_analysis_window") == __import__("datetime").date(2018, 8, 31)


def test_year_and_month_columns_consistent(scalar):
    assert scalar("SELECT count(*) FROM core.dim_date WHERE year <> extract(year FROM date) "
                  "OR month <> extract(month FROM date) OR year_month <> to_char(date,'YYYY-MM')") == 0