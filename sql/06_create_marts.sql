-- =====================================================================
-- Day 6: marts (business-ready tables and views)
-- Source: core.*      Target: marts.*
-- Revenue = item price on orders that are NOT canceled or unavailable,
-- purchased inside the analysis window (Jan 2017 to Aug 2018).
-- Run after 05_create_facts.sql. Safe to re-run.
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS marts;

DROP VIEW IF EXISTS marts.kpi_summary CASCADE;
DROP VIEW IF EXISTS marts.payment_mix CASCADE;
DROP MATERIALIZED VIEW IF EXISTS marts.seller_scorecard CASCADE;
DROP MATERIALIZED VIEW IF EXISTS marts.cohort_retention CASCADE;
DROP MATERIALIZED VIEW IF EXISTS marts.customer_rfm CASCADE;
DROP VIEW IF EXISTS marts.state_delivery CASCADE;
DROP VIEW IF EXISTS marts.category_pareto CASCADE;
DROP VIEW IF EXISTS marts.monthly_sales CASCADE;
DROP VIEW IF EXISTS marts.v_sales_orders CASCADE;
DROP VIEW IF EXISTS marts.v_sales_items CASCADE;

-- ---------- helper views: the single definition of a "valid sale" -------
CREATE VIEW marts.v_sales_items AS
SELECT f.order_id, f.order_item_id, d.date AS purchase_date, d.year_month, d.month_start,
       f.customer_key, f.product_key, f.seller_key, p.category_en, f.price, f.freight_value
FROM core.fact_order_items f
JOIN core.dim_date d     ON d.date_key = f.purchase_date_key
JOIN core.dim_products p ON p.product_key = f.product_key
WHERE d.in_analysis_window
  AND f.order_status NOT IN ('canceled', 'unavailable');

CREATE VIEW marts.v_sales_orders AS
SELECT o.order_id, o.customer_key, d.date AS purchase_date, d.year_month, d.month_start,
       o.item_count, o.item_revenue, o.freight_total, o.is_delivered, o.is_late,
       o.delivery_days, o.delay_days
FROM core.fact_orders o
JOIN core.dim_date d ON d.date_key = o.purchase_date_key
WHERE d.in_analysis_window
  AND o.order_status NOT IN ('canceled', 'unavailable')
  AND o.item_count > 0;

