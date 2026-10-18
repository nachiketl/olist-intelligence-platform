# KPI Definitions

One definition per KPI. SQL (marts), Power BI (DAX) and the AI agent must all use these definitions.

## Global rules
- **Valid sale:** an order whose status is not `canceled` or `unavailable`.
- **Analysis window:** orders purchased from 2017-01-01 to 2018-08-31 (earlier and later months are sparse).
- **Currency:** Brazilian real (BRL).
- **Customer:** a person, identified by `customer_unique_id` (`customer_key` in `core.dim_customers`).
- **Revenue excludes freight.** Freight is reported separately.

## KPIs
| KPI | Definition | Source |
|---|---|---|
| Revenue | Sum of item price on valid sales in the window | `marts.kpi_summary`, `marts.monthly_sales` |
| Orders | Distinct valid orders with at least one item | `marts.kpi_summary` |
| AOV (average order value) | Revenue divided by Orders | `marts.kpi_summary` |
| Customers | People with at least one valid order in the window | `marts.customer_rfm` |
| Repeat rate | Customers with 2 or more valid orders divided by Customers | `marts.kpi_summary` |
| MoM growth | (Revenue this month - Revenue last month) / Revenue last month | `marts.monthly_sales` |
| 3-month moving average | Average revenue of the current and previous 2 months | `marts.monthly_sales` |
| YoY growth | Revenue compared with the same month one year earlier (2018 months only) | `marts.monthly_sales` |
| Avg delivery days | Mean of (delivered time - purchase time) for delivered orders | `marts.kpi_summary`, `marts.state_delivery` |
| Late-delivery rate | Delivered orders delivered after the estimated date / delivered orders | `marts.kpi_summary`, `marts.state_delivery` |
| Avg review score | Mean of the latest review score per order | `marts.kpi_summary` |
| Category share | Category revenue / total revenue; ABC class A = categories making up the first 80 percent of revenue | `marts.category_pareto` |

## RFM segmentation (snapshot date 2018-08-31)
- **Recency:** days since the last valid order. Score 1 to 5 with NTILE (5 = most recent).
- **Frequency:** 1 order = 1, 2 orders = 3, 3 or more = 5. Fixed rules, because about 97 percent of customers bought once.
- **Monetary:** total item revenue. Score 1 to 5 with NTILE (5 = highest spend).
- **Segments:** Loyal repeat (2+ orders, R >= 3), Lapsed repeat (2+ orders, R < 3), New high value (1 order, R >= 4, M >= 4), New customer (1 order, R >= 4), Cooling (R = 3), Lost high value (R <= 2, M >= 4), Lost.

## Cohort retention
- Cohort = month of the customer's first valid order (all history). Cohorts shown: Jan 2017 to Aug 2018.
- Retention at month N = customers from the cohort with a valid order N months later / cohort size.

## Seller risk score (0 to 100; sellers with under 20 orders are not scored)
`risk = 40 x min(late rate / 20%, 1) + 35 x min(low-review rate / 25%, 1) + 25 x min(cancel rate / 5%, 1)`
- **Late rate:** late delivered orders / delivered orders containing the seller's items.
- **Low-review rate:** reviews of 1 or 2 stars / reviewed orders.
- **Cancel rate:** canceled or unavailable orders / all orders containing the seller's items.
- **Tiers:** Low below 25, Medium 25 to under 50, High 50 and above. Thresholds are business rules and will move to `excel/business_rules.xlsx`.
- An order with several sellers counts for each of them, and its review and delivery result are shared.

## Notes
- Mart views based on facts are always current. Materialized views (`customer_rfm`, `cohort_retention`, `seller_scorecard`) must be rebuilt after the facts change: run `06_create_marts.sql`.
- Payments are not revenue. They include vouchers and installment interest and are reported in `marts.payment_mix`.