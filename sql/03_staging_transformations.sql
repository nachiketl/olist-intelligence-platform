-- =====================================================================
-- Stage 2: staging layer (typed, deduplicated, enriched)
-- Source: raw.* (text, immutable)   Target: staging.*
-- Safe to re-run: every table is dropped and rebuilt.
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS audit.dq_issues (
    id           serial PRIMARY KEY,
    checked_at   timestamptz DEFAULT now(),
    layer        text,
    table_name   text,
    check_name   text,
    severity     text,
    issue_count  bigint,
    total_rows   bigint,
    note         text
);
DELETE FROM audit.dq_issues WHERE layer = 'raw->staging';

-- ---------- category translation (adds the 2 missing categories) ------
DROP TABLE IF EXISTS staging.category_translation CASCADE;
CREATE TABLE staging.category_translation AS
SELECT trim(product_category_name) AS category_pt,
       trim(product_category_name_english) AS category_en
FROM raw.product_category_name_translation;

INSERT INTO staging.category_translation (category_pt, category_en)
SELECT v.category_pt, v.category_en
FROM (VALUES
    ('pc_gamer', 'pc_gamer'),
    ('portateis_cozinha_e_preparadores_de_alimentos', 'portable_kitchen_food_preparers')
) AS v(category_pt, category_en)
WHERE v.category_pt NOT IN (SELECT category_pt FROM staging.category_translation);
ALTER TABLE staging.category_translation ADD PRIMARY KEY (category_pt);

-- ---------- customers --------------------------------------------------
DROP TABLE IF EXISTS staging.customers CASCADE;
CREATE TABLE staging.customers AS
SELECT customer_id,
       customer_unique_id,
       lpad(customer_zip_code_prefix, 5, '0') AS zip_prefix,
       lower(trim(customer_city))             AS city,
       upper(trim(customer_state))            AS state
FROM raw.customers;
ALTER TABLE staging.customers ADD PRIMARY KEY (customer_id);

-- ---------- sellers ----------------------------------------------------
DROP TABLE IF EXISTS staging.sellers CASCADE;
CREATE TABLE staging.sellers AS
SELECT seller_id,
       lpad(seller_zip_code_prefix, 5, '0') AS zip_prefix,
       lower(trim(seller_city))             AS city,
       upper(trim(seller_state))            AS state
FROM raw.sellers;
ALTER TABLE staging.sellers ADD PRIMARY KEY (seller_id);

-- ---------- geolocation: one row per zip prefix ------------------------
DROP TABLE IF EXISTS staging.geolocation CASCADE;
CREATE TABLE staging.geolocation AS
SELECT lpad(geolocation_zip_code_prefix, 5, '0')                       AS zip_prefix,
       avg(geolocation_lat::numeric)::numeric(9,6)                     AS lat,
       avg(geolocation_lng::numeric)::numeric(9,6)                     AS lng,
       mode() WITHIN GROUP (ORDER BY upper(trim(geolocation_state)))   AS state,
       mode() WITHIN GROUP (ORDER BY lower(trim(geolocation_city)))    AS city,
       count(*)                                                        AS source_rows
FROM raw.geolocation
GROUP BY 1;
ALTER TABLE staging.geolocation ADD PRIMARY KEY (zip_prefix);

-- ---------- products ---------------------------------------------------
DROP TABLE IF EXISTS staging.products CASCADE;
CREATE TABLE staging.products AS
SELECT p.product_id,
       COALESCE(NULLIF(trim(p.product_category_name), ''), 'unknown') AS category_pt,
       COALESCE(t.category_en, 'unknown')                             AS category_en,
       NULLIF(p.product_name_lenght, '')::int          AS name_length,
       NULLIF(p.product_description_lenght, '')::int   AS description_length,
       NULLIF(p.product_photos_qty, '')::int           AS photos_qty,
       NULLIF(p.product_weight_g, '')::numeric         AS weight_g,
       NULLIF(p.product_length_cm, '')::numeric        AS length_cm,
       NULLIF(p.product_height_cm, '')::numeric        AS height_cm,
       NULLIF(p.product_width_cm, '')::numeric         AS width_cm
FROM raw.products p
LEFT JOIN staging.category_translation t
       ON t.category_pt = trim(p.product_category_name);
ALTER TABLE staging.products ADD PRIMARY KEY (product_id);

