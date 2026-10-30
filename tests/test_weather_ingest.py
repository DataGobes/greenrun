"""End-to-end tests for `python -m greenrun ingest weather` (BAKE-001, AC-1..AC-15), all offline."""

import itertools
import urllib.error
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import duckdb
import pytest
from conftest import REAL_HTTP_GET, NetworkBlocked, fake_response, fake_values

from greenrun.__main__ import main

START, END = "2026-10-01", "2026-10-07"
FAILURES = {
    "http-500": urllib.error.HTTPError("u", 500, "Server Error", None, None),
    "url-error": urllib.error.URLError("connection refused"),
    "timeout": TimeoutError("timed out"),
    "non-json": b"<html>502 Bad Gateway</html>",
}


def ingest(start=START, end=END) -> int:
    return main(["ingest", "weather", "--start", start, "--end", end])


def query(offline, sql, params=None):
    con = duckdb.connect(str(offline.db), read_only=True)
    try:
        return con.execute(sql, params or []).fetchall()
    finally:
        con.close()


def table(offline):
    return query(offline, "SELECT * FROM raw.weather_hourly ORDER BY bidding_zone, hour_utc")


def load(offline, start=START, end=END, **kwargs) -> int:
    offline.http.script = [fake_response(start, end, **kwargs)]
    return ingest(start, end)


# AC-1
def test_loads_one_row_per_utc_hour(offline, capsys):
    assert load(offline) == 0
    rows = query(
        offline,
        "SELECT count(*), count(DISTINCT hour_utc), min(hour_utc), max(hour_utc) "
        "FROM raw.weather_hourly WHERE bidding_zone = 'DE-LU'",
    )
    assert rows == [(168, 168, datetime(2026, 10, 1, 0), datetime(2026, 10, 7, 23))]
    hours = [r[0] for r in query(offline, "SELECT hour_utc FROM raw.weather_hourly ORDER BY 1")]
    assert all(b - a == timedelta(hours=1) for a, b in itertools.pairwise(hours))
    out, err = capsys.readouterr()
    assert out == "Loaded 168 weather rows for DE-LU, 2026-10-01 to 2026-10-07.\n"
    assert err == ""


# AC-2
def test_columns_and_values_match_source(offline):
    assert load(offline) == 0
    described = query(offline, "DESCRIBE raw.weather_hourly")
    assert [(r[0], r[1]) for r in described] == [
        ("bidding_zone", "VARCHAR"),
        ("hour_utc", "TIMESTAMP"),
        ("temperature_c", "DOUBLE"),
        ("solar_radiation_wm2", "DOUBLE"),
        ("wind_speed_100m_kmh", "DOUBLE"),
        ("loaded_at", "TIMESTAMP"),
    ]
    rows = table(offline)
    assert {r[0] for r in rows} == {"DE-LU"}
    for i in (0, 13, 167):
        source = fake_values(i)
        assert rows[i][2:5] == (source["temperature_2m"], source["shortwave_radiation"], source["wind_speed_100m"])
    assert {r[5] for r in rows} == {offline.clock.now}


# AC-3
def test_request_url(offline):
    assert load(offline) == 0
    [url] = offline.http.urls
    parts = urlsplit(url)
    assert (parts.scheme, parts.netloc, parts.path) == ("https", "api.open-meteo.com", "/v1/forecast")
    query_params = parse_qs(parts.query)
    assert query_params == {
        "latitude": ["51.17"],
        "longitude": ["10.45"],
        "hourly": ["temperature_2m,shortwave_radiation,wind_speed_100m"],
        "start_date": [START],
        "end_date": [END],
        "timezone": ["UTC"],
    }


# AC-4, AC-14
@pytest.mark.parametrize(("start", "end"), [("2026-07-19", "2026-07-25"), ("2026-10-21", "2026-10-28")])
def test_window_refused(offline, capsys, start, end):
    assert ingest(start, end) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "2026-07-20" in err and "2026-10-27" in err
    assert offline.http.calls == []
    assert not offline.db.exists()


