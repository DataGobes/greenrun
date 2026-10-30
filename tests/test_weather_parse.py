"""Unit tests for the pieces of `greenrun.weather` and `greenrun.warehouse`."""

import json
import urllib.error
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import duckdb
import pytest
from conftest import fake_response

from greenrun import warehouse, weather
from greenrun.weather import BadResponse, SourceError, WeatherRow

D1 = date(2026, 10, 1)
D7 = date(2026, 10, 7)


# --- warehouse -------------------------------------------------------------------------------------------------------


def test_db_path_honours_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GREENRUN_DB", str(tmp_path / "x.duckdb"))
    assert warehouse.db_path() == tmp_path / "x.duckdb"


def test_db_path_default(monkeypatch):
    monkeypatch.delenv("GREENRUN_DB", raising=False)
    assert warehouse.db_path() == Path("data/greenrun.duckdb")


def test_connect_creates_parent_dir(offline):
    con = warehouse.connect()
    con.close()
    assert offline.db.exists()


# --- dates, window, URL ----------------------------------------------------------------------------------------------


def test_parse_date_strict():
    assert weather.parse_date("2026-10-01") == D1
    for bad in ["2026-13-01", "2026/10/01", "20261001", "2026-1-01", " 2026-10-01", "2026-02-30", ""]:
        with pytest.raises(ValueError):
            weather.parse_date(bad)


def test_allowed_window():
    assert weather.allowed_window(date(2026, 10, 20)) == (date(2026, 7, 20), date(2026, 10, 27))


def test_expected_hours_24_per_day():
    hours = weather.expected_hours(D1, D7)
    assert len(hours) == 168
    assert hours[0] == datetime(2026, 10, 1, 0)
    assert hours[-1] == datetime(2026, 10, 7, 23)
    assert len(weather.expected_hours(D1, D1)) == 24


def test_build_url():
    url = weather.build_url(D1, D7)
    assert url == (
        "https://api.open-meteo.com/v1/forecast?latitude=51.17&longitude=10.45"
        "&hourly=temperature_2m,shortwave_radiation,wind_speed_100m"
        "&start_date=2026-10-01&end_date=2026-10-07&timezone=UTC"
    )
    query = parse_qs(urlsplit(url).query)
    assert not any("unit" in key for key in query)


# --- parsing ---------------------------------------------------------------------------------------------------------


def test_parse_maps_variables():
    rows = weather.parse_response(fake_response(D1, D1))
    assert len(rows) == 24
    assert rows[0] == WeatherRow(datetime(2026, 10, 1, 0), 5.0, 0.0, 10.0)


def test_parse_null():
    body = fake_response(
        D1,
        D1,
        overrides={
            "2026-10-01 03:00": {"temperature_2m": None},
            "2026-10-01 04:00": {"shortwave_radiation": None},
            "2026-10-01 05:00": {"wind_speed_100m": None},
        },
    )
    rows = {r.hour_utc.hour: r for r in weather.parse_response(body)}
    assert rows[3].temperature_c is None and rows[3].solar_radiation_wm2 is not None
    assert rows[4].solar_radiation_wm2 is None and rows[4].wind_speed_100m_kmh is not None
    assert rows[5].wind_speed_100m_kmh is None and rows[5].temperature_c is not None


def _mutated(change) -> bytes:
    body = json.loads(fake_response(D1, D1))
    change(body)
    return json.dumps(body).encode()


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"<html>busy</html>", id="not-json"),
        pytest.param(b"[]", id="not-object"),
        pytest.param(_mutated(lambda b: b.pop("hourly")), id="missing-hourly"),
        pytest.param(_mutated(lambda b: b["hourly"].pop("wind_speed_100m")), id="missing-variable"),
        pytest.param(_mutated(lambda b: b["hourly"]["temperature_2m"].pop()), id="length-mismatch"),
        pytest.param(_mutated(lambda b: b["hourly"]["time"].__setitem__(1, "2026-10-01T00:00")), id="duplicate-time"),
        pytest.param(_mutated(lambda b: b["hourly"]["time"].__setitem__(1, "2026-10-01 01:00")), id="bad-time"),
        pytest.param(_mutated(lambda b: b["hourly"]["time"].__setitem__(1, "2026-10-01T25:00")), id="invalid-time"),
        pytest.param(_mutated(lambda b: b["hourly"]["temperature_2m"].__setitem__(1, "12.0")), id="string-value"),
        pytest.param(_mutated(lambda b: b["hourly"]["temperature_2m"].__setitem__(1, True)), id="bool-value"),
    ],
)
def test_parse_rejects(body):
    with pytest.raises(BadResponse):
        weather.parse_response(body)


