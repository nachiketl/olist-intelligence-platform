# Data Quality Policy

How each type of problem is detected, handled and tested. Tests live in `tests/test_data_quality.py`;
results of each run are stored in `audit.test_results` (run `python python/etl/validate.py`).

## Principles
1. Raw data is never edited. Every fix happens in staging and is logged in `audit.dq_issues`.
2. Problems that would make a KPI wrong must be fixed or excluded. Problems that do not affect KPIs are flagged.
3. Every known source problem has a documented threshold. A test fails if the problem grows beyond it.

## Issue handling
| Issue | Count (Olist) | Handling | Test rule |
|---|---|---|---|
| Duplicate geolocation rows | 261,831 | One row per zip prefix (average coordinates) | Staging rows = distinct zip prefixes |
| Several reviews per order | 547 orders | Keep latest; store reviews_for_order | One review row per order |
| Orders without items | 775 | Excluded from item-based revenue | Documented in dq_issues |
| Missing product category | 610 | Label 'unknown' | Share below 2 percent |
| Categories missing from translation | 2 | Added manually in staging | Every known category translated |
| Delivered, no delivery date | 8 | is_delivered = false | At most 20 |
| Handed to carrier before purchase | 166 | Flag only; not used in KPIs | Below 0.5 percent of orders |
| Delivered before carrier pickup | 23 | Flag only | Below 0.1 percent of orders |
| Payments differ from items + freight | 249 orders | Reconcile within tolerance | Below 1 percent of orders |
| Shipping limit date after 2019 | 4 | Flag only | Documented in dq_issues |

## Must always be zero
Duplicate keys, orphan rows, review scores outside 1 to 5, non-positive prices, negative freight or payments,
delivered before purchase, approved before purchase, delivery metrics on undelivered orders.

## Rounding rule
`delay_days` is rounded to 2 decimals. `is_late` uses the exact timestamps. An order a few seconds late shows
delay_days = 0.00 and is_late = true. Tests only require that the two never contradict each other.

## When a test fails
1. Read the message; it states the table and the count.
2. Decide: is it a pipeline bug (fix the SQL) or a new source problem (document it and set a threshold)?
3. Never raise a threshold only to make a test pass without writing the reason here.