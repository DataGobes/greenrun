# BAKE-002 Ingest day-ahead prices and generation

**As** an energy analyst
**I want** day-ahead prices and public net generation by type in the warehouse
**so that** we can see when power is cheap and when it is green.

## Acceptance criteria

1. `python -m greenrun ingest energy --start 2026-10-01 --end 2026-10-07` loads day-ahead prices for DE-LU from
   Energy-Charts `/price?bzn=DE-LU` into `raw.day_ahead_price` with columns `bidding_zone`, `interval_start_utc`,
   `interval_minutes`, `price_eur_mwh` and `loaded_at`, at the source's own resolution (15 or 60 minutes).
2. The same command loads public net generation from `/public_power?country=de` into `raw.public_power` in long form:
   `bidding_zone`, `interval_start_utc`, `interval_minutes`, `production_type` (the source's name, unchanged),
   `value_mw`, `loaded_at`.
3. Every UTC interval that falls inside the requested dates is loaded, and none outside them.
4. Running the same range again leaves exactly one row per key; the newest load wins.
5. Negative prices are kept as they are. Null values stay null.
6. API failures behave as in BAKE-001, criterion 4.

## Out of scope

Other bidding zones, intraday prices, cross-border flows.
