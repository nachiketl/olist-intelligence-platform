-- =====================================================================
-- Day 4: dimension tables (core schema)
-- Source: staging.*      Target: core.dim_*
-- Every dimension has a surrogate key, a natural key and an 'Unknown' member (key -1).
-- Safe to re-run: every table is dropped and rebuilt.
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS core;

-- ---------- dim_state: Brazilian states and regions ---------------------
DROP TABLE IF EXISTS core.dim_state CASCADE;
CREATE TABLE core.dim_state AS
SELECT * FROM (VALUES
  ('AC','Acre','North'),('AL','Alagoas','Northeast'),('AP','Amapa','North'),('AM','Amazonas','North'),
  ('BA','Bahia','Northeast'),('CE','Ceara','Northeast'),('DF','Distrito Federal','Central-West'),
  ('ES','Espirito Santo','Southeast'),('GO','Goias','Central-West'),('MA','Maranhao','Northeast'),
  ('MT','Mato Grosso','Central-West'),('MS','Mato Grosso do Sul','Central-West'),('MG','Minas Gerais','Southeast'),
  ('PA','Para','North'),('PB','Paraiba','Northeast'),('PR','Parana','South'),('PE','Pernambuco','Northeast'),
  ('PI','Piaui','Northeast'),('RJ','Rio de Janeiro','Southeast'),('RN','Rio Grande do Norte','Northeast'),
  ('RS','Rio Grande do Sul','South'),('RO','Rondonia','North'),('RR','Roraima','North'),
  ('SC','Santa Catarina','South'),('SP','Sao Paulo','Southeast'),('SE','Sergipe','Northeast'),
  ('TO','Tocantins','North')
) AS s(state_code, state_name, region);
ALTER TABLE core.dim_state ADD PRIMARY KEY (state_code);

-- ---------- dim_date: one row per calendar day --------------------------
DROP TABLE IF EXISTS core.dim_date CASCADE;
CREATE TABLE core.dim_date AS
WITH bounds AS (
    SELECT date_trunc('year', min(d))::date                               AS d0,
           (date_trunc('year', max(d)) + interval '1 year - 1 day')::date AS d1
    FROM (
        SELECT purchase_ts::date AS d FROM staging.orders
        UNION ALL SELECT delivered_ts::date FROM staging.orders
        UNION ALL SELECT estimated_ts::date FROM staging.orders
        UNION ALL SELECT review_creation_ts::date FROM staging.order_reviews
        UNION ALL SELECT review_answer_ts::date FROM staging.order_reviews
    ) x
    WHERE d IS NOT NULL
), days AS (
    SELECT generate_series(d0, d1, interval '1 day')::date AS date FROM bounds
)
SELECT to_char(date, 'YYYYMMDD')::int          AS date_key,
       date,
       extract(year    FROM date)::int         AS year,
       extract(quarter FROM date)::int         AS quarter,
       extract(month   FROM date)::int         AS month,
       to_char(date, 'FMMonth')                AS month_name,
       to_char(date, 'Mon')                    AS month_short,
       to_char(date, 'YYYY-MM')                AS year_month,
       date_trunc('month', date)::date         AS month_start,
       extract(week    FROM date)::int         AS iso_week,
       extract(day     FROM date)::int         AS day_of_month,
       extract(isodow  FROM date)::int         AS day_of_week,
       to_char(date, 'FMDay')                  AS day_name,
       (extract(isodow FROM date) >= 6)        AS is_weekend,
       (date BETWEEN DATE '2017-01-01' AND DATE '2018-08-31') AS in_analysis_window
FROM days;
ALTER TABLE core.dim_date ADD PRIMARY KEY (date_key);

-- ---------- dim_geography: one row per zip prefix -----------------------
DROP TABLE IF EXISTS core.dim_geography CASCADE;
CREATE TABLE core.dim_geography AS
SELECT row_number() OVER (ORDER BY g.zip_prefix)::int AS geography_key,
       g.zip_prefix,
       g.city,
       g.state                                       AS state_code,
       COALESCE(s.state_name, 'Unknown')             AS state_name,
       COALESCE(s.region, 'Unknown')                 AS region,
       g.lat,
       g.lng
FROM staging.geolocation g
LEFT JOIN core.dim_state s ON s.state_code = g.state;
INSERT INTO core.dim_geography (geography_key, zip_prefix, city, state_code, state_name, region)
VALUES (-1, 'unknown', 'unknown', 'XX', 'Unknown', 'Unknown');
ALTER TABLE core.dim_geography ADD PRIMARY KEY (geography_key);
CREATE UNIQUE INDEX ON core.dim_geography (zip_prefix);