@pytest.mark.parametrize(("start", "end"), [("2026-07-20", "2026-07-20"), ("2026-10-27", "2026-10-27")])
def test_window_bounds_allowed(offline, start, end):
    assert load(offline, start, end) == 0
    assert query(offline, "SELECT count(*) FROM raw.weather_hourly") == [(24,)]


def test_window_uses_utc_date(offline):
    offline.clock.now = datetime(2026, 10, 20, 23, 30)  # already 21 Oct in Berlin, still 20 Oct in UTC
    assert ingest("2026-10-21", "2026-10-28") == 2


# AC-5, AC-14
@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-13-01", END),
        ("2026/10/01", END),
        ("20261001", END),
        (START, "2026-10-32"),
        ("2026-10-07", "2026-10-01"),
    ],
)
def test_bad_input(offline, capsys, start, end):
    assert ingest(start, end) == 2
    out, err = capsys.readouterr()
    assert out == "" and err.startswith("error:")
    assert offline.http.calls == []
    assert not offline.db.exists()


def test_missing_flag_exits_2(offline):
    with pytest.raises(SystemExit) as raised:
        main(["ingest", "weather", "--start", START])
    assert raised.value.code == 2
    assert offline.http.calls == []


# AC-6
def test_rerun_newest_load_wins(offline):
    first_at = offline.clock.now
    assert load(offline) == 0
    second_at = offline.clock.advance(hours=1)
    assert load(offline, offset=50.0) == 0
    rows = table(offline)
    assert len(rows) == 168
    assert query(offline, "SELECT count(DISTINCT (bidding_zone, hour_utc)) FROM raw.weather_hourly") == [(168,)]
    assert {r[5] for r in rows} == {second_at} != {first_at}
    assert rows[0][2] == fake_values(0, 50.0)["temperature_2m"]


# AC-7
def test_overlapping_range_replaces_only_overlap(offline):
    first_at = offline.clock.now
    assert load(offline, "2026-10-01", "2026-10-03") == 0
    first = {r[1]: r for r in table(offline)}
    second_at = offline.clock.advance(hours=2)
    assert load(offline, "2026-10-03", "2026-10-05", offset=50.0) == 0
    rows = table(offline)
    assert len(rows) == 120
    for row in rows:
        if row[1] < datetime(2026, 10, 3):
            assert row == first[row[1]]
            assert row[5] == first_at
        else:
            assert row[5] == second_at
    oct3 = next(r for r in rows if r[1] == datetime(2026, 10, 3, 0))
    assert oct3[2] == fake_values(0, 50.0)["temperature_2m"]


# AC-8, AC-14
@pytest.mark.parametrize("failure", list(FAILURES.values()), ids=list(FAILURES))
def test_all_attempts_fail(offline, capsys, failure):
    assert load(offline) == 0
    before = table(offline)
    capsys.readouterr()
    offline.clock.advance(hours=1)
    offline.http.script = [failure] * 4
    offline.http.calls.clear()
    assert ingest() == 1
    assert len(offline.http.calls) == 4
    out, err = capsys.readouterr()
    assert out == ""
    assert "Open-Meteo" in err
    assert table(offline) == before


# AC-9
def test_two_failures_then_success(offline):
    offline.http.script = [FAILURES["http-500"], FAILURES["timeout"], fake_response(START, END)]
    assert ingest() == 0
    assert len(offline.http.calls) == 3
    assert query(offline, "SELECT count(*) FROM raw.weather_hourly") == [(168,)]


# AC-10
def test_null_stored_as_null(offline):
    overrides = {
        "2026-10-02 12:00": {"temperature_2m": None},
        "2026-10-02 13:00": {"shortwave_radiation": None},
        "2026-10-02 14:00": {"wind_speed_100m": None},
    }
    assert load(offline, overrides=overrides) == 0
    rows = {
        r[0].hour: r[1:]
        for r in query(
            offline,
            "SELECT hour_utc, temperature_c, solar_radiation_wm2, wind_speed_100m_kmh FROM raw.weather_hourly "
            "WHERE hour_utc BETWEEN '2026-10-02 12:00' AND '2026-10-02 14:00'",
        )
    }
    assert rows[12][0] is None and None not in rows[12][1:]
    assert rows[13][1] is None and rows[13][0] is not None and rows[13][2] is not None
    assert rows[14][2] is None and None not in rows[14][:2]
    assert query(offline, "SELECT count(*) FROM raw.weather_hourly") == [(168,)]


