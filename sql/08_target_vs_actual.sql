-- =====================================================================
-- Day 7: actual versus target (reads ref.sales_targets, loaded from Excel)
-- Run after 06_create_marts.sql (re-running 06 drops these views).
-- Targets are by category group: the 18 class A categories plus 'Other'.
-- =====================================================================
DROP VIEW IF EXISTS marts.target_vs_actual_monthly CASCADE;
DROP VIEW IF EXISTS marts.target_vs_actual CASCADE;

CREATE VIEW marts.target_vs_actual AS
WITH cat AS (
    SELECT category_en,
           CASE WHEN abc_class = 'A' THEN category_en ELSE 'Other' END AS category_group
    FROM marts.category_pareto
), act AS (
    SELECT i.month_start, c.category_group AS category,
           sum(i.price) AS actual_revenue, count(DISTINCT i.order_id) AS actual_orders
    FROM marts.v_sales_items i
    JOIN cat c USING (category_en)
    GROUP BY i.month_start, c.category_group
)
SELECT t.month AS month_start,
       to_char(t.month, 'YYYY-MM')                              AS year_month,
       t.category,
       COALESCE(a.actual_revenue, 0)                            AS actual_revenue,
       t.target_revenue,
       round(100 * COALESCE(a.actual_revenue, 0) / t.target_revenue, 1) AS attainment_pct,
       COALESCE(a.actual_revenue, 0) - t.target_revenue         AS revenue_variance,
       COALESCE(a.actual_orders, 0)                             AS actual_orders,
       t.target_orders,
       t.target_delivery_days
FROM ref.sales_targets t
LEFT JOIN act a ON a.month_start = t.month AND a.category = t.category;

CREATE VIEW marts.target_vs_actual_monthly AS
SELECT month_start, year_month,
       sum(actual_revenue)                                          AS actual_revenue,
       sum(target_revenue)                                          AS target_revenue,
       round(100 * sum(actual_revenue) / sum(target_revenue), 1)    AS attainment_pct,
       sum(actual_revenue) - sum(target_revenue)                    AS revenue_variance
FROM marts.target_vs_actual
GROUP BY month_start, year_month;