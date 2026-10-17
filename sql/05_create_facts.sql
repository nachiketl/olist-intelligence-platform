-- =====================================================================
-- Day 5: fact tables (core schema)
-- Source: staging.* + core.dim_*      Target: core.fact_*
-- Four facts with four different grains. They are NEVER joined to each other
-- and then summed (that would double count). Run after 04_create_dimensions.sql.
-- Safe to re-run: every table is dropped and rebuilt.
-- =====================================================================

-- ---------- fact_order_items: one row per order item --------------------
DROP TABLE IF EXISTS core.fact_order_items CASCADE;
CREATE TABLE core.fact_order_items AS
SELECT i.order_id,
       i.order_item_id,
       to_char(o.purchase_ts, 'YYYYMMDD')::int       AS purchase_date_key,
       COALESCE(dc.customer_key, -1)                 AS customer_key,
       COALESCE(dp.product_key, -1)                  AS product_key,
       COALESCE(ds.seller_key, -1)                   AS seller_key,
       o.order_status,
       i.price,
       i.freight_value,
       i.price + i.freight_value                     AS item_total
FROM staging.order_items i
JOIN staging.orders o        ON o.order_id = i.order_id
JOIN staging.customers c     ON c.customer_id = o.customer_id
LEFT JOIN core.dim_customers dc ON dc.customer_unique_id = c.customer_unique_id
LEFT JOIN core.dim_products  dp ON dp.product_id = i.product_id
LEFT JOIN core.dim_sellers   ds ON ds.seller_id = i.seller_id;
ALTER TABLE core.fact_order_items ADD PRIMARY KEY (order_id, order_item_id);
CREATE INDEX ON core.fact_order_items (purchase_date_key);
CREATE INDEX ON core.fact_order_items (customer_key);
CREATE INDEX ON core.fact_order_items (product_key);
CREATE INDEX ON core.fact_order_items (seller_key);

-- ---------- fact_orders: one row per order ------------------------------
-- Item and payment totals are summed BEFORE joining, so each order stays one row.
DROP TABLE IF EXISTS core.fact_orders CASCADE;
CREATE TABLE core.fact_orders AS
WITH items AS (
    SELECT order_id, count(*) AS item_count, sum(price) AS item_revenue, sum(freight_value) AS freight_total
    FROM staging.order_items GROUP BY order_id
), pays AS (
    SELECT order_id, count(*) AS payment_count, sum(payment_value) AS payment_total
    FROM staging.order_payments GROUP BY order_id
)
SELECT o.order_id,
       COALESCE(dc.customer_key, -1)                         AS customer_key,
       to_char(o.purchase_ts,  'YYYYMMDD')::int              AS purchase_date_key,
       to_char(o.approved_ts,  'YYYYMMDD')::int              AS approved_date_key,
       to_char(o.carrier_ts,   'YYYYMMDD')::int              AS carrier_date_key,
       to_char(o.delivered_ts, 'YYYYMMDD')::int              AS delivered_date_key,
       to_char(o.estimated_ts, 'YYYYMMDD')::int              AS estimated_date_key,
       o.order_status,
       o.is_delivered,
       o.is_late,
       o.delivery_days,
       o.delay_days,
       round(extract(epoch FROM o.approved_ts - o.purchase_ts) / 3600.0, 2) AS approval_hours,
       COALESCE(it.item_count, 0)                            AS item_count,
       COALESCE(it.item_revenue, 0)::numeric(12,2)           AS item_revenue,
       COALESCE(it.freight_total, 0)::numeric(12,2)          AS freight_total,
       COALESCE(pa.payment_count, 0)                         AS payment_count,
       COALESCE(pa.payment_total, 0)::numeric(12,2)          AS payment_total
FROM staging.orders o
JOIN staging.customers c        ON c.customer_id = o.customer_id
LEFT JOIN core.dim_customers dc ON dc.customer_unique_id = c.customer_unique_id
LEFT JOIN items it              ON it.order_id = o.order_id
LEFT JOIN pays pa               ON pa.order_id = o.order_id;
ALTER TABLE core.fact_orders ADD PRIMARY KEY (order_id);
CREATE INDEX ON core.fact_orders (purchase_date_key);
CREATE INDEX ON core.fact_orders (customer_key);
CREATE INDEX ON core.fact_orders (order_status);

-- ---------- fact_payments: one row per payment record -------------------
DROP TABLE IF EXISTS core.fact_payments CASCADE;
CREATE TABLE core.fact_payments AS
SELECT p.order_id,
       p.payment_sequential,
       to_char(o.purchase_ts, 'YYYYMMDD')::int       AS purchase_date_key,
       COALESCE(dc.customer_key, -1)                 AS customer_key,
       p.payment_type,
       p.installments,
       p.payment_value
FROM staging.order_payments p
JOIN staging.orders o        ON o.order_id = p.order_id
JOIN staging.customers c     ON c.customer_id = o.customer_id
LEFT JOIN core.dim_customers dc ON dc.customer_unique_id = c.customer_unique_id;
ALTER TABLE core.fact_payments ADD PRIMARY KEY (order_id, payment_sequential);
CREATE INDEX ON core.fact_payments (purchase_date_key);
CREATE INDEX ON core.fact_payments (payment_type);

-- ---------- fact_reviews: one row per order (latest review) -------------
DROP TABLE IF EXISTS core.fact_reviews CASCADE;
CREATE TABLE core.fact_reviews AS
SELECT r.order_id,
       r.review_id,
       COALESCE(dc.customer_key, -1)                 AS customer_key,
       to_char(r.review_creation_ts, 'YYYYMMDD')::int AS review_date_key,
       to_char(r.review_answer_ts,   'YYYYMMDD')::int AS answer_date_key,
       r.review_score,
       r.has_comment,
       r.reviews_for_order
FROM staging.order_reviews r
JOIN staging.orders o        ON o.order_id = r.order_id
JOIN staging.customers c     ON c.customer_id = o.customer_id
LEFT JOIN core.dim_customers dc ON dc.customer_unique_id = c.customer_unique_id;
ALTER TABLE core.fact_reviews ADD PRIMARY KEY (order_id);
CREATE INDEX ON core.fact_reviews (review_date_key);
CREATE INDEX ON core.fact_reviews (review_score);