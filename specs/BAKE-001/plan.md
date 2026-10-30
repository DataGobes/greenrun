# BAKE-001 plan

Source of truth: `spec.md` (updated to match `answers.md`). Product owner answer 1 decides the partial-response case:
load the hours that came back, then exit 1 naming the missing hours.

## Files

| File | Change |
|---|---|
| `src/greenrun/warehouse.py` | New. `db_path() -> Path` reads `$GREENRUN_DB`, default `data/greenrun.duckdb`. `connect() -> duckdb.DuckDBPyConnection` creates the parent directory and opens the file. Shared by later stories. |
| `src/greenrun/weather.py` | New. Open-Meteo client, response parsing, window check and the loader (sections below). Holds the replaceable seams `http_get`, `utc_now`, `sleep`. |
| `src/greenrun/__main__.py` | Change. Add `ingest` subparser with a `weather` subcommand (`--start`, `--end`, both required), dispatch to `weather.run_ingest(start, end) -> int`. Keep "no command prints help, exit 0". |
| `tests/conftest.py` | New. Autouse fixture: block real sockets (`socket.socket.connect` raises), set `GREENRUN_DB` to a `tmp_path` file, replace `weather.sleep` with a recorder, fix `weather.utc_now`. Helper `fake_response(start, end, overrides=..., drop=..., extra=...)` builds an Open-Meteo-shaped body. Helper `FakeHttp` scripts a sequence of results (body, `HttpError(status)`, `OSError`/timeout, raw bytes) and records each call's URL and timeout. |
| `tests/test_weather_ingest.py` | New. CLI-level tests for AC-1..AC-15 (see test plan). |
| `tests/test_weather_parse.py` | New. Unit tests for URL building, parsing, window and missing-hours formatting. |
| `tests/test_cli.py` | Unchanged; must still pass. |

No new dependencies: HTTP uses `urllib.request` (as in `scripts/smoke_apis.py`), storage uses `duckdb`.

## Data contracts

### Request

`GET https://api.open-meteo.com/v1/forecast` with query, in this order:

```
latitude=51.17&longitude=10.45&hourly=temperature_2m,shortwave_radiation,wind_speed_100m
&start_date=<start>&end_date=<end>&timezone=UTC
```

No unit parameters (wind stays km/h). Timeout 30 s per request.

Constants in `weather.py`: `SOURCE = "Open-Meteo"`, `URL`, `ZONE = "DE-LU"`, `LATITUDE = 51.17`, `LONGITUDE = 10.45`,
`VARIABLES`, `ATTEMPTS = 4`, `TIMEOUT_S = 30`, `RETRY_WAIT_S = 1.0`, `PAST_DAYS = 92`, `FUTURE_DAYS = 7`.

### Seams (replaced by tests)

```python
def http_get(url: str, timeout: float) -> bytes: ...   # urllib; raises on non-2xx (HTTPError), network error, timeout
def utc_now() -> datetime: ...                          # naive datetime in UTC
def sleep(seconds: float) -> None: ...                  # time.sleep
```

Code calls them through the module (`weather.http_get(...)`) so `monkeypatch.setattr(weather, "http_get", fake)` works.

### Response (expected shape)

```json
{"hourly": {"time": ["2026-10-01T00:00", ...],
            "temperature_2m": [12.3, null, ...],
            "shortwave_radiation": [0.0, ...],
            "wind_speed_100m": [14.1, ...]}}
```

`parse_response(body: bytes) -> list[WeatherRow]` raises `BadResponse` when the body is not JSON, `hourly` or any of
the four arrays is missing, arrays differ in length, a time does not parse as `YYYY-MM-DDTHH:MM`, a value is neither a
number nor null, or a time repeats. `BadResponse` counts as a failed attempt and is retried (spec assumption 4).

```python
@dataclass(frozen=True)
class WeatherRow:
    hour_utc: datetime              # naive UTC, exactly as Open-Meteo labels it (no shift; see note below)
    temperature_c: float | None
    solar_radiation_wm2: float | None
    wind_speed_100m_kmh: float | None
```

`null` maps to `None` and is stored as SQL `NULL` (never `0`). Convention note in code: Open-Meteo labels
`shortwave_radiation` with the end of the hour it averages; we store it at the label, and any shift belongs in the
BAKE-003 staging model.

### Functions in `weather.py`

