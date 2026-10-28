# Backlog

| Id | Story | Area |
|---|---|---|
| BAKE-001 | Ingest hourly weather | ingestion |
| BAKE-002 | Ingest day-ahead prices and generation | ingestion |
| BAKE-003 | Hourly energy mart in dbt | dbt |
| BAKE-004 | Data completeness report | data quality |
| BAKE-005 | Forecast the renewable share | ML |
| BAKE-006 | Best time to run my appliance | product logic |
| BAKE-007 | Ask greenrun in plain language | agent |

Work them in order: each story builds on the ones before. The product owner answers questions about any story.

## Glossary

- **Bidding zone:** the market area a price applies to. Germany is `DE-LU`. Each zone has one weather reference point.
- **Day-ahead price:** the price in EUR/MWh set the day before delivery, published around 12:00 Europe/Berlin.
  Negative prices are real and valid.
- **Interval:** one value from the source. Since October 2025 the day-ahead market uses 15-minute intervals; older
  data, and some series, are hourly.
- **Hour (`hour_utc`):** the UTC hour an interval falls in, as a timestamp at the start of the hour.
- **Complete hour:** an hour where every interval the source should have for it is present and not null.
- **Local day:** a calendar day in the bidding zone's time zone (`Europe/Berlin` for DE-LU). A local day has 23, 24
  or 25 hours.
- **Renewable share:** renewable generation divided by total generation, for one hour, between 0 and 1.
  - Renewable: Biomass, Hydro Run-of-River, Hydro water reservoir, Geothermal, Wind offshore, Wind onshore, Solar.
  - Total generation: every production type from `/public_power` except Load, Residual load, Cross border
    electricity trading, Hydro pumped storage consumption, and any series that is already a share or percentage.
- **Run window:** the hours an appliance runs, from its start time to its end time.

## Shared interfaces

These are fixed, so that every story fits together and the result can be checked from outside.

- Python package `greenrun` under `src/`, run as `python -m greenrun <command>`.
- Warehouse: DuckDB at `$GREENRUN_DB`, default `data/greenrun.duckdb`. Raw data goes in schema `raw`, dbt builds into
  schema `main`.
- Every timestamp stored in the warehouse is UTC.
- Dates on the command line are `YYYY-MM-DD`. `--start` and `--end` are inclusive.
- Exit codes: `0` success, `1` the command ran but found a problem it reports, `2` bad input.
- Tests run offline. No test calls a real API or a real LLM.

## Weather reference points

| Bidding zone | Point | Latitude | Longitude | Time zone |
|---|---|---|---|---|
| DE-LU | Centre of Germany | 51.17 | 10.45 | Europe/Berlin |