-- ---------- orders (+ delivery metrics) --------------------------------
DROP TABLE IF EXISTS staging.orders CASCADE;
CREATE TABLE staging.orders AS
WITH t AS (
    SELECT order_id,
           customer_id,
           lower(trim(order_status))                             AS order_status,
           NULLIF(order_purchase_timestamp, '')::timestamp       AS purchase_ts,
           NULLIF(order_approved_at, '')::timestamp              AS approved_ts,
           NULLIF(order_delivered_carrier_date, '')::timestamp   AS carrier_ts,
           NULLIF(order_delivered_customer_date, '')::timestamp  AS delivered_ts,
           NULLIF(order_estimated_delivery_date, '')::timestamp  AS estimated_ts
    FROM raw.orders
)
SELECT t.*,
       (order_status = 'delivered' AND delivered_ts IS NOT NULL) AS is_delivered,
       CASE WHEN order_status = 'delivered' AND delivered_ts IS NOT NULL
            THEN round(extract(epoch FROM delivered_ts - purchase_ts) / 86400.0, 2) END AS delivery_days,
       CASE WHEN order_status = 'delivered' AND delivered_ts IS NOT NULL
            THEN round(extract(epoch FROM delivered_ts - estimated_ts) / 86400.0, 2) END AS delay_days,
       CASE WHEN order_status = 'delivered' AND delivered_ts IS NOT NULL
            THEN delivered_ts > estimated_ts END AS is_late
FROM t;
ALTER TABLE staging.orders ADD PRIMARY KEY (order_id);

-- ---------- order items ------------------------------------------------
DROP TABLE IF EXISTS staging.order_items CASCADE;
CREATE TABLE staging.order_items AS
SELECT order_id,
       order_item_id::int                                  AS order_item_id,
       product_id,
       seller_id,
       NULLIF(shipping_limit_date, '')::timestamp          AS shipping_limit_ts,
       price::numeric(12,2)                                AS price,
       freight_value::numeric(12,2)                        AS freight_value
FROM raw.order_items;
ALTER TABLE staging.order_items ADD PRIMARY KEY (order_id, order_item_id);

-- ---------- payments ---------------------------------------------------
DROP TABLE IF EXISTS staging.order_payments CASCADE;
CREATE TABLE staging.order_payments AS
SELECT order_id,
       payment_sequential::int       AS payment_sequential,
       lower(trim(payment_type))     AS payment_type,
       payment_installments::int     AS installments,
       payment_value::numeric(12,2)  AS payment_value
FROM raw.order_payments;
ALTER TABLE staging.order_payments ADD PRIMARY KEY (order_id, payment_sequential);

-- ---------- reviews: keep the latest review per order ------------------
DROP TABLE IF EXISTS staging.order_reviews CASCADE;
CREATE TABLE staging.order_reviews AS
SELECT DISTINCT ON (order_id)
       order_id,
       review_id,
       review_score,
       has_comment,
       review_creation_ts,
       review_answer_ts,
       count(*) OVER (PARTITION BY order_id) AS reviews_for_order
FROM (
    SELECT order_id,
           review_id,
           review_score::smallint                                 AS review_score,
           (NULLIF(trim(review_comment_message), '') IS NOT NULL) AS has_comment,
           NULLIF(review_creation_date, '')::timestamp            AS review_creation_ts,
           NULLIF(review_answer_timestamp, '')::timestamp         AS review_answer_ts
    FROM raw.order_reviews
) r
ORDER BY order_id, review_creation_ts DESC, review_answer_ts DESC, review_id;
ALTER TABLE staging.order_reviews ADD PRIMARY KEY (order_id);

-- ---------- data-quality issue log -------------------------------------
INSERT INTO audit.dq_issues (layer, table_name, check_name, severity, issue_count, total_rows, note)
SELECT 'raw->staging', 'geolocation', 'fully duplicated rows', 'medium',
       (SELECT count(*) FROM raw.geolocation) - (SELECT count(*) FROM (SELECT DISTINCT * FROM raw.geolocation) d),
       (SELECT count(*) FROM raw.geolocation),
       'Collapsed to one row per zip prefix in staging.geolocation';

INSERT INTO audit.dq_issues (layer, table_name, check_name, severity, issue_count, total_rows, note)
SELECT 'raw->staging', 'orders', 'orders without order items', 'medium',
       count(*), (SELECT count(*) FROM staging.orders),
       'Mostly unavailable or canceled orders; excluded from item-based revenue'
