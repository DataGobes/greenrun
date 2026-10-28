# BAKE-004 Data completeness report

**As** an analyst
**I want** to see which days have missing or incomplete hours
**so that** I know whether I can trust a forecast or a recommendation built on them.

## Acceptance criteria

1. `python -m greenrun quality --start 2026-10-24 --end 2026-10-26` prints, per bidding zone and local day: expected
   hours, present hours and complete hours, from `fct_hourly_energy`.
2. Days are local days in the zone's time zone, so 2026-10-25 in DE-LU expects 25 hours and 2026-03-29 expects 23.
3. `--json` prints the same as a JSON list of objects with keys `bidding_zone`, `local_date`, `expected_hours`,
   `present_hours`, `complete_hours`.
4. Exit code is 1 if any day has fewer than 95% of its expected hours complete, otherwise 0.

## Out of scope

Alerting, history of past reports.
