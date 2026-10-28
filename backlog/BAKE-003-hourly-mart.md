# BAKE-003 Hourly energy mart in dbt

**As** an analyst and as the forecasting model
**I want** one clean table with price, renewable share and weather per hour
**so that** nobody has to join and resample raw data again.

## Acceptance criteria

1. The dbt project declares the three raw tables as sources and has one staging model per source.
2. The mart `fct_hourly_energy` has exactly one row per `bidding_zone` and `hour_utc` for every hour where any source
   has data, with these columns and types:

   | Column | Type | Meaning |
   |---|---|---|
   | `bidding_zone` | varchar | e.g. `DE-LU` |
   | `hour_utc` | timestamp | start of the UTC hour |
   | `price_eur_mwh` | double | mean of the hour's price intervals; null unless the hour is complete |
   | `renewable_share` | double | see the glossary; null unless the hour is complete |
   | `temperature_c` | double | |
   | `solar_radiation_wm2` | double | |
   | `wind_speed_100m_kmh` | double | |
   | `is_complete` | boolean | price and generation are both complete for the hour |

3. The mart's columns and types are a published contract: dbt enforces it, and a change needs a new model version.
4. dbt tests cover: the key is unique and not null, `renewable_share` is between 0 and 1, and `is_complete` is false
   whenever `price_eur_mwh` or `renewable_share` is null.
5. `dbt build --project-dir dbt --profiles-dir dbt` passes offline on small invented fixture data that includes a
   15-minute hour, an hourly hour, a negative price and a missing interval.

## Out of scope

Daily aggregates, dashboards.