# AC-11
def test_no_network_used(offline):
    with pytest.raises(NetworkBlocked):
        REAL_HTTP_GET("https://api.open-meteo.com/v1/forecast", 1)
    assert load(offline) == 0
    assert len(offline.http.calls) == 1  # every call went to the fake


# AC-12
def test_partial_response_loads_and_exits_1(offline, capsys):
    seed_at = offline.clock.now
    assert load(offline, "2026-10-07", "2026-10-07") == 0
    seeded = {r[1]: r for r in table(offline)}
    capsys.readouterr()
    run_at = offline.clock.advance(hours=1)
    missing = ["2026-10-07 21:00", "2026-10-07 22:00", "2026-10-07 23:00"]
    assert load(offline, drop=missing, offset=50.0) == 1
    out, err = capsys.readouterr()
    assert out == "Loaded 165 weather rows for DE-LU, 2026-10-01 to 2026-10-07.\n"
    assert "returned 165 of 168 hours" in err
    assert "2026-10-07 21:00..2026-10-07 23:00" in err
    rows = table(offline)
    assert len(rows) == 168
    kept = [r for r in rows if r[1] >= datetime(2026, 10, 7, 21)]
    assert kept == [seeded[r[1]] for r in kept]
    assert {r[5] for r in kept} == {seed_at}
    assert {r[5] for r in rows if r[1] < datetime(2026, 10, 7, 21)} == {run_at}


def test_empty_response_exits_1_writes_nothing(offline, capsys):
    every_hour = [datetime(2026, 10, 1, h) for h in range(24)]
    offline.http.script = [fake_response(START, START, drop=every_hour)]
    assert ingest(START, START) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert "returned 0 of 24 hours" in err
    assert not offline.db.exists()


# AC-13
def test_out_of_range_hours_dropped(offline):
    assert load(offline, "2026-10-08", "2026-10-08") == 0
    seeded = [r for r in table(offline) if r[1] == datetime(2026, 10, 8, 0)]
    offline.clock.advance(hours=1)
    assert load(offline, extra=["2026-09-30 23:00", "2026-10-08 00:00"], offset=50.0) == 0
    rows = table(offline)
    assert [r for r in rows if r[1] == datetime(2026, 10, 8, 0)] == seeded
    assert not [r for r in rows if r[1] < datetime(2026, 10, 1)]
    assert len([r for r in rows if r[1].date() <= date(2026, 10, 7)]) == 168


# AC-14
def test_refused_and_failed_runs_create_nothing(offline):
    assert ingest("2026-10-07", "2026-10-01") == 2
    assert ingest("2026-01-01", "2026-01-02") == 2
    offline.http.script = [FAILURES["url-error"]] * 4
    assert ingest() == 1
    assert not offline.db.exists()
    assert not offline.db.parent.exists()


# AC-15
def test_4xx_is_retried(offline):
    offline.http.script = [urllib.error.HTTPError("u", 400, "Bad Request", None, None)] * 4
    assert ingest() == 1
    assert len(offline.http.calls) == 4


def test_timeout_and_wait(offline):
    offline.http.script = [FAILURES["timeout"]] * 4
    assert ingest() == 1
    assert offline.http.timeouts == [30] * 4
    assert offline.sleeps == [1.0, 1.0, 1.0]

    offline.sleeps.clear()
    offline.http.calls.clear()
    assert load(offline) == 0
    assert offline.http.timeouts == [30]
    assert offline.sleeps == []


def test_cli_help_lists_ingest_weather(capsys):
    with pytest.raises(SystemExit) as raised:
        main(["ingest", "weather", "--help"])
    assert raised.value.code == 0
    out = capsys.readouterr().out
    assert "--start" in out and "--end" in out
