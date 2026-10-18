"""Day 6: tests for the marts. Each mart is checked against an independent calculation from the facts."""
import pytest

VALID = "f.order_status NOT IN ('canceled','unavailable')"
WINDOW = "d.in_analysis_window"
# Independent definition of revenue (does not use the marts helper views)
REVENUE_SQL = (f"SELECT sum(f.price) FROM core.fact_order_items f JOIN core.dim_date d ON d.date_key = f.purchase_date_key "
               f"WHERE {WINDOW} AND {VALID}")


def revenue(scalar):
    return float(scalar(REVENUE_SQL))


# ---------- 1. KPI summary -----------------------------------------------------
def test_kpi_revenue_matches_facts(scalar):
    assert abs(float(scalar("SELECT revenue FROM marts.kpi_summary")) - revenue(scalar)) < 0.01


def test_kpi_orders_match_facts(scalar):
    expected = scalar(f"SELECT count(DISTINCT f.order_id) FROM core.fact_order_items f JOIN core.dim_date d "
                      f"ON d.date_key = f.purchase_date_key WHERE {WINDOW} AND {VALID}")
    assert scalar("SELECT orders FROM marts.kpi_summary") == expected


def test_kpi_aov_is_revenue_over_orders(scalar):
    rev, orders, aov = [float(x) for x in (scalar("SELECT revenue FROM marts.kpi_summary"),
                                           scalar("SELECT orders FROM marts.kpi_summary"),
                                           scalar("SELECT aov FROM marts.kpi_summary"))]
    assert abs(aov - rev / orders) < 0.01


def test_kpi_customers_are_people_with_valid_orders(scalar):
    expected = scalar(f"SELECT count(DISTINCT f.customer_key) FROM core.fact_order_items f JOIN core.dim_date d "
                      f"ON d.date_key = f.purchase_date_key WHERE {WINDOW} AND {VALID}")
    assert scalar("SELECT customers FROM marts.kpi_summary") == expected


def test_kpi_rates_are_sensible(scalar):
    assert 0 < float(scalar("SELECT repeat_rate_pct FROM marts.kpi_summary")) < 20
    assert 0 < float(scalar("SELECT late_rate_pct FROM marts.kpi_summary")) < 30
    assert 1 <= float(scalar("SELECT avg_review FROM marts.kpi_summary")) <= 5
    assert 0 < float(scalar("SELECT avg_delivery_days FROM marts.kpi_summary")) < 60


def test_cancelled_and_unavailable_are_excluded(scalar):
    all_status = float(scalar(f"SELECT sum(f.price) FROM core.fact_order_items f JOIN core.dim_date d "
                              f"ON d.date_key = f.purchase_date_key WHERE {WINDOW}"))
    excluded = float(scalar(f"SELECT sum(f.price) FROM core.fact_order_items f JOIN core.dim_date d "
                            f"ON d.date_key = f.purchase_date_key WHERE {WINDOW} "
                            f"AND f.order_status IN ('canceled','unavailable')"))
    assert abs((all_status - excluded) - revenue(scalar)) < 0.01 and excluded > 0


# ---------- 2. Monthly sales ----------------------------------------------------
def test_monthly_has_20_months(scalar):
    assert scalar("SELECT count(*) FROM marts.monthly_sales") == 20


def test_monthly_revenue_adds_up(scalar):
    assert abs(float(scalar("SELECT sum(revenue) FROM marts.monthly_sales")) - revenue(scalar)) < 0.01


def test_monthly_orders_add_up(scalar):
    assert scalar("SELECT sum(orders) FROM marts.monthly_sales") == scalar("SELECT orders FROM marts.kpi_summary")


def test_first_month_has_no_growth(scalar):
    assert scalar("SELECT mom_pct FROM marts.monthly_sales ORDER BY month_start LIMIT 1") is None


def test_mom_growth_is_correct(scalar):
    got = float(scalar("SELECT mom_pct FROM marts.monthly_sales WHERE year_month = '2017-02'"))
    jan = float(scalar("SELECT revenue FROM marts.monthly_sales WHERE year_month = '2017-01'"))
    feb = float(scalar("SELECT revenue FROM marts.monthly_sales WHERE year_month = '2017-02'"))
    assert abs(got - round(100 * (feb - jan) / jan, 1)) < 0.06


def test_moving_average_is_correct(scalar):
    got = float(scalar("SELECT revenue_ma3 FROM marts.monthly_sales WHERE year_month = '2017-03'"))
    avg = float(scalar("SELECT avg(revenue) FROM (SELECT revenue FROM marts.monthly_sales ORDER BY month_start LIMIT 3) t"))
    assert abs(got - avg) < 0.01


def test_yoy_only_exists_from_2018(scalar):
    assert scalar("SELECT count(*) FROM marts.monthly_sales WHERE year_month LIKE '2017%' AND yoy_pct IS NOT NULL") == 0
    assert scalar("SELECT count(*) FROM marts.monthly_sales WHERE year_month LIKE '2018%' AND yoy_pct IS NULL") == 0


