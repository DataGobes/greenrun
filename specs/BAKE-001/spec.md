# BAKE-001 spec

## Intent

An energy analyst needs hourly weather for the DE-LU reference point in the warehouse. This story adds a command that loads temperature, solar radiation and wind speed from Open-Meteo into `raw.weather_hourly`. Later stories use the data to explain and forecast the renewable share.

## Acceptance criteria

- **AC-1** (story criterion 1): `python -m greenrun ingest weather --start 2026-10-01 --end 2026-10-07`, run against a faked Open-Meteo response, exits 0. Afterwards `raw.weather_hourly` holds exactly 168 rows for `DE-LU`: one per UTC hour from `2026-10-01 00:00` to `2026-10-07 23:00`, with no gaps and no duplicates.
- **AC-2** (story criterion 1): Each loaded row has the columns `bidding_zone`, `hour_utc`, `temperature_c`, `solar_radiation_wm2`, `wind_speed_100m_kmh` and `loaded_at`. The values match the faked source: `temperature_2m` goes to `temperature_c`, `shortwave_radiation` to `solar_radiation_wm2`, and `wind_speed_100m` to `wind_speed_100m_kmh`. `bidding_zone` is `DE-LU`.
- **AC-3** (story criterion 1): The request sent to Open-Meteo uses latitude `51.17`, longitude `10.45`, the forecast endpoint `https://api.open-meteo.com/v1/forecast`, the requested start and end dates, and UTC timestamps. A test checks the request without calling the real API.
- **AC-4** (story criterion 2): With "today" fixed by the test, a range whose start is more than 92 days before today, or whose end is more than 7 days after today, exits with code 2. The message names the allowed window as two dates. No API call is made and no row is written.
- **AC-5** (shared interface, exit code 2 for bad input): A date that is not `YYYY-MM-DD`, or a `--start` later than `--end`, exits with code 2. Nothing is loaded.
- **AC-6** (story criterion 3): Loading the same range twice leaves exactly one row per (`bidding_zone`, `hour_utc`). Where the second load returns different values, the table holds the second load's values and its later `loaded_at`.
- **AC-7** (story criterion 3): Loading a range that overlaps an earlier load replaces only the overlapping hours. Hours outside the new range keep their earlier rows.
- **AC-8** (story criterion 4): When the faked API fails on every call, the command makes 1 first attempt plus 3 retries, then exits non-zero. The message names Open-Meteo as the source. The table is unchanged from before the run.
- **AC-9** (story criterion 4): When the faked API fails twice and then succeeds, the command exits 0 and loads the full range.
- **AC-10** (story criterion 5): A `null` in the source for any of the three measures is stored as SQL `NULL` in that column, not as `0`. The row for that hour is still written.
- **AC-11** (shared interface, offline tests): All tests for this story run without network access. The HTTP call and the clock can be replaced in tests.

## Interfaces

**CLI**

- New command: `python -m greenrun ingest weather --start YYYY-MM-DD --end YYYY-MM-DD`.
- `--start` and `--end` are required and inclusive.
- Exit codes: `0` loaded; `2` bad input or range outside the allowed window; non-zero (see assumptions) when the API keeps failing.

**Warehouse** (DuckDB at `$GREENRUN_DB`, default `data/greenrun.duckdb`)

- Schema `raw` and table `raw.weather_hourly` are created if they do not exist.
- Columns:

| Column | Meaning |
|---|---|
| `bidding_zone` | text, `DE-LU` |
| `hour_utc` | timestamp, UTC, start of the hour |
| `temperature_c` | double, Open-Meteo `temperature_2m`, nullable |
| `solar_radiation_wm2` | double, Open-Meteo `shortwave_radiation`, nullable |
| `wind_speed_100m_kmh` | double, Open-Meteo `wind_speed_100m`, nullable |
| `loaded_at` | timestamp, UTC, when the run wrote the row |

- One row per (`bidding_zone`, `hour_utc`).

**Source**

- `https://api.open-meteo.com/v1/forecast`, hourly variables `temperature_2m`, `shortwave_radiation`, `wind_speed_100m`, `timezone=UTC`.
- Reference point from `backlog/README.md`: DE-LU, latitude 51.17, longitude 10.45.

**Files**

- Changes `src/greenrun/__main__.py` to add the `ingest weather` command.
- Adds new modules under `src/greenrun/` and tests under `tests/`. Exact file names are left to the implementation.

## Out of scope

- Bidding zones other than DE-LU.
- Historical archives older than 92 days, including the Open-Meteo archive API.
- Scheduling or automatic runs.
- Weather variables other than the three named.
- Any dbt model on top of `raw.weather_hourly` (BAKE-003).

## Assumptions

1. "Every day in the range" means UTC calendar days, so each day has exactly 24 rows. Local days in Europe/Berlin are not used here.
2. `temperature_c` comes from Open-Meteo `temperature_2m` (as in `scripts/smoke_apis.py`). The story does not name the height.
3. The allowed window is measured from today's date in UTC: start no earlier than today minus 92 days, end no later than today plus 7 days. Both bounds are inclusive.
4. "Retries up to 3 times" means 4 attempts in total. A failure is a network error, a timeout, a non-2xx HTTP status, or a body that cannot be read as the expected JSON. The wait between attempts is short and not fixed by this spec.
5. The exit code after the API keeps failing is `1`. The shared rule says `1` means "the command ran but found a problem it reports".
6. "Newest load wins" is done by deleting the rows for the zone and the loaded hours, then inserting the new rows, in one transaction. A failed run writes nothing because all data is fetched before the transaction starts.
7. Wind speed is stored in km/h, which is the Open-Meteo default unit. No unit parameter is sent.
8. There is no `--zone` flag. DE-LU is the only zone.
9. If Open-Meteo returns fewer hours than requested, the command loads what it got and does not fail. The story does not say what to do here.
10. On success the command prints a short line with the number of rows loaded. The story does not require any output.