-- ---------- 1. monthly sales with growth and moving average -------------
CREATE VIEW marts.monthly_sales AS
WITH m AS (
    SELECT month_start, year_month,
           sum(price)                    AS revenue,
           sum(freight_value)            AS freight,
           count(*)                      AS items,
           count(DISTINCT order_id)      AS orders,
           count(DISTINCT customer_key)  AS customers
    FROM marts.v_sales_items
    GROUP BY month_start, year_month
)
SELECT month_start, year_month, revenue, freight, items, orders, customers,
       round(revenue / orders, 2)                                              AS aov,
       revenue - lag(revenue) OVER w                                           AS mom_change,
       round(100.0 * (revenue - lag(revenue) OVER w) / NULLIF(lag(revenue) OVER w, 0), 1) AS mom_pct,
       round(avg(revenue) OVER (ORDER BY month_start ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS revenue_ma3,
       round(100.0 * (revenue - lag(revenue, 12) OVER w) / NULLIF(lag(revenue, 12) OVER w, 0), 1) AS yoy_pct
FROM m
WINDOW w AS (ORDER BY month_start);

-- ---------- 2. Pareto (80/20) by product category -----------------------
CREATE VIEW marts.category_pareto AS
WITH c AS (
    SELECT category_en, sum(price) AS revenue, count(*) AS items, count(DISTINCT order_id) AS orders
    FROM marts.v_sales_items GROUP BY category_en
), t AS (
    SELECT c.*, 100.0 * revenue / sum(revenue) OVER () AS share
    FROM c
), r AS (
    SELECT t.*, sum(share) OVER (ORDER BY revenue DESC, category_en
                                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cum
    FROM t
)
SELECT row_number() OVER (ORDER BY revenue DESC, category_en) AS rank,
       category_en, revenue, items, orders,
       round(share, 2) AS share_pct,
       round(cum, 2)   AS cumulative_pct,
       CASE WHEN cum - share < 80 THEN 'A' WHEN cum - share < 95 THEN 'B' ELSE 'C' END AS abc_class
FROM r;

-- ---------- 3. delivery performance by customer state -------------------
CREATE VIEW marts.state_delivery AS
SELECT c.state_code, c.state_name, c.region,
       count(*)                                  AS delivered_orders,
       round(sum(o.item_revenue), 2)             AS revenue,
       round(avg(o.delivery_days), 2)            AS avg_delivery_days,
       round(avg(o.delay_days), 2)               AS avg_delay_days,
       round(100.0 * avg(o.is_late::int), 2)     AS late_rate_pct,
       round(avg(o.freight_total), 2)            AS avg_freight,
       round(avg(r.review_score), 2)             AS avg_review
FROM core.fact_orders o
JOIN core.dim_date d       ON d.date_key = o.purchase_date_key
JOIN core.dim_customers c  ON c.customer_key = o.customer_key
LEFT JOIN core.fact_reviews r ON r.order_id = o.order_id
WHERE o.is_delivered AND d.in_analysis_window
GROUP BY c.state_code, c.state_name, c.region;

-- ---------- 4. customer RFM segmentation --------------------------------
-- Snapshot date = 2018-08-31. Recency and Monetary use NTILE(5).
-- Frequency uses fixed rules because about 97 percent of customers bought once:
-- NTILE would split identical values into different groups.
CREATE MATERIALIZED VIEW marts.customer_rfm AS
WITH base AS (
    SELECT customer_key,
           max(purchase_date)  AS last_purchase,
           count(*)            AS frequency,
           sum(item_revenue)   AS monetary
    FROM marts.v_sales_orders
    GROUP BY customer_key
), scored AS (
    SELECT b.*,
           (DATE '2018-08-31' - b.last_purchase) AS recency_days,
           ntile(5) OVER (ORDER BY (DATE '2018-08-31' - b.last_purchase) DESC, b.customer_key) AS r_score,
           CASE WHEN b.frequency = 1 THEN 1 WHEN b.frequency = 2 THEN 3 ELSE 5 END           AS f_score,
           ntile(5) OVER (ORDER BY b.monetary, b.customer_key)                               AS m_score
    FROM base b
)
SELECT s.customer_key, c.state_code, s.last_purchase, s.recency_days, s.frequency,
       round(s.monetary, 2) AS monetary, s.r_score, s.f_score, s.m_score,
       CASE WHEN s.frequency >= 2 AND s.r_score >= 3 THEN 'Loyal repeat'
            WHEN s.frequency >= 2                    THEN 'Lapsed repeat'
            WHEN s.r_score >= 4 AND s.m_score >= 4   THEN 'New high value'
            WHEN s.r_score >= 4                      THEN 'New customer'
            WHEN s.r_score = 3                       THEN 'Cooling'
            WHEN s.m_score >= 4                      THEN 'Lost high value'
            ELSE 'Lost' END AS segment
FROM scored s
JOIN core.dim_customers c ON c.customer_key = s.customer_key;
CREATE UNIQUE INDEX ON marts.customer_rfm (customer_key);
CREATE INDEX ON marts.customer_rfm (segment);

-- ---------- 5. cohort retention by first purchase month -----------------
CREATE MATERIALIZED VIEW marts.cohort_retention AS
WITH orders_all AS (
    SELECT o.customer_key, d.month_start
    FROM core.fact_orders o
    JOIN core.dim_date d ON d.date_key = o.purchase_date_key
    WHERE o.order_status NOT IN ('canceled', 'unavailable') AND o.item_count > 0
    GROUP BY o.customer_key, d.month_start
), first_month AS (
    SELECT customer_key, min(month_start) AS cohort_month FROM orders_all GROUP BY customer_key
), act AS (
    SELECT f.cohort_month,
           ((extract(year FROM o.month_start) - extract(year FROM f.cohort_month)) * 12
            + extract(month FROM o.month_start) - extract(month FROM f.cohort_month))::int AS months_since,
           count(DISTINCT o.customer_key) AS active_customers
    FROM orders_all o
    JOIN first_month f USING (customer_key)
    WHERE f.cohort_month BETWEEN DATE '2017-01-01' AND DATE '2018-08-01'
      AND o.month_start <= DATE '2018-08-01'
    GROUP BY 1, 2
), size AS (
    SELECT cohort_month, count(*) AS cohort_size FROM first_month GROUP BY cohort_month
)
SELECT a.cohort_month, to_char(a.cohort_month, 'YYYY-MM') AS cohort, a.months_since,
       s.cohort_size, a.active_customers,
       round(100.0 * a.active_customers / s.cohort_size, 2) AS retention_pct
FROM act a JOIN size s USING (cohort_month);
CREATE UNIQUE INDEX ON marts.cohort_retention (cohort_month, months_since);

-- ---------- 6. seller scorecard and risk score --------------------------
-- An order counts for every seller who has an item on it.
-- Risk score (0 to 100) = 40 percent late rate (capped at 20), 35 percent low-review rate
-- (reviews of 1 or 2, capped at 25), 25 percent cancel rate (capped at 5).
-- Sellers with fewer than 20 orders are not scored.
CREATE MATERIALIZED VIEW marts.seller_scorecard AS
WITH so AS (
    SELECT DISTINCT i.seller_key, i.order_id
    FROM core.fact_order_items i
    JOIN core.dim_date d ON d.date_key = i.purchase_date_key
    WHERE d.in_analysis_window
), sx AS (
    SELECT so.seller_key, so.order_id, o.order_status, o.is_delivered, o.is_late, r.review_score
    FROM so
    JOIN core.fact_orders o ON o.order_id = so.order_id
    LEFT JOIN core.fact_reviews r ON r.order_id = so.order_id
), agg AS (
    SELECT seller_key,
           count(*)                                                                 AS orders_total,
           count(*) FILTER (WHERE order_status IN ('canceled', 'unavailable'))      AS orders_cancelled,
           count(*) FILTER (WHERE is_delivered)                                     AS delivered,
           count(*) FILTER (WHERE is_late)                                          AS late,
           count(review_score)                                                      AS reviewed,
           count(*) FILTER (WHERE review_score <= 2)                                AS low_reviews,
           avg(review_score)                                                        AS avg_review
    FROM sx GROUP BY seller_key
), rev AS (
    SELECT seller_key, sum(price) AS revenue FROM marts.v_sales_items GROUP BY seller_key
), calc AS (
    SELECT a.*, COALESCE(r.revenue, 0) AS revenue,
           a.late::numeric / NULLIF(a.delivered, 0)             AS late_rate,
           a.low_reviews::numeric / NULLIF(a.reviewed, 0)       AS low_review_rate,
           a.orders_cancelled::numeric / a.orders_total         AS cancel_rate
    FROM agg a LEFT JOIN rev r USING (seller_key)
)
SELECT c.seller_key, s.seller_label, s.state_code, s.region,
       c.orders_total, c.orders_cancelled, c.delivered,
       round(c.revenue, 2)                    AS revenue,
       round(100 * c.late_rate, 2)            AS late_rate_pct,
       round(c.avg_review, 2)                 AS avg_review,
       round(100 * c.low_review_rate, 2)      AS low_review_rate_pct,
       round(100 * c.cancel_rate, 2)          AS cancel_rate_pct,
       CASE WHEN c.orders_total >= 20 THEN
            round(100 * (0.40 * least(COALESCE(c.late_rate, 0) / 0.20, 1)
                       + 0.35 * least(COALESCE(c.low_review_rate, 0) / 0.25, 1)
                       + 0.25 * least(c.cancel_rate / 0.05, 1)), 1) END AS risk_score,
       CASE WHEN c.orders_total < 20 THEN 'Not scored'
            WHEN 100 * (0.40 * least(COALESCE(c.late_rate, 0) / 0.20, 1)
                      + 0.35 * least(COALESCE(c.low_review_rate, 0) / 0.25, 1)
                      + 0.25 * least(c.cancel_rate / 0.05, 1)) >= 50 THEN 'High'
            WHEN 100 * (0.40 * least(COALESCE(c.late_rate, 0) / 0.20, 1)
                      + 0.35 * least(COALESCE(c.low_review_rate, 0) / 0.25, 1)
                      + 0.25 * least(c.cancel_rate / 0.05, 1)) >= 25 THEN 'Medium'
            ELSE 'Low' END AS risk_tier
FROM calc c JOIN core.dim_sellers s ON s.seller_key = c.seller_key;
CREATE UNIQUE INDEX ON marts.seller_scorecard (seller_key);
CREATE INDEX ON marts.seller_scorecard (risk_tier);

-- ---------- 7. payment mix -----------------------------------------------
CREATE VIEW marts.payment_mix AS
SELECT p.payment_type,
       count(*)                                    AS payments,
       round(sum(p.payment_value), 2)              AS payment_value,
       round(100.0 * sum(p.payment_value) / sum(sum(p.payment_value)) OVER (), 2) AS share_pct,
       round(avg(p.installments), 2)               AS avg_installments
FROM core.fact_payments p
JOIN core.fact_orders o ON o.order_id = p.order_id
JOIN core.dim_date d    ON d.date_key = p.purchase_date_key
WHERE d.in_analysis_window AND o.order_status NOT IN ('canceled', 'unavailable')
GROUP BY p.payment_type;

-- ---------- 8. one-row KPI summary for the executive page and the agent --
CREATE VIEW marts.kpi_summary AS
SELECT (SELECT sum(price) FROM marts.v_sales_items)                                  AS revenue,
       (SELECT count(DISTINCT order_id) FROM marts.v_sales_items)                    AS orders,
       round((SELECT sum(price) FROM marts.v_sales_items)
             / (SELECT count(DISTINCT order_id) FROM marts.v_sales_items), 2)        AS aov,
       (SELECT count(*) FROM marts.customer_rfm)                                     AS customers,
       round(100.0 * (SELECT count(*) FROM marts.customer_rfm WHERE frequency >= 2)
             / (SELECT count(*) FROM marts.customer_rfm), 2)                         AS repeat_rate_pct,
       (SELECT round(avg(delivery_days), 2) FROM marts.v_sales_orders WHERE is_delivered) AS avg_delivery_days,
       (SELECT round(100.0 * avg(is_late::int), 2) FROM marts.v_sales_orders WHERE is_delivered) AS late_rate_pct,
       (SELECT round(avg(r.review_score), 2) FROM marts.v_sales_orders o
          JOIN core.fact_reviews r ON r.order_id = o.order_id)                       AS avg_review;