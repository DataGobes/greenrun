# BAKE-001 questions

1. [blocking] If Open-Meteo answers but returns fewer hours than requested, should the command load what it got and exit 0, or load nothing and exit 1?
   Why it matters: it decides the exit code (an interface) and whether story criterion 1 ("one row per UTC hour") can be broken by a successful run. Spec assumption 9 currently picks "load and exit 0".

2. [default] When a run replaces rows, does it delete the whole requested range or only the hours the response contains?
   Why it matters: with a partial response, deleting the whole range erases good earlier rows that the new run cannot replace.

3. [default] Is the window bound inclusive: is a start of exactly today minus 92 days, or an end of exactly today plus 7 days, allowed?
   Why it matters: the boundary case in the AC-4 test passes or fails depending on this.

4. [default] Is "today" for the window the UTC date or the Europe/Berlin date?
   Why it matters: between 22:00 and 24:00 UTC the two dates differ, so the allowed window shifts by one day.

5. [default] Which exit code is used when the API keeps failing: 1 or something else?
   Why it matters: the story only says "non-zero"; tests and scripts need one fixed value.

6. [default] Should every failure be retried, including 4xx answers such as 400?
   Why it matters: retrying a request the API rejects as invalid only adds delay, and it changes how many calls tests expect.

7. [default] How long is the request timeout and the wait between attempts?
   Why it matters: real runs need a bounded time; tests must not sleep.

8. [default] Open-Meteo documents `shortwave_radiation` as the mean of the preceding hour. Should the value be stored at the hour Open-Meteo labels it with, or shifted to the start of the hour it covers?
   Why it matters: a one-hour shift changes which solar value lines up with which price and generation hour in BAKE-003 and BAKE-005.

9. [default] For future days the endpoint returns forecasts, which change on each run. Must the table keep older forecast versions?
   Why it matters: "newest load wins" throws older forecasts away; keeping them would need an extra column the story does not list.

10. [default] Is `loaded_at` one value per run or per row, and is it stored as a plain TIMESTAMP or TIMESTAMPTZ?
    Why it matters: BAKE-003 reads these columns, and DuckDB treats the two types differently.

11. [default] Should the table declare a primary key on (`bidding_zone`, `hour_utc`)?
    Why it matters: a key makes duplicates impossible instead of relying only on the delete-then-insert logic.

12. [default] If the input is invalid or the window check fails, may the command still create the DuckDB file, schema or table?
    Why it matters: AC-4, AC-5 and AC-8 say nothing is written; creating an empty table on a refused run is a side effect.

13. [default] If the response contains hours outside the requested range, what happens to them?
    Why it matters: loading them would replace rows the user did not ask to touch.

14. [default] Where do messages go: stdout or stderr?
    Why it matters: tests check messages, and scripts often read stdout only.
