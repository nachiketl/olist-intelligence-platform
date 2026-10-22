-- =====================================================================
-- Day 8: BI Views Schema for Power BI Import Mode
-- Provides clean, optimized ordinary views mapped specifically for Power BI models.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS bi;

-- 1. dim_date
DROP VIEW IF EXISTS bi.dim_date CASCADE;
CREATE VIEW bi.dim_date AS
SELECT 
    date_key,
    date,
    year,
    quarter,
    month,
    month_name,
    month_short,
    month_start,
    iso_week,
    day_of_week,
    day_name,
    is_weekend,
    in_analysis_window,
    year_month
FROM core.dim_date;

-- 2. dim_customer
DROP VIEW IF EXISTS bi.dim_customer CASCADE;
CREATE VIEW bi.dim_customer AS
SELECT 
    c.customer_key,
    c.customer_unique_id,
    c.city,
    c.state_code,
    c.state_name,
    c.region,
    c.first_order_date,
    r.segment AS rfm_segment
FROM core.dim_customers c
LEFT JOIN marts.customer_rfm r ON r.customer_key = c.customer_key;

-- 3. dim_product
DROP VIEW IF EXISTS bi.dim_product CASCADE;
CREATE VIEW bi.dim_product AS
SELECT 
    p.product_key,
    p.product_id,
    p.product_label,
    p.category_pt,
    COALESCE(p.category_en, 'Uncategorised') AS category_en,
    p.weight_g,
    p.weight_band,
    p.volume_cm3,
    cp.abc_class
FROM core.dim_products p
LEFT JOIN marts.category_pareto cp ON cp.category_en = p.category_en;

-- 4. dim_seller
DROP VIEW IF EXISTS bi.dim_seller CASCADE;
CREATE VIEW bi.dim_seller AS
SELECT 
    s.seller_key,
    s.seller_id,
    s.seller_label,
    s.city,
    s.state_code,
    s.state_name,
    s.region,
    sc.risk_score,
    COALESCE(sc.risk_tier, 'Not scored') AS risk_tier
FROM core.dim_sellers s
LEFT JOIN marts.seller_scorecard sc ON sc.seller_key = s.seller_key;

-- 5. fact_order_items
DROP VIEW IF EXISTS bi.fact_order_items CASCADE;
CREATE VIEW bi.fact_order_items AS
SELECT 
    i.order_id,
    i.order_item_id,
    i.purchase_date_key,
    i.customer_key,
    i.product_key,
    i.seller_key,
    i.price,
    i.freight_value,
    i.item_total,
    o.order_status,
    (o.order_status NOT IN ('canceled', 'unavailable')) AS is_valid_sale
FROM core.fact_order_items i
JOIN core.fact_orders o ON o.order_id = i.order_id;

-- 6. fact_orders
DROP VIEW IF EXISTS bi.fact_orders CASCADE;
CREATE VIEW bi.fact_orders AS
SELECT 
    o.order_id,
    o.customer_key,
    o.purchase_date_key,
    o.approved_date_key,
    o.carrier_date_key,
    o.delivered_date_key,
    o.estimated_date_key,
    o.order_status,
    o.is_delivered,
    o.is_late,
    o.delivery_days,
    o.delay_days,
    o.approval_hours,
    o.item_count,
    o.item_revenue,
    o.freight_total,
    o.payment_count,
    o.payment_total,
    r.review_score
FROM core.fact_orders o
LEFT JOIN core.fact_reviews r ON r.order_id = o.order_id;

-- 7. fact_payments
DROP VIEW IF EXISTS bi.fact_payments CASCADE;
CREATE VIEW bi.fact_payments AS
SELECT 
    order_id,
    payment_sequential,
    purchase_date_key,
    customer_key,
    payment_type,
    installments,
    payment_value
FROM core.fact_payments;

-- 8. target_monthly
DROP VIEW IF EXISTS bi.target_monthly CASCADE;
CREATE VIEW bi.target_monthly AS
SELECT 
    month AS month_start,
    category,
    target_revenue,
    target_orders,
    target_delivery_days
FROM ref.sales_targets;

-- 9. cohort_retention
DROP VIEW IF EXISTS bi.cohort_retention CASCADE;
CREATE VIEW bi.cohort_retention AS
SELECT 
    cohort,
    months_since,
    cohort_size,
    active_customers,
    retention_pct
FROM marts.cohort_retention;
