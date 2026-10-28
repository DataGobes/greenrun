# BAKE-005 Forecast the renewable share

**As** a household user, later on
**I want** a forecast of the renewable share for the coming day
**so that** a recommendation can include hours that day-ahead prices do not cover yet.

## Acceptance criteria

1. `python -m greenrun train --until 2026-10-20` trains a model that predicts the hourly `renewable_share` from
   weather and calendar features, using only complete hours before that date. It needs at least 60 days of data and
   exits with code 2 if there is less.
2. Training holds out the last 7 days before `--until`, and writes the model's mean absolute error and a naive
   baseline's (the same hour one day earlier) to `artifacts/metrics.json`. If the model does not beat the baseline,
   the command exits with code 1 and does not save the model.
3. `python -m greenrun predict --date 2026-10-28` writes 24 rows, one per UTC hour, to
   `main.renewable_share_forecast` with columns `bidding_zone`, `hour_utc`, `predicted_renewable_share` (between 0
   and 1) and `model_version`. Running it again replaces those rows.
4. A prediction uses only the weather forecast for that date, never the actual renewable share of that date or later.
5. Training with the same data gives the same model and the same metrics.

## Out of scope

Price forecasting, hyperparameter search, a model registry.