-- ---------- dim_customers: one row per person (customer_unique_id) ------
-- Location comes from the person's most recent order.
DROP TABLE IF EXISTS core.dim_customers CASCADE;
CREATE TABLE core.dim_customers AS
WITH latest AS (
    SELECT DISTINCT ON (c.customer_unique_id)
           c.customer_unique_id, c.zip_prefix, c.city, c.state
    FROM staging.customers c
    LEFT JOIN staging.orders o USING (customer_id)
    ORDER BY c.customer_unique_id, o.purchase_ts DESC NULLS LAST, c.customer_id
), first_order AS (
    SELECT c.customer_unique_id, min(o.purchase_ts)::date AS first_order_date
    FROM staging.customers c JOIN staging.orders o USING (customer_id)
    GROUP BY 1
)
SELECT row_number() OVER (ORDER BY l.customer_unique_id)::int AS customer_key,
       l.customer_unique_id,
       l.zip_prefix,
       COALESCE(g.geography_key, -1)                  AS geography_key,
       l.city,
       l.state                                        AS state_code,
       COALESCE(s.state_name, 'Unknown')              AS state_name,
       COALESCE(s.region, 'Unknown')                  AS region,
       f.first_order_date
FROM latest l
LEFT JOIN first_order f USING (customer_unique_id)
LEFT JOIN core.dim_state s ON s.state_code = l.state
LEFT JOIN core.dim_geography g ON g.zip_prefix = l.zip_prefix;
INSERT INTO core.dim_customers (customer_key, customer_unique_id, zip_prefix, geography_key, city, state_code, state_name, region)
VALUES (-1, 'unknown', 'unknown', -1, 'unknown', 'XX', 'Unknown', 'Unknown');
ALTER TABLE core.dim_customers ADD PRIMARY KEY (customer_key);
CREATE UNIQUE INDEX ON core.dim_customers (customer_unique_id);

-- ---------- dim_sellers --------------------------------------------------
DROP TABLE IF EXISTS core.dim_sellers CASCADE;
CREATE TABLE core.dim_sellers AS
SELECT row_number() OVER (ORDER BY se.seller_id)::int AS seller_key,
       se.seller_id,
       'S-' || left(se.seller_id, 8)                  AS seller_label,
       se.zip_prefix,
       COALESCE(g.geography_key, -1)                  AS geography_key,
       se.city,
       se.state                                       AS state_code,
       COALESCE(s.state_name, 'Unknown')              AS state_name,
       COALESCE(s.region, 'Unknown')                  AS region
FROM staging.sellers se
LEFT JOIN core.dim_state s ON s.state_code = se.state
LEFT JOIN core.dim_geography g ON g.zip_prefix = se.zip_prefix;
INSERT INTO core.dim_sellers (seller_key, seller_id, seller_label, zip_prefix, geography_key, city, state_code, state_name, region)
VALUES (-1, 'unknown', 'S-unknown', 'unknown', -1, 'unknown', 'XX', 'Unknown', 'Unknown');
ALTER TABLE core.dim_sellers ADD PRIMARY KEY (seller_key);
CREATE UNIQUE INDEX ON core.dim_sellers (seller_id);

-- ---------- dim_products -------------------------------------------------
DROP TABLE IF EXISTS core.dim_products CASCADE;
CREATE TABLE core.dim_products AS
SELECT row_number() OVER (ORDER BY p.product_id)::int AS product_key,
       p.product_id,
       'P-' || left(p.product_id, 10)                 AS product_label,
       p.category_en,
       p.category_pt,
       p.name_length,
       p.description_length,
       p.photos_qty,
       p.weight_g,
       p.length_cm * p.height_cm * p.width_cm         AS volume_cm3,
       CASE WHEN p.weight_g IS NULL    THEN 'Unknown'
            WHEN p.weight_g < 500      THEN '1. Light (under 0.5 kg)'
            WHEN p.weight_g < 2000     THEN '2. Medium (0.5 to 2 kg)'
            WHEN p.weight_g < 10000    THEN '3. Heavy (2 to 10 kg)'
            ELSE                            '4. Very heavy (10 kg and over)' END AS weight_band
FROM staging.products p;
INSERT INTO core.dim_products (product_key, product_id, product_label, category_en, category_pt, weight_band)
VALUES (-1, 'unknown', 'P-unknown', 'unknown', 'unknown', 'Unknown');
ALTER TABLE core.dim_products ADD PRIMARY KEY (product_key);
CREATE UNIQUE INDEX ON core.dim_products (product_id);
