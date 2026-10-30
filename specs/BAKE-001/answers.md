# BAKE-001 answers

1. Product owner (2026-10-30): load the hours that came back, then exit 1 with a message naming the missing hours.

2. Default: delete only the hours present in the response, for zone DE-LU, then insert them, in one transaction.

3. Default: both bounds inclusive. Start may be today minus 92 days; end may be today plus 7 days. This matches spec assumption 3.

4. Default: the UTC date, taken from a clock the tests can replace. This matches spec assumption 3.

5. Default: exit code 1, as in spec assumption 5 and the shared rule "the command ran but found a problem it reports".

6. Default: retry every failure listed in spec assumption 4, including 4xx. 4 attempts in total.

7. Default: 30 second timeout per request (as in `scripts/smoke_apis.py`) and a short wait of about 1 second between attempts. Tests replace the wait so they do not sleep.

8. Default: store the value at the hour Open-Meteo returns, with no shift. Note the convention in the code. A shift, if wanted, belongs in the BAKE-003 staging model.

9. Default: no. Keep only the newest load, as the story says. No extra column.

10. Default: one `loaded_at` per run, the UTC time the run started writing, stored as plain TIMESTAMP (UTC), the same type as `hour_utc`.

11. Default: yes, declare PRIMARY KEY (`bidding_zone`, `hour_utc`).

12. Default: no. Validate dates and window before opening the database. Create the schema and table only inside the write transaction of a successful fetch.

13. Default: drop any hour outside the requested range before writing.

14. Default: the success line goes to stdout. Error messages (bad input, window, API failure) go to stderr.