def test_select_in_range_drops_outside_hours():
    body = fake_response(D1, D1, extra=["2026-09-30 23:00", "2026-10-02 00:00"])
    rows = weather.parse_response(body)
    kept = weather.select_in_range(rows, D1, D1)
    assert len(rows) == 26
    assert [r.hour_utc for r in kept] == weather.expected_hours(D1, D1)


def test_missing_hours():
    rows = weather.parse_response(fake_response(D1, D1, drop=["2026-10-01 05:00"]))
    assert weather.missing_hours(rows, D1, D1) == [datetime(2026, 10, 1, 5)]


def test_format_hours():
    hours = [datetime(2026, 10, 7, h) for h in (21, 22, 23)] + [datetime(2026, 10, 1, 5)]
    assert weather.format_hours(hours) == "2026-10-01 05:00, 2026-10-07 21:00..2026-10-07 23:00 UTC"
    assert weather.format_hours([datetime(2026, 10, 7, 23), datetime(2026, 10, 8, 0)]) == (
        "2026-10-07 23:00..2026-10-08 00:00 UTC"
    )


# --- fetch -----------------------------------------------------------------------------------------------------------


def test_fetch_first_try(offline):
    offline.http.script = [fake_response(D1, D1)]
    assert len(weather.fetch(D1, D1)) == 24
    assert offline.http.timeouts == [30]
    assert offline.sleeps == []


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError("u", 400, "Bad Request", None, None),
        urllib.error.HTTPError("u", 503, "Unavailable", None, None),
        urllib.error.URLError("no route"),
        TimeoutError("timed out"),
        b"not json",
    ],
    ids=["http-400", "http-503", "url-error", "timeout", "bad-body"],
)
def test_fetch_gives_up_after_4_attempts(offline, error):
    offline.http.script = [error] * 4
    with pytest.raises(SourceError, match="Open-Meteo request failed after 4 attempts"):
        weather.fetch(D1, D1)
    assert len(offline.http.calls) == 4
    assert offline.http.timeouts == [30] * 4
    assert offline.sleeps == [1.0, 1.0, 1.0]


def test_fetch_fail_fail_succeed(offline):
    offline.http.script = [urllib.error.URLError("x"), b"{}", fake_response(D1, D1)]
    assert len(weather.fetch(D1, D1)) == 24
    assert len(offline.http.calls) == 3
    assert offline.sleeps == [1.0, 1.0]


# --- write -----------------------------------------------------------------------------------------------------------


def _rows(start, end, offset=0.0):
    return weather.parse_response(fake_response(start, end, offset=offset))


def _table(con):
    return con.execute("SELECT * FROM raw.weather_hourly ORDER BY hour_utc").fetchall()


def test_write_rerun_replaces(tmp_path):
    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    t1, t2 = datetime(2026, 10, 20, 10), datetime(2026, 10, 20, 11)
    assert weather.write(con, _rows(D1, D1), t1) == 24
    assert weather.write(con, _rows(D1, D1, offset=100), t2) == 24
    table = _table(con)
    assert len(table) == 24
    assert {r[5] for r in table} == {t2}
    assert table[0][2] == 105.0


def test_write_overlap_keeps_other_hours(tmp_path):
    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    t1, t2 = datetime(2026, 10, 20, 10), datetime(2026, 10, 20, 11)
    weather.write(con, _rows(D1, date(2026, 10, 2)), t1)
    weather.write(con, _rows(date(2026, 10, 2), date(2026, 10, 3), offset=100), t2)
    table = _table(con)
    assert len(table) == 72
    assert {r[5] for r in table if r[1].day == 1} == {t1}
    assert {r[5] for r in table if r[1].day >= 2} == {t2}


def test_write_failure_rolls_back(tmp_path):
    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    weather.write(con, _rows(D1, D1), datetime(2026, 10, 20, 10))
    before = _table(con)
    new = _rows(D1, D1, offset=100)
    with pytest.raises(duckdb.Error):
        weather.write(con, new + new[:1], datetime(2026, 10, 20, 11))  # duplicate key fails after the delete
    assert _table(con) == before


# --- run_ingest ------------------------------------------------------------------------------------------------------


def test_run_ingest_exit_codes(offline):
    offline.http.script = [fake_response(D1, D1)]
    assert weather.run_ingest("2026-10-01", "2026-10-01") == 0
    offline.http.script = [fake_response(D1, D1, drop=["2026-10-01 05:00"])]
    assert weather.run_ingest("2026-10-01", "2026-10-01") == 1
    offline.http.script = [b"x"] * 4
    assert weather.run_ingest("2026-10-01", "2026-10-01") == 1
    assert weather.run_ingest("2026-10-02", "2026-10-01") == 2
    assert weather.run_ingest("2026-10-01", "2026-11-01") == 2
