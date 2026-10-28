# greenrun

Tells a household when to run an appliance, using day-ahead electricity prices, the renewable share of generation and
the weather.

The work to do is in `backlog/`. Start with `backlog/README.md`: it holds the glossary and the interfaces every story
shares.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q
ruff check . && ruff format --check .
```

dbt runs from the repo root:

```bash
dbt build --project-dir dbt --profiles-dir dbt
```

The warehouse is a DuckDB file at `$GREENRUN_DB`, default `data/greenrun.duckdb`. It is not committed.

## Data sources

Both are free and need no API key.

- Energy-Charts (Fraunhofer ISE): https://api.energy-charts.info, endpoints `/price` and `/public_power`.
- Open-Meteo: https://api.open-meteo.com/v1/forecast.

`python scripts/smoke_apis.py` checks that both answer.