def test_monthly_aov_is_revenue_over_orders(scalar):
    assert scalar("SELECT count(*) FROM marts.monthly_sales WHERE abs(aov - revenue / orders) > 0.01") == 0


# ---------- 3. Category Pareto ----------------------------------------------------
def test_pareto_revenue_adds_up(scalar):
    assert abs(float(scalar("SELECT sum(revenue) FROM marts.category_pareto")) - revenue(scalar)) < 0.01


def test_pareto_ranks_are_consecutive(scalar):
    n = scalar("SELECT count(*) FROM marts.category_pareto")
    assert scalar("SELECT max(rank) FROM marts.category_pareto") == n
    assert scalar("SELECT count(DISTINCT rank) FROM marts.category_pareto") == n


def test_pareto_shares_sum_to_100(scalar):
    assert abs(float(scalar("SELECT sum(share_pct) FROM marts.category_pareto")) - 100) < 0.5
    assert abs(float(scalar("SELECT max(cumulative_pct) FROM marts.category_pareto")) - 100) < 0.01


def test_pareto_cumulative_never_decreases(scalar):
    assert scalar("SELECT count(*) FROM (SELECT cumulative_pct - lag(cumulative_pct) OVER (ORDER BY rank) AS d "
                  "FROM marts.category_pareto) t WHERE d < 0") == 0


def test_pareto_classes(scalar):
    assert scalar("SELECT count(*) FROM marts.category_pareto WHERE abc_class NOT IN ('A','B','C')") == 0
    assert float(scalar("SELECT sum(share_pct) FROM marts.category_pareto WHERE abc_class = 'A'")) >= 80


def test_pareto_covers_every_category(scalar):
    expected = scalar(f"SELECT count(DISTINCT p.category_en) FROM core.fact_order_items f JOIN core.dim_date d "
                      f"ON d.date_key = f.purchase_date_key JOIN core.dim_products p ON p.product_key = f.product_key "
                      f"WHERE {WINDOW} AND {VALID}")
    assert scalar("SELECT count(*) FROM marts.category_pareto") == expected


# ---------- 4. State delivery -----------------------------------------------------
def test_state_delivery_covers_all_states(scalar):
    assert scalar("SELECT count(*) FROM marts.state_delivery") == 27


def test_state_delivered_orders_match_facts(scalar):
    expected = scalar("SELECT count(*) FROM core.fact_orders o JOIN core.dim_date d ON d.date_key = o.purchase_date_key "
                      "WHERE o.is_delivered AND d.in_analysis_window")
    assert scalar("SELECT sum(delivered_orders) FROM marts.state_delivery") == expected


def test_state_late_rate_in_range_and_consistent(scalar):
    assert scalar("SELECT count(*) FROM marts.state_delivery WHERE late_rate_pct < 0 OR late_rate_pct > 100") == 0
    weighted = float(scalar("SELECT sum(late_rate_pct * delivered_orders) / sum(delivered_orders) FROM marts.state_delivery"))
    assert abs(weighted - float(scalar("SELECT late_rate_pct FROM marts.kpi_summary"))) < 0.1


# ---------- 5. RFM ------------------------------------------------------------------
def test_rfm_one_row_per_customer(scalar):
    assert scalar("SELECT count(*) - count(DISTINCT customer_key) FROM marts.customer_rfm") == 0
    assert scalar("SELECT count(*) FROM marts.customer_rfm") == scalar("SELECT customers FROM marts.kpi_summary")


def test_rfm_money_and_orders_add_up(scalar):
    assert abs(float(scalar("SELECT sum(monetary) FROM marts.customer_rfm")) - revenue(scalar)) < 1
    assert scalar("SELECT sum(frequency) FROM marts.customer_rfm") == scalar("SELECT orders FROM marts.kpi_summary")


def test_rfm_scores_valid(scalar):
    assert scalar("SELECT count(*) FROM marts.customer_rfm WHERE r_score NOT BETWEEN 1 AND 5 OR m_score NOT BETWEEN 1 AND 5 "
                  "OR f_score NOT IN (1,3,5)") == 0
    assert scalar("SELECT count(*) FROM marts.customer_rfm WHERE recency_days < 0 OR frequency < 1 OR monetary <= 0") == 0


def test_rfm_buckets_are_even(scalar):
    sizes = scalar("SELECT max(c) - min(c) FROM (SELECT count(*) c FROM marts.customer_rfm GROUP BY r_score) t")
    assert sizes <= 1


def test_rfm_segments_valid(scalar):
    assert scalar("SELECT count(*) FROM marts.customer_rfm WHERE segment NOT IN ('Loyal repeat','Lapsed repeat',"
                  "'New high value','New customer','Cooling','Lost high value','Lost')") == 0


def test_repeat_rate_matches_rfm(scalar):
    rate = 100.0 * scalar("SELECT count(*) FROM marts.customer_rfm WHERE frequency >= 2") / scalar("SELECT count(*) FROM marts.customer_rfm")
    assert abs(rate - float(scalar("SELECT repeat_rate_pct FROM marts.kpi_summary"))) < 0.01


