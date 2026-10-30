"""Load hourly weather for DE-LU from the Open-Meteo forecast API into `raw.weather_hourly`.

The HTTP call (`http_get`), the clock (`utc_now`) and the wait between attempts (`sleep`) are module-level seams.
Code calls them through this module so tests can replace them with `monkeypatch.setattr(weather, ...)`.
"""

import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import duckdb

from greenrun import warehouse

SOURCE = "Open-Meteo"
URL = "https://api.open-meteo.com/v1/forecast"
ZONE = "DE-LU"
LATITUDE = 51.17
LONGITUDE = 10.45
# Open-Meteo variable -> column in raw.weather_hourly
VARIABLES = {
    "temperature_2m": "temperature_c",
    "shortwave_radiation": "solar_radiation_wm2",
    "wind_speed_100m": "wind_speed_100m_kmh",
}
ATTEMPTS = 4
TIMEOUT_S = 30
RETRY_WAIT_S = 1.0
PAST_DAYS = 92
FUTURE_DAYS = 7

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")

CREATE_SQL = """
CREATE SCHEMA IF NOT EXISTS raw;
CREATE TABLE IF NOT EXISTS raw.weather_hourly (
    bidding_zone        VARCHAR   NOT NULL,
    hour_utc            TIMESTAMP NOT NULL,
    temperature_c       DOUBLE,
    solar_radiation_wm2 DOUBLE,
    wind_speed_100m_kmh DOUBLE,
    loaded_at           TIMESTAMP NOT NULL,
    PRIMARY KEY (bidding_zone, hour_utc)
);
"""


class BadResponse(Exception):
    """The body is not the JSON shape we expect from Open-Meteo."""


class SourceError(Exception):
    """Open-Meteo kept failing after every attempt."""


@dataclass(frozen=True)
class WeatherRow:
    hour_utc: datetime  # naive UTC, exactly as Open-Meteo labels it (no shift)
    temperature_c: float | None
    solar_radiation_wm2: float | None
    wind_speed_100m_kmh: float | None


# --- seams -----------------------------------------------------------------------------------------------------------


def http_get(url: str, timeout: float) -> bytes:
    """GET `url`. Raises on a non-2xx status (HTTPError), a network error or a timeout."""
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read()


def utc_now() -> datetime:
    """The current time in UTC, as a naive datetime."""
    return datetime.now(UTC).replace(tzinfo=None)


def sleep(seconds: float) -> None:
    time.sleep(seconds)


# --- dates and window ------------------------------------------------------------------------------------------------


def parse_date(text: str) -> date:
    """Parse a strict `YYYY-MM-DD` date, else raise ValueError."""
    if not _DATE_RE.match(text):
        raise ValueError(f"not a YYYY-MM-DD date: {text!r}")
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"not a valid date: {text!r}") from error


def allowed_window(today: date) -> tuple[date, date]:
    """The dates the forecast endpoint serves, both inclusive."""
    return today - timedelta(days=PAST_DAYS), today + timedelta(days=FUTURE_DAYS)


def expected_hours(start: date, end: date) -> list[datetime]:
    """Every UTC hour from `start 00:00` to `end 23:00`."""
    first = datetime.combine(start, datetime.min.time())
    count = ((end - start).days + 1) * 24
    return [first + timedelta(hours=i) for i in range(count)]


def build_url(start: date, end: date) -> str:
    query = urllib.parse.urlencode(
        {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "hourly": ",".join(VARIABLES),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "timezone": "UTC",
        },
        safe=",",
    )
    return f"{URL}?{query}"


# --- response parsing ------------------------------------------------------------------------------------------------


def _value(raw: object, name: str, index: int) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise BadResponse(f"{name}[{index}] is not a number or null: {raw!r}")
    value = float(raw)
    if not math.isfinite(value):
        raise BadResponse(f"{name}[{index}] is not finite: {raw!r}")
    return value


def parse_response(body: bytes) -> list[WeatherRow]:
    """Turn an Open-Meteo body into rows, or raise BadResponse.

    Convention: Open-Meteo labels `shortwave_radiation` with the end of the hour it averages. We store every value at
    the hour Open-Meteo labels it with, with no shift. A shift, if wanted, belongs in the BAKE-003 staging model.
    """
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError) as error:
        raise BadResponse(f"body is not JSON: {error}") from error
    hourly = data.get("hourly") if isinstance(data, dict) else None
    if not isinstance(hourly, dict):
        raise BadResponse("body has no 'hourly' object")
    arrays = {}
    for name in ("time", *VARIABLES):
        array = hourly.get(name)
        if not isinstance(array, list):
            raise BadResponse(f"'hourly' has no '{name}' array")
        arrays[name] = array
    lengths = {len(array) for array in arrays.values()}
    if len(lengths) != 1:
        raise BadResponse(f"'hourly' arrays differ in length: { {k: len(v) for k, v in arrays.items()} }")

    rows = []
    seen = set()
    for i, text in enumerate(arrays["time"]):
        if not isinstance(text, str) or not _TIME_RE.match(text):
            raise BadResponse(f"time[{i}] is not YYYY-MM-DDTHH:MM: {text!r}")
        try:
            hour = datetime.strptime(text, "%Y-%m-%dT%H:%M")
        except ValueError as error:
            raise BadResponse(f"time[{i}] is not a valid time: {text!r}") from error
        if hour in seen:
            raise BadResponse(f"time {text} appears more than once")
        seen.add(hour)
        values = [_value(arrays[name][i], name, i) for name in VARIABLES]
        rows.append(WeatherRow(hour, *values))
    return rows


