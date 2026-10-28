# BAKE-001 Ingest hourly weather

**As** an energy analyst
**I want** hourly weather for each bidding zone's reference point in the warehouse
**so that** we can explain and forecast the renewable share.

## Acceptance criteria

1. `python -m greenrun ingest weather --start 2026-10-01 --end 2026-10-07` loads, for DE-LU's reference point, one
   row per UTC hour of every day in the range into `raw.weather_hourly`, with columns `bidding_zone`, `hour_utc`,
   `temperature_c`, `solar_radiation_wm2` (Open-Meteo `shortwave_radiation`), `wind_speed_100m_kmh` and `loaded_at`.
2. Data comes from the Open-Meteo forecast endpoint, which serves the last 92 days and the next 7. A range that
   reaches outside that window is refused with exit code 2 and a message naming the allowed window. Nothing is loaded.
3. Running the same range again leaves exactly one row per zone and hour; the newest load wins.
4. If the API fails, the command retries up to 3 times, then exits non-zero with a message naming the source. Rows
   from a failed run are not written.
5. A null value in the source is stored as null, not as 0.

## Out of scope

Other bidding zones, historical archives older than 92 days, scheduling.
