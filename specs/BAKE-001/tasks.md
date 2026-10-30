# BAKE-001 tasks

Follow `plan.md`. Run `ruff check .`, `ruff format --check .` and `python -m pytest -q` after each step.

1. **Warehouse helper.** Add `src/greenrun/warehouse.py` with `db_path()` and `connect()`.
   Done when: a test shows `db_path()` honours `$GREENRUN_DB` and defaults to `data/greenrun.duckdb`.

2. **Test scaffolding.** Add `tests/conftest.py`: socket block, per-test `GREENRUN_DB`, fixed `utc_now`, recording
   `sleep`, `fake_response(...)` and `FakeHttp`.
   Done when: the existing `tests/test_cli.py` still passes with the autouse fixture active.

3. **Constants, dates and window.** In `src/greenrun/weather.py` add constants, `parse_date`, `allowed_window`,
   `expected_hours`, `build_url`.
   Done when: unit tests for strict date parsing, inclusive window bounds, 24 hours per day and the exact URL query
   (AC-3) pass.

4. **Response parsing.** Add `WeatherRow`, `BadResponse`, `parse_response` (with the no-shift convention comment),
   `select_in_range`, `missing_hours`, `format_hours`.
   Done when: unit tests pass for nulls kept as `None` (AC-10), each malformed-body case, out-of-range filtering
   (AC-13) and range formatting of missing hours (AC-12).

5. **Fetch with retries.** Add seams `http_get`, `utc_now`, `sleep` and `fetch` (4 attempts, 30 s timeout, 1 s wait,
   every failure retried, `SourceError` naming Open-Meteo).
   Done when: unit tests show 4 calls on constant failure including HTTP 400, 3 calls on fail-fail-succeed, timeouts
   of 30, sleeps `[1.0, 1.0, 1.0]` (AC-8, AC-9, AC-15 at function level).

6. **Write transaction.** Add `write(con, rows, loaded_at)`: create schema/table with primary key, delete only returned
   hours for DE-LU, insert, one transaction, rollback on error.
   Done when: unit tests on a temp DuckDB show rerun replaces values and `loaded_at` (AC-6), overlap keeps other hours
   (AC-7), and an injected failure leaves the table unchanged.

7. **Orchestration.** Add `run_ingest(start, end)` with the step order and messages from `plan.md` (validate, window,
   fetch, filter, write, report; partial -> exit 1).
   Done when: it returns 0/1/2 for success, partial or source failure, bad input or window, respectively, in unit tests.

8. **CLI wiring.** Add `ingest weather --start --end` to `src/greenrun/__main__.py`.
   Done when: `python -m greenrun ingest weather --help` shows both flags and `main([])` still prints help.

9. **End-to-end CLI tests.** Write `tests/test_weather_ingest.py` covering every row of the test-plan table
   (AC-1..AC-15), including "no DB file" checks and stdout/stderr split.
   Done when: every AC-n from `spec.md` maps to at least one passing test and the full check suite is green offline.

10. **Manual smoke (optional, not in CI).** Run the command once against the real API for a recent week.
    Done when: it exits 0 and `raw.weather_hourly` has 24 rows per day; no test depends on this.
