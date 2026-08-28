"""Tests for the live bar feed's completed-day cache.

The cache exists to keep the hourly reconcile off GMO's rate limiter — every second
of backoff lands between the bar close and the entry order, which is what creates
phantom fills. So the properties that matter are: a completed day is fetched once,
the day still ACCUMULATING is never cached, and a failed fetch is never persisted.

The fake API here serves a GMO ``date=D`` bucket as it really is — 24 hourly bars from
06:00 JST on D to 05:00 JST on D+1, truncated to the frozen clock. The original suite
modelled it as one bar on a calendar day, which is precisely why it passed while live
cached every day six hours early and lost the 01:00–05:00 JST bars for good.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from src.execution import live_bars


# Frozen clock: 02:00 JST — inside the window where the calendar date has rolled over
# but GMO's previous bucket is still six hours from closing.
_NOW = datetime(2026, 8, 29, 2, 0, tzinfo=live_bars._JST)


def _rec(ts: datetime) -> dict[str, str]:
    """One raw GMO kline record opening at ``ts``."""
    return {
        "openTime": str(int(ts.timestamp() * 1000)),
        "open": "100", "high": "110", "low": "90", "close": "105", "volume": "1",
    }


def _bucket(day: date, *, now: datetime = _NOW) -> list[dict[str, str]]:
    """The klines GMO returns for ``date=day``: 06:00 JST on ``day`` → 05:00 JST next.

    Truncated at ``now``, which is what makes an in-progress bucket short — the exact
    shape the cache must refuse to freeze.
    """
    start = datetime(day.year, day.month, day.day, live_bars._DAY_START_HOUR_JST,
                     tzinfo=live_bars._JST)
    return [_rec(start + timedelta(hours=h)) for h in range(24)
            if start + timedelta(hours=h) < now]


@pytest.fixture()
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the cache at a temp dir, freeze the clock, remove the courtesy sleep."""
    monkeypatch.setenv("KLINE_CACHE", str(tmp_path))
    monkeypatch.setattr(live_bars.time, "sleep", lambda _s: None)
    monkeypatch.setattr(live_bars, "_now_jst", lambda: _NOW)
    return tmp_path


@pytest.fixture()
def calls(monkeypatch: pytest.MonkeyPatch) -> list[date]:
    """Record every day actually fetched; serve that day's bucket as GMO would."""
    seen: list[date] = []

    def fake(_session: Any, _symbol: str, _interval: str, day: date) -> list[dict[str, str]]:
        seen.append(day)
        return _bucket(day)

    monkeypatch.setattr(live_bars, "_fetch_klines", fake)
    return seen


def test_completed_days_are_fetched_once(cache: Path, calls: list[date]) -> None:
    """A second run hits the API only for the still-accumulating trading day."""
    live_bars.recent_bars("BTC_JPY", days=3)
    assert len(calls) == 4  # days 3,2,1 back + the one in progress
    current = live_bars._trading_day(_NOW)

    calls.clear()
    live_bars.recent_bars("BTC_JPY", days=3)
    assert calls == [current], "completed days must come from the cache"


def test_current_day_is_never_cached(cache: Path, calls: list[date]) -> None:
    """The accumulating day is still filling — caching it would freeze a partial day."""
    live_bars.recent_bars("BTC_JPY", days=1)
    current = live_bars._trading_day(_NOW)
    assert not live_bars._cache_file("BTC_JPY", "1hour", current).exists()
    assert live_bars._cache_file("BTC_JPY", "1hour", current - timedelta(days=1)).exists()


def test_yesterdays_bucket_is_live_until_0600_jst(cache: Path, calls: list[date]) -> None:
    """The bug: at 02:00 JST the previous CALENDAR day is 6 hours from closing.

    GMO's ``date=D`` bucket runs 06:00 JST on D → 06:00 JST on D+1. Treating the
    calendar rollover as the boundary froze that bucket at 18 of its 24 bars, so the
    01:00–05:00 JST bars never entered the live series again and the 00:00 JST bar was
    cached mid-formation.
    """
    live_bars.recent_bars("BTC_JPY", days=1)
    yesterday = (_NOW - timedelta(days=1)).date()  # 2026-08-28, still accumulating
    assert not live_bars._cache_file("BTC_JPY", "1hour", yesterday).exists()
    assert yesterday in calls, "the in-progress bucket must be re-fetched every run"


def test_no_request_for_a_bucket_that_has_not_started(
    cache: Path, calls: list[date]
) -> None:
    """At 02:00 JST today's bucket opens at 06:00 — asking for it is a 404.

    That 404 is indistinguishable from throttling, so it cost the full 3→6→12→24→48s
    retry ladder: ~93s of dead time between the bar close and the entry order, on each
    of the six runs between midnight and 06:00 JST.
    """
    live_bars.recent_bars("BTC_JPY", days=2)
    assert _NOW.date() not in calls
    assert max(calls) == live_bars._trading_day(_NOW)


def test_a_full_day_survives_the_cache_round_trip(cache: Path, calls: list[date]) -> None:
    """A day cached after 06:00 JST keeps all 24 of its bars."""
    day = (_NOW - timedelta(days=2)).date()
    live_bars.recent_bars("BTC_JPY", days=3)
    records = live_bars._read_cache(live_bars._cache_file("BTC_JPY", "1hour", day))
    assert records is not None and len(records) == 24


def test_pre_fix_cache_files_are_refetched(cache: Path, calls: list[date]) -> None:
    """Truncated bare-list files from the old format must not be trusted on upgrade."""
    day = (_NOW - timedelta(days=2)).date()
    path = live_bars._cache_file("BTC_JPY", "1hour", day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_bucket(day)[:18]), encoding="utf-8")  # midnight-truncated

    live_bars.recent_bars("BTC_JPY", days=3)
    assert day in calls, "a pre-fix bare list must be re-fetched, not replayed"
    records = live_bars._read_cache(path)
    assert records is not None and len(records) == 24, "and rewritten whole"


def test_failed_fetch_is_not_cached(cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A throttled day must not be frozen as permanently missing."""
    monkeypatch.setattr(live_bars, "_fetch_klines", lambda *_a, **_k: None)
    live_bars.recent_bars("BTC_JPY", days=2)
    assert list(cache.glob("*.json")) == []


def test_corrupt_cache_falls_back_to_the_api(cache: Path, calls: list[date]) -> None:
    """A torn cache file costs one request, never a trading cycle."""
    live_bars.recent_bars("BTC_JPY", days=1)
    yesterday = live_bars._trading_day(_NOW) - timedelta(days=1)
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
    stale.write_text(json.dumps({"records": _bucket(date(2020, 1, 1))}), encoding="utf-8")
    old = live_bars.time.time() - (live_bars._CACHE_KEEP_DAYS + 1) * 86400
    os.utime(stale, (old, old))

    live_bars._prune_cache()
    assert not stale.exists()
    fresh = live_bars._cache_file(
        "BTC_JPY", "1hour", live_bars._trading_day(_NOW) - timedelta(days=1)
    )
    assert fresh.exists()
