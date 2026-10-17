# Olist Commerce Intelligence & AI Decision Platform
End-to-end analytics project: PostgreSQL warehouse, Power BI report and a guarded AI agent,
built on the public Olist Brazilian E-Commerce dataset (2016-2018, BRL).
Portfolio project; not a deployed company system.
## Progress- [x] Day 1: environment, raw load with audit log (9 tables, row counts verified)- [x] 
Day 2: staging layer, delivery metrics, 13 data-quality checks- [ ] 
Day 3: automated data-quality tests- [ ] 
Days 4-6: star schema, marts, advanced SQL- [ ]
Day 7: Excel inputs and database security- [ ]
Days 8-10: Power BI model and report- [ ] 
Days 11-13: AI agent (guarded SQL, investigations, evaluation)- [ ] 
Days 14-15: chat interface, documentation, demo
## Architecture
raw (exact copy) -> staging (typed, deduplicated) -> core (star schema) -> marts (KPIs)-> Power BI and AI agent
## Run it
1. Install PostgreSQL 18 and Python; create database olist_dw
2. python -m venv .venv ; activate ; pip install -r requirements.txt
3. Copy .env.example to .env and set DATABASE_URL
4. Download the Olist CSVs from Kaggle into data/raw
5. python python/etl/ingest.py
6. python python/etl/run_sql.py sql/03_staging_transformations.sql
## Key decisions- Raw layer stored as text to stay an exact copy of the source- Separate fact grains for items, payments and reviews- Analysis window Jan 2017 to Aug 2018 (other months sparse)
## Limitations
Historical data, BRL, no costs or targets, anonymised sellers and products