FROM staging.orders o WHERE NOT EXISTS (SELECT 1 FROM staging.order_items i WHERE i.order_id = o.order_id);

INSERT INTO audit.dq_issues (layer, table_name, check_name, severity, issue_count, total_rows, note)
SELECT 'raw->staging', 'orders', 'missing approval timestamp', 'low',
       count(*) FILTER (WHERE approved_ts IS NULL), count(*), 'Kept as NULL'
FROM staging.orders;

INSERT INTO audit.dq_issues (layer, table_name, check_name, severity, issue_count, total_rows, note)
SELECT 'raw->staging', 'orders', 'delivered status without delivery date', 'high',
       count(*) FILTER (WHERE order_status = 'delivered' AND delivered_ts IS NULL), count(*),
       'Excluded from delivery metrics (is_delivered = false)'
FROM staging.orders;

INSERT INTO audit.dq_issues (layer, table_name, check_name, severity, issue_count, total_rows, note)
SELECT 'raw->staging', 'orders', 'delivered before purchase', 'high',
       count(*) FILTER (WHERE delivered_ts < purchase_ts), count(*), 'Impossible timeline'
FROM staging.orders;

INSERT INTO audit.dq_issues (layer, table_name, check_name, severity, issue_count, total_rows, note)
SELECT 'raw->staging', 'order_items', 'shipping limit date after 2019', 'low',
       count(*) FILTER (WHERE shipping_limit_ts >= '2019-01-01'), count(*), 'Outlier dates; flagged, not used in KPIs'
FROM staging.order_items;

INSERT INTO audit.dq_issues (layer, table_name, check_name, severity, issue_count, total_rows, note)
SELECT 'raw->staging', 'order_items', 'zero or negative price', 'high',
       count(*) FILTER (WHERE price <= 0), count(*), 'Should be 0'
FROM staging.order_items;

INSERT INTO audit.dq_issues (layer, table_name, check_name, severity, issue_count, total_rows, note)
SELECT 'raw->staging', 'products', 'missing category', 'medium',
       count(*) FILTER (WHERE category_pt = 'unknown'), count(*), 'Labelled unknown'
FROM staging.products;

INSERT INTO audit.dq_issues (layer, table_name, check_name, severity, issue_count, total_rows, note)
SELECT 'raw->staging', 'category_translation', 'categories missing from source translation', 'low',
       count(DISTINCT trim(p.product_category_name)), (SELECT count(*) FROM staging.category_translation),
       'Added manually in staging.category_translation'
FROM raw.products p
WHERE NULLIF(trim(p.product_category_name), '') IS NOT NULL
  AND trim(p.product_category_name) NOT IN
      (SELECT trim(product_category_name) FROM raw.product_category_name_translation);

INSERT INTO audit.dq_issues (layer, table_name, check_name, severity, issue_count, total_rows, note)
SELECT 'raw->staging', 'order_reviews', 'repeated review_id', 'medium',
       count(*) - count(DISTINCT review_id), count(*), 'Same review_id used on several orders'
FROM raw.order_reviews;

INSERT INTO audit.dq_issues (layer, table_name, check_name, severity, issue_count, total_rows, note)
SELECT 'raw->staging', 'order_reviews', 'orders with more than one review', 'medium',
       count(*) FILTER (WHERE reviews_for_order > 1), count(*), 'Latest review kept per order'
FROM staging.order_reviews;

INSERT INTO audit.dq_issues (layer, table_name, check_name, severity, issue_count, total_rows, note)
SELECT 'raw->staging', 'order_reviews', 'review score outside 1-5', 'high',
       count(*) FILTER (WHERE review_score NOT BETWEEN 1 AND 5), count(*), 'Should be 0'
FROM staging.order_reviews;

INSERT INTO audit.dq_issues (layer, table_name, check_name, severity, issue_count, total_rows, note)
SELECT 'raw->staging', 'order_payments', 'payments differ from items + freight by more than 1', 'medium',
       count(*) FILTER (WHERE abs(p.paid - i.billed) > 1), count(*),
       'Vouchers, rounding and installment interest; reconcile within tolerance'
FROM (SELECT order_id, sum(payment_value) AS paid FROM staging.order_payments GROUP BY 1) p
JOIN (SELECT order_id, sum(price + freight_value) AS billed FROM staging.order_items GROUP BY 1) i
  USING (order_id);