def test_most_customers_buy_once(scalar):
    assert scalar("SELECT count(*) FILTER (WHERE frequency = 1) * 1.0 / count(*) FROM marts.customer_rfm") > 0.9


# ---------- 6. Cohort retention --------------------------------------------------------
def test_cohort_month_zero_is_100_percent(scalar):
    assert scalar("SELECT count(*) FROM marts.cohort_retention WHERE months_since = 0 AND retention_pct <> 100") == 0
    assert scalar("SELECT count(*) FROM marts.cohort_retention WHERE months_since = 0 AND active_customers <> cohort_size") == 0


def test_cohort_retention_in_range(scalar):
    assert scalar("SELECT count(*) FROM marts.cohort_retention WHERE retention_pct < 0 OR retention_pct > 100 OR months_since < 0") == 0


def test_cohort_rows_are_unique(scalar):
    assert scalar("SELECT count(*) - count(DISTINCT (cohort_month, months_since)) FROM marts.cohort_retention") == 0


def test_cohort_count_and_length(scalar):
    assert scalar("SELECT count(DISTINCT cohort_month) FROM marts.cohort_retention") == 20
    assert scalar("SELECT max(months_since) FROM marts.cohort_retention WHERE cohort = '2017-01'") == 19


def test_cohort_sizes_match_first_orders(scalar):
    expected = scalar("""SELECT count(*) FROM (
        SELECT o.customer_key, min(d.month_start) AS m FROM core.fact_orders o JOIN core.dim_date d ON d.date_key = o.purchase_date_key
        WHERE o.order_status NOT IN ('canceled','unavailable') AND o.item_count > 0 GROUP BY 1) x
        WHERE m BETWEEN DATE '2017-01-01' AND DATE '2018-08-01'""")
    assert scalar("SELECT sum(cohort_size) FROM (SELECT DISTINCT cohort_month, cohort_size FROM marts.cohort_retention) c") == expected


def test_known_finding_retention_is_low(scalar):
    # Honest business finding: month-1 retention is below 2 percent for every cohort.
    assert scalar("SELECT max(retention_pct) FROM marts.cohort_retention WHERE months_since = 1") < 2


# ---------- 7. Seller scorecard --------------------------------------------------------
def test_seller_one_row_each(scalar):
    assert scalar("SELECT count(*) - count(DISTINCT seller_key) FROM marts.seller_scorecard") == 0


def test_seller_revenue_adds_up(scalar):
    assert abs(float(scalar("SELECT sum(revenue) FROM marts.seller_scorecard")) - revenue(scalar)) < 0.5


def test_seller_scoring_rules(scalar):
    assert scalar("SELECT count(*) FROM marts.seller_scorecard WHERE (orders_total >= 20) <> (risk_score IS NOT NULL)") == 0
    assert scalar("SELECT count(*) FROM marts.seller_scorecard WHERE risk_score < 0 OR risk_score > 100") == 0
    assert scalar("SELECT count(*) FROM marts.seller_scorecard WHERE risk_tier NOT IN ('Low','Medium','High','Not scored')") == 0


def test_seller_tiers_match_scores(scalar):
    assert scalar("SELECT count(*) FROM marts.seller_scorecard WHERE risk_tier = 'High' AND risk_score < 49.95") == 0
    assert scalar("SELECT count(*) FROM marts.seller_scorecard WHERE risk_tier = 'Low' AND risk_score >= 25.05") == 0


def test_seller_rates_in_range(scalar):
    assert scalar("SELECT count(*) FROM marts.seller_scorecard WHERE late_rate_pct NOT BETWEEN 0 AND 100 "
                  "OR cancel_rate_pct NOT BETWEEN 0 AND 100 OR low_review_rate_pct NOT BETWEEN 0 AND 100") == 0
    assert scalar("SELECT count(*) FROM marts.seller_scorecard WHERE orders_cancelled > orders_total") == 0


def test_every_seller_with_sales_is_listed(scalar):
    expected = scalar(f"SELECT count(DISTINCT f.seller_key) FROM core.fact_order_items f JOIN core.dim_date d "
                      f"ON d.date_key = f.purchase_date_key WHERE {WINDOW}")
    assert scalar("SELECT count(*) FROM marts.seller_scorecard") == expected


# ---------- 8. Payment mix -------------------------------------------------------------
def test_payment_shares_sum_to_100(scalar):
    assert abs(float(scalar("SELECT sum(share_pct) FROM marts.payment_mix")) - 100) < 0.1


def test_payment_types_known(scalar):
    assert scalar("SELECT count(*) FROM marts.payment_mix WHERE payment_type NOT IN "
                  "('credit_card','boleto','voucher','debit_card','not_defined')") == 0


def test_payment_value_matches_facts(scalar):
    expected = float(scalar("SELECT sum(p.payment_value) FROM core.fact_payments p JOIN core.fact_orders o ON o.order_id = p.order_id "
                            "JOIN core.dim_date d ON d.date_key = p.purchase_date_key "
                            "WHERE d.in_analysis_window AND o.order_status NOT IN ('canceled','unavailable')"))
    assert abs(float(scalar("SELECT sum(payment_value) FROM marts.payment_mix")) - expected) < 0.5