- `parse_date(text) -> date`: strict `YYYY-MM-DD` (regex plus `date.fromisoformat`), else `ValueError`.
- `allowed_window(today: date) -> tuple[date, date]`: `(today - 92 days, today + 7 days)`, both inclusive.
- `expected_hours(start, end) -> list[datetime]`: every UTC hour from `start 00:00` to `end 23:00` (24 per day).
- `build_url(start, end) -> str`.
- `fetch(start, end) -> list[WeatherRow]`: up to `ATTEMPTS` calls; on any exception (HTTP error of any status,
  `OSError`/`URLError`/timeout, `BadResponse`) waits `RETRY_WAIT_S` via `sleep` and tries again, no wait after the last
  attempt. After the last failure raises `SourceError("Open-Meteo request failed after 4 attempts: <last error>")`.
- `select_in_range(rows, start, end) -> list[WeatherRow]`: drops hours outside `[start 00:00, end 23:00]` (answer 13).
- `missing_hours(rows, start, end) -> list[datetime]`.
- `format_hours(hours) -> str`: collapses consecutive hours into ranges, e.g.
  `2026-10-07 21:00..2026-10-07 23:00 UTC`, comma separated.
- `write(con, rows, loaded_at) -> int`: one transaction (below). Returns rows written.
- `run_ingest(start_text, end_text) -> int`: orchestration and exit code (below).

### Table

```sql
CREATE SCHEMA IF NOT EXISTS raw;
CREATE TABLE IF NOT EXISTS raw.weather_hourly (
    bidding_zone        VARCHAR   NOT NULL,
    hour_utc            TIMESTAMP NOT NULL,   -- UTC, plain TIMESTAMP
    temperature_c       DOUBLE,
    solar_radiation_wm2 DOUBLE,
    wind_speed_100m_kmh DOUBLE,
    loaded_at           TIMESTAMP NOT NULL,   -- UTC, one value per run
    PRIMARY KEY (bidding_zone, hour_utc)
);
```

### Write transaction (`write`)

Only called with at least one row. `BEGIN`; create schema and table if missing; load rows into a temp table;
`DELETE FROM raw.weather_hourly WHERE bidding_zone = 'DE-LU' AND hour_utc IN (SELECT hour_utc FROM temp)`;
`INSERT ... SELECT` from temp with `bidding_zone = 'DE-LU'` and the single `loaded_at`; `COMMIT`. Any exception
`ROLLBACK`s and re-raises. Only hours present in the response are touched (answer 2).

### Orchestration and exit codes (`run_ingest`)

1. Parse `--start` and `--end`. Bad format or `start > end` -> stderr message, exit 2. Database not opened.
2. `today = utc_now().date()`; if `start < lo` or `end > hi` -> stderr
   `"--start/--end outside the allowed window <lo> to <hi> (Open-Meteo forecast serves today-92 to today+7 days)"`,
   exit 2. No HTTP call, database not opened.
3. `fetch` -> on `SourceError`, stderr message naming Open-Meteo, exit 1. Database not opened.
4. `rows = select_in_range(...)`; `missing = missing_hours(...)`.
5. If `rows`: `loaded_at = utc_now()` (naive UTC), `connect()`, `write`, close. Print
   `"Loaded <n> weather rows for DE-LU, <start> to <end>."` to stdout.
6. If `missing`: stderr `"Open-Meteo returned <k> of <expected> hours; missing: <format_hours(missing)>"`, exit 1.
   Otherwise exit 0.

argparse's own errors (missing required flag, unknown subcommand) already exit 2.

## Test plan

All tests are offline: the autouse fixture blocks sockets, fakes `http_get`, fixes `utc_now` (e.g. `2026-10-20 10:00`
UTC so 2026-10-01..07 is inside the window), and replaces `sleep`. Each test uses its own `GREENRUN_DB` in `tmp_path`.
Tests call `main([...])` and read the database with `duckdb.connect`.

