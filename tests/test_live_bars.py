"""Tests for the live bar feed's completed-day cache.

The cache exists to keep the hourly reconcile off GMO's rate limiter — every second
of backoff lands between the bar close and the entry order, which is what creates
phantom fills. So the properties that matter are: a completed day is fetched once,
the CURRENT day never is cached, and a failed fetch is never persisted.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from src.execution import live_bars


def _rec(day: date, hour: int) -> dict[str, str]:
    """One raw GMO kline record for ``day`` at ``hour`` UTC."""
    ts = datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)
    return {
        "openTime": str(int(ts.timestamp() * 1000)),
        "open": "100", "high": "110", "low": "90", "close": "105", "volume": "1",
    }


@pytest.fixture()
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the cache at a temp dir and remove the courtesy sleep."""
    monkeypatch.setenv("KLINE_CACHE", str(tmp_path))
    monkeypatch.setattr(live_bars.time, "sleep", lambda _s: None)
    return tmp_path


@pytest.fixture()
def calls(monkeypatch: pytest.MonkeyPatch) -> list[date]:
    """Record every day actually fetched from the API; serve one bar per day."""
    seen: list[date] = []

    def fake(_session: Any, _symbol: str, _interval: str, day: date) -> list[dict[str, str]]:
        seen.append(day)
        return [_rec(day, 0)]

    monkeypatch.setattr(live_bars, "_fetch_klines", fake)
    return seen


def test_completed_days_are_fetched_once(cache: Path, calls: list[date]) -> None:
    """A second run hits the API only for the still-accumulating current day."""
    live_bars.recent_bars("BTC_JPY", days=3)
    assert len(calls) == 4  # days 3,2,1 back + today
    today = datetime.now(live_bars._JST).date()

    calls.clear()
    live_bars.recent_bars("BTC_JPY", days=3)
    assert calls == [today], "completed days must come from the cache"


def test_current_day_is_never_cached(cache: Path, calls: list[date]) -> None:
    """Today is still accumulating bars — caching it would freeze a partial day."""
    live_bars.recent_bars("BTC_JPY", days=1)
    today = datetime.now(live_bars._JST).date()
    assert not live_bars._cache_file("BTC_JPY", "1hour", today).exists()
    assert live_bars._cache_file("BTC_JPY", "1hour", today - timedelta(days=1)).exists()


def test_failed_fetch_is_not_cached(cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A throttled day must not be frozen as permanently missing."""
    monkeypatch.setattr(live_bars, "_fetch_klines", lambda *_a, **_k: None)
    live_bars.recent_bars("BTC_JPY", days=2)
    assert list(cache.glob("*.json")) == []


def test_corrupt_cache_falls_back_to_the_api(cache: Path, calls: list[date]) -> None:
    """A torn cache file costs one request, never a trading cycle."""
    live_bars.recent_bars("BTC_JPY", days=1)
    yesterday = datetime.now(live_bars._JST).date() - timedelta(days=1)
    path = live_bars._cache_file("BTC_JPY", "1hour", yesterday)
    path.write_text("{not json", encoding="utf-8")

    calls.clear()
    bars = live_bars.recent_bars("BTC_JPY", days=1)
    assert yesterday in calls
    assert bars, "the day must still be served after a corrupt read"


def test_cached_bars_match_a_live_fetch(cache: Path, calls: list[date]) -> None:
    """The cache round-trip must not alter the bar series the strategy replays."""
    first = live_bars.recent_bars("BTC_JPY", days=3)
    second = live_bars.recent_bars("BTC_JPY", days=3)
    assert [(b.timestamp, b.open, b.high, b.low, b.close, b.volume) for b in first] == \
           [(b.timestamp, b.open, b.high, b.low, b.close, b.volume) for b in second]


def test_symbols_and_intervals_do_not_share_cache_entries(
    cache: Path, calls: list[date]
) -> None:
    """A cache key collision would feed one book another book's prices."""
    live_bars.recent_bars("BTC_JPY", days=1)
    calls.clear()
    live_bars.recent_bars("XRP_JPY", days=1)
    assert len(calls) == 2, "XRP must not read BTC's cached day"


def test_prune_drops_only_stale_entries(cache: Path, calls: list[date]) -> None:
    """The cache is bounded, but a day still inside the window survives."""
    live_bars.recent_bars("BTC_JPY", days=2)
    stale = cache / "BTC_JPY_1hour_20200101.json"
    stale.write_text(json.dumps([_rec(date(2020, 1, 1), 0)]), encoding="utf-8")
    old = live_bars.time.time() - (live_bars._CACHE_KEEP_DAYS + 1) * 86400
    os.utime(stale, (old, old))

    live_bars._prune_cache()
    assert not stale.exists()
    fresh = live_bars._cache_file(
        "BTC_JPY", "1hour", datetime.now(live_bars._JST).date() - timedelta(days=1)
    )
    assert fresh.exists()
