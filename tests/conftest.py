"""Shared test scaffolding. Every test runs offline with a fake Open-Meteo, a fixed clock and no real sleeps."""

import json
import socket
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from greenrun import weather

REAL_HTTP_GET = weather.http_get
NOW = datetime(2026, 10, 20, 10, 0)


class NetworkBlocked(RuntimeError):
    """Raised when a test tries to open a real network connection."""


def _blocked(*args, **kwargs):
    raise NetworkBlocked("network access is blocked in tests")


def _hour_key(value: str | datetime) -> str:
    """Accept `2026-10-07 21:00`, `2026-10-07T21:00` or a datetime; return the Open-Meteo time string."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M")
    return value.replace(" ", "T")


def fake_values(index: int, offset: float = 0.0) -> dict[str, float]:
    return {
        "temperature_2m": round(5.0 + index * 0.1 + offset, 3),
        "shortwave_radiation": round(index * 1.5 + offset, 3),
        "wind_speed_100m": round(10.0 + index * 0.25 + offset, 3),
    }


def fake_response(
    start: date | str,
    end: date | str,
    overrides: dict | None = None,
    drop: list | None = None,
    extra: list | None = None,
    offset: float = 0.0,
) -> bytes:
    """An Open-Meteo-shaped body for every hour of [start, end], with optional changes.

    overrides: {hour: {variable: value}} replaces values (use None for JSON null).
    drop: hours to leave out. extra: hours to add (outside the range, for example).
    offset: added to every generated value, to tell two runs apart.
    """
    start = date.fromisoformat(str(start))
    end = date.fromisoformat(str(end))
    overrides = {_hour_key(k): v for k, v in (overrides or {}).items()}
    dropped = {_hour_key(h) for h in (drop or [])}
    times = [_hour_key(h) for h in weather.expected_hours(start, end)]
    times = [t for t in times if t not in dropped] + [_hour_key(h) for h in (extra or [])]
    hourly: dict[str, list] = {"time": [], "temperature_2m": [], "shortwave_radiation": [], "wind_speed_100m": []}
    for i, t in enumerate(times):
        values = fake_values(i, offset) | overrides.get(t, {})
        hourly["time"].append(t)
        for name in weather.VARIABLES:
            hourly[name].append(values[name])
    body = {"latitude": 51.17, "longitude": 10.45, "timezone": "GMT", "hourly": hourly}
    return json.dumps(body).encode()


@dataclass
class FakeHttp:
    """Scripted replacement for `weather.http_get`.

    Each script entry is bytes (returned as the body) or an exception instance (raised). Every call is recorded.
    """

    script: list = field(default_factory=list)
    calls: list = field(default_factory=list)

    def __call__(self, url: str, timeout: float) -> bytes:
        self.calls.append((url, timeout))
        if not self.script:
            raise AssertionError(f"unexpected HTTP call: {url}")
        result = self.script.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    @property
    def urls(self) -> list[str]:
        return [url for url, _ in self.calls]

    @property
    def timeouts(self) -> list[float]:
        return [timeout for _, timeout in self.calls]


@dataclass
class Clock:
    now: datetime = NOW

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> datetime:
        self.now = self.now + timedelta(**kwargs)
        return self.now


@dataclass
class Offline:
    http: FakeHttp
    clock: Clock
    sleeps: list
    db: Path


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path) -> Offline:
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)

    db = tmp_path / "warehouse" / "test.duckdb"
    monkeypatch.setenv("GREENRUN_DB", str(db))

    http = FakeHttp()
    clock = Clock()
    sleeps: list[float] = []
    monkeypatch.setattr(weather, "http_get", http)
    monkeypatch.setattr(weather, "utc_now", clock)
    monkeypatch.setattr(weather, "sleep", sleeps.append)
    return Offline(http=http, clock=clock, sleeps=sleeps, db=db)