| AC | Test (file `tests/test_weather_ingest.py` unless noted) | Checks |
|---|---|---|
| AC-1 | `test_loads_one_row_per_utc_hour` | exit 0; 168 rows for DE-LU; `min = 2026-10-01 00:00`, `max = 2026-10-07 23:00`; `count(distinct hour_utc) = 168`. |
| AC-2 | `test_columns_and_values_match_source` | column names and order via `DESCRIBE`; types (`TIMESTAMP` for `hour_utc` and `loaded_at`, `DOUBLE` measures); spot-checked values equal the fake's `temperature_2m`, `shortwave_radiation`, `wind_speed_100m`; `bidding_zone = 'DE-LU'`. |
| AC-3 | `test_request_url` (also `test_weather_parse.py::test_build_url`) | recorded URL host/path is `api.open-meteo.com/v1/forecast`; query has `latitude=51.17`, `longitude=10.45`, the three variables, `start_date`, `end_date`, `timezone=UTC`; no unit params. |
| AC-4 | `test_window_refused` (parametrized: start = today-93; end = today+8) and `test_window_bounds_allowed` (start = today-92, end = today+7) | refused: exit 2, stderr contains both window dates, fake HTTP never called, no DB file. Bounds: exit 0. Also `test_weather_parse.py::test_allowed_window`. |
| AC-5 | `test_bad_input` (parametrized: `2026-13-01`, `2026/10/01`, `20261001`, start after end) | exit 2; no HTTP call; no DB file. Missing `--end` -> `SystemExit(2)` from argparse. |
| AC-6 | `test_rerun_newest_load_wins` | load, advance clock, load again with changed values; 168 rows; values and `loaded_at` are the second run's; one `loaded_at` value per run. |
| AC-7 | `test_overlapping_range_replaces_only_overlap` | load 10-01..10-03, then 10-03..10-05 with new values; 120 rows; 10-01..10-02 keep first `loaded_at` and values; 10-03 has second run's. |
| AC-8 | `test_all_attempts_fail` (parametrized: `HTTPError 500`, `URLError`, timeout, non-JSON body) | 4 HTTP calls; exit 1; stderr names "Open-Meteo"; pre-seeded table identical before and after (compare full `SELECT *`). |
| AC-9 | `test_two_failures_then_success` | 3 calls; exit 0; 168 rows. |
| AC-10 | `test_null_stored_as_null` | fake sets one hour's each measure to `null`; that row exists with `NULL` (not `0`) in that column, other columns intact. Also `test_weather_parse.py::test_parse_null`. |
| AC-11 | `conftest.py` socket block (all tests) and `test_no_network_used` | a test that would hit the network fails; `test_no_network_used` asserts real `http_get` is never reached (fake recorded every call). |
| AC-12 | `test_partial_response_loads_and_exits_1` | pre-seed 10-07 rows; fake omits 10-07 21:00..23:00; exit 1; stderr contains `2026-10-07 21:00..2026-10-07 23:00`; 165 hours updated with new `loaded_at`; the 3 missing hours keep pre-seeded rows; stdout success line reports 165. Plus `test_empty_response_exits_1_writes_nothing` (no rows, no DB file). Also `test_weather_parse.py::test_format_hours`. |
| AC-13 | `test_out_of_range_hours_dropped` | pre-seed 2026-10-08 00:00; fake adds 2026-09-30 23:00 and 2026-10-08 00:00; exit 0; 168 new rows; the 10-08 row unchanged; no 09-30 row. |
| AC-14 | `test_refused_and_failed_runs_create_nothing` and checks in AC-4/5/8 tests | no DB file after refused or failed run on a fresh path; success line on stdout, errors on stderr (`capsys`). |
| AC-15 | `test_4xx_is_retried`, `test_timeout_and_wait` | `HTTPError 400` x4 -> 4 calls, exit 1; every recorded timeout is 30; `sleep` recorded `[1.0, 1.0, 1.0]` on all-fail and nothing on first-try success. |

Unit tests in `tests/test_weather_parse.py` also cover `parse_response` rejecting: missing `hourly`, missing variable,
length mismatch, duplicate time, bad time string, string value.

## Checks

`ruff check .`, `ruff format --check .`, `python -m pytest -q` (from `.specgraph/config.json`).

## Risks

- DuckDB `PRIMARY KEY` with delete-then-insert in one transaction: DuckDB has had issues with re-inserting a just
  deleted key inside the same transaction. AC-6/AC-7 tests cover it; if it fails, delete in its own statement before
  the insert in the same transaction using the temp table, and if DuckDB still rejects it, fall back to
  `INSERT OR REPLACE` (same result: newest load wins, only returned hours touched).
- The real clock's `today` vs fixed test dates: every window-sensitive test fixes `utc_now`.
