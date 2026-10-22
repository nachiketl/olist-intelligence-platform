-- =====================================================================
-- Create Cohort Retention Mart & BI View
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS marts;

DROP TABLE IF EXISTS marts.cohort_retention CASCADE;

CREATE TABLE marts.cohort_retention AS
WITH customer_first AS (
    SELECT 
        customer_unique_id,
        MIN(DATE_TRUNC('month', o.order_purchase_timestamp)) AS cohort_month
    FROM core.fact_orders o
    JOIN core.dim_customers c ON c.customer_key = o.customer_key
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
    GROUP BY customer_unique_id
),
customer_activity AS (
    SELECT DISTINCT
        c.customer_unique_id,
        cf.cohort_month,
        DATE_TRUNC('month', o.order_purchase_timestamp) AS activity_month
    FROM core.fact_orders o
    JOIN core.dim_customers c ON c.customer_key = o.customer_key
    JOIN customer_first cf ON cf.customer_unique_id = c.customer_unique_id
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
),
cohort_counts AS (
    SELECT 
        cohort_month,
        activity_month,
        (EXTRACT(YEAR FROM activity_month) - EXTRACT(YEAR FROM cohort_month)) * 12 +
        (EXTRACT(MONTH FROM activity_month) - EXTRACT(MONTH FROM cohort_month)) AS months_since,
        COUNT(DISTINCT customer_unique_id) AS active_customers
    FROM customer_activity
    GROUP BY cohort_month, activity_month
),
cohort_sizes AS (
    SELECT 
        cohort_month,
        active_customers AS cohort_size
    FROM cohort_counts
    WHERE months_since = 0
)
SELECT 
    TO_CHAR(cc.cohort_month, 'YYYY-MM') AS cohort,
    cc.months_since,
    cs.cohort_size,
    cc.active_customers,
    ROUND((cc.active_customers::numeric / cs.cohort_size::numeric) * 100, 2) AS retention_pct
FROM cohort_counts cc
JOIN cohort_sizes cs ON cs.cohort_month = cc.cohort_month
ORDER BY cc.cohort_month, cc.months_since;

-- Re-create the BI view
CREATE SCHEMA IF NOT EXISTS bi;
DROP VIEW IF EXISTS bi.cohort_retention CASCADE;
CREATE VIEW bi.cohort_retention AS
SELECT 
    cohort,
    months_since,
    cohort_size,
    active_customers,
    retention_pct
FROM marts.cohort_retention;

GRANT SELECT ON bi.cohort_retention TO bi_ro;