def select_in_range(rows: Iterable[WeatherRow], start: date, end: date) -> list[WeatherRow]:
    """Keep only rows from `start 00:00` to `end 23:00`."""
    lo = datetime.combine(start, datetime.min.time())
    hi = datetime.combine(end, datetime.min.time()) + timedelta(hours=23)
    return [row for row in rows if lo <= row.hour_utc <= hi]


def missing_hours(rows: Iterable[WeatherRow], start: date, end: date) -> list[datetime]:
    present = {row.hour_utc for row in rows}
    return [hour for hour in expected_hours(start, end) if hour not in present]


def format_hours(hours: Iterable[datetime]) -> str:
    """Collapse consecutive hours into ranges: `2026-10-07 21:00..2026-10-07 23:00, 2026-10-08 05:00 UTC`."""
    ranges: list[list[datetime]] = []
    for hour in sorted(hours):
        if ranges and hour - ranges[-1][1] == timedelta(hours=1):
            ranges[-1][1] = hour
        else:
            ranges.append([hour, hour])
    if not ranges:
        return ""

    def fmt(hour: datetime) -> str:
        return hour.strftime("%Y-%m-%d %H:%M")

    parts = [fmt(a) if a == b else f"{fmt(a)}..{fmt(b)}" for a, b in ranges]
    return ", ".join(parts) + " UTC"


# --- fetch -----------------------------------------------------------------------------------------------------------


def fetch(start: date, end: date) -> list[WeatherRow]:
    """Fetch and parse the range. Every failure is retried; ATTEMPTS calls in total, then SourceError."""
    url = build_url(start, end)
    last: Exception | None = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return parse_response(http_get(url, TIMEOUT_S))
        except Exception as error:  # noqa: BLE001 - every failure is retried (spec assumption 4)
            last = error
            if attempt < ATTEMPTS:
                sleep(RETRY_WAIT_S)
    raise SourceError(f"{SOURCE} request failed after {ATTEMPTS} attempts: {last}")


# --- write -----------------------------------------------------------------------------------------------------------


def write(con: duckdb.DuckDBPyConnection, rows: list[WeatherRow], loaded_at: datetime) -> int:
    """Replace the returned hours for DE-LU with `rows`, in one transaction. Returns the number of rows written."""
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(CREATE_SQL)
        con.execute(
            "CREATE OR REPLACE TEMP TABLE weather_load ("
            "hour_utc TIMESTAMP, temperature_c DOUBLE, solar_radiation_wm2 DOUBLE, wind_speed_100m_kmh DOUBLE)"
        )
        con.executemany(
            "INSERT INTO weather_load VALUES (?, ?, ?, ?)",
            [(r.hour_utc, r.temperature_c, r.solar_radiation_wm2, r.wind_speed_100m_kmh) for r in rows],
        )
        con.execute(
            "DELETE FROM raw.weather_hourly WHERE bidding_zone = ? AND hour_utc IN (SELECT hour_utc FROM weather_load)",
            [ZONE],
        )
        con.execute(
            "INSERT INTO raw.weather_hourly "
            "(bidding_zone, hour_utc, temperature_c, solar_radiation_wm2, wind_speed_100m_kmh, loaded_at) "
            "SELECT ?, hour_utc, temperature_c, solar_radiation_wm2, wind_speed_100m_kmh, ? FROM weather_load",
            [ZONE, loaded_at],
        )
        con.execute("DROP TABLE weather_load")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return len(rows)


# --- orchestration ---------------------------------------------------------------------------------------------------


def run_ingest(start_text: str, end_text: str) -> int:
    """Run `ingest weather`. Exit 0 all hours loaded, 1 source failure or missing hours, 2 bad input or window."""
    try:
        start = parse_date(start_text)
        end = parse_date(end_text)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if start > end:
        print(f"error: --start {start} is after --end {end}", file=sys.stderr)
        return 2

    lo, hi = allowed_window(utc_now().date())
    if start < lo or end > hi:
        print(
            f"error: --start/--end outside the allowed window {lo} to {hi} "
            f"({SOURCE} forecast serves today-{PAST_DAYS} to today+{FUTURE_DAYS} days)",
            file=sys.stderr,
        )
        return 2

    try:
        fetched = fetch(start, end)
    except SourceError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    rows = select_in_range(fetched, start, end)
    missing = missing_hours(rows, start, end)

    if rows:
        loaded_at = utc_now()
        con = warehouse.connect()
        try:
            written = write(con, rows, loaded_at)
        finally:
            con.close()
        print(f"Loaded {written} weather rows for {ZONE}, {start} to {end}.")

    if missing:
        expected = len(expected_hours(start, end))
        print(
            f"error: {SOURCE} returned {len(rows)} of {expected} hours; missing: {format_hours(missing)}",
            file=sys.stderr,
        )
        return 1
    return 0
