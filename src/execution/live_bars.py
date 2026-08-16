"""Fetch recent CLOSED 1h bars from GMO public klines, for live signal generation.

Reuses the backtest importer's kline fetch/parse (same source as our data), so the
live bar series is identical in shape to what the strategies were validated on. The
still-forming current hour is dropped — strategies act only on closed bars.

Completed JST days are **immutable**, so they are cached on disk and fetched exactly
once; only the current day is re-fetched each run. Before caching, every hourly run
re-downloaded ~25 unchanged days per book — 52 requests per cycle across two books,
enough to trip GMO's rate limit and send :func:`_fetch_klines` up its 3→6→12→24→48s
backoff ladder. Those stalls are visible in ``logs/orders.jsonl`` as runs landing at
``:07`` instead of ``:05``, and every second of them sits between the bar close and
the entry order reaching the exchange — the exact window that manufactures phantom
fills (a limit the simulator fills against the whole bar, which the live order was
not yet resting for). See ``docs/deploy.md``.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from loguru import logger

from src.core.types import Bar
from src.data.import_gmo import _fetch_klines, _to_bars

_JST = timezone(timedelta(hours=9))
_CACHE_DEFAULT = Path(__file__).resolve().parents[2] / "logs" / "kline_cache"
_CACHE_KEEP_DAYS = 90  # prune beyond this so the cache cannot grow without bound
_FETCH_SLEEP_S = 0.25  # public rate-limit courtesy, paid only on a real request


def cache_dir() -> Path:
    """Resolve the kline cache directory (``KLINE_CACHE`` env or ``logs/kline_cache``)."""
    return Path(os.environ.get("KLINE_CACHE") or _CACHE_DEFAULT)


def _cache_file(symbol: str, interval: str, day: date) -> Path:
    """Path of one completed day's cached klines."""
    return cache_dir() / f"{symbol}_{interval}_{day:%Y%m%d}.json"


def _read_cache(path: Path) -> list[dict[str, str]] | None:
    """Load one cached day, or None when absent/unreadable/empty.

    Any problem degrades to a re-fetch rather than raising: a corrupt cache file must
    cost one request, never a trading cycle.
    """
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, list) or not data:
        return None
    return data


def _write_cache(path: Path, records: list[dict[str, str]]) -> None:
    """Persist one completed day. Never raises into the caller (caching != trading).

    Written to a per-process temp file and renamed, so neither an interrupted write nor
    a second process writing the same day can leave a torn file that later reads back
    as a valid — but short — day.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(records, fh)
        tmp.replace(path)
    except OSError as e:
        logger.warning("kline cache write failed for {}: {}", path.name, e)


def _prune_cache(now: float | None = None) -> None:
    """Delete cached days older than ``_CACHE_KEEP_DAYS``. Best-effort, never raises."""
    cutoff = (now if now is not None else time.time()) - _CACHE_KEEP_DAYS * 86400
    try:
        for f in cache_dir().glob("*.json"):
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
    except OSError as e:
        logger.warning("kline cache prune failed: {}", e)


def _day_records(
    session: requests.Session, symbol: str, interval: str, day: date, today: date
) -> list[dict[str, str]]:
    """One JST day's raw klines, served from the cache when the day is complete.

    Only days strictly before ``today`` (JST) are cacheable — the current day is still
    accumulating bars. An empty or failed fetch is never cached: :func:`_fetch_klines`
    returns ``None`` once it exhausts its retries, and persisting that would turn a
    single throttled request into a permanently missing day in every future replay.

    Args:
        session: Reusable HTTP session.
        symbol: GMO symbol.
        interval: GMO kline interval.
        day: The JST day to fetch.
        today: The current JST date — the cacheability boundary.

    Returns:
        The day's raw kline dicts (empty when unavailable).
    """
    if day >= today:
        return _fetch(session, symbol, interval, day)
    path = _cache_file(symbol, interval, day)
    cached = _read_cache(path)
    if cached is not None:
        return cached
    records = _fetch(session, symbol, interval, day)
    if records:
        _write_cache(path, records)
    return records


def _fetch(
    session: requests.Session, symbol: str, interval: str, day: date
) -> list[dict[str, str]]:
    """Fetch one day from the API, paying the rate-limit courtesy sleep."""
    records = _fetch_klines(session, symbol, interval, day) or []
    time.sleep(_FETCH_SLEEP_S)
    return records


def recent_bars(symbol: str, *, days: int = 25, interval: str = "1hour") -> list[Bar]:
    """Return recent CLOSED ``interval`` bars for ``symbol`` (newest last).

    Args:
        symbol: GMO symbol (``BTC_JPY`` / ``XRP_JPY`` / ``ETH_JPY``).
        days: How many JST days back to pull (≈ ``24 × days`` hourly bars).
            **Do not shrink this to save requests** — the day cache does that safely
            instead. The replay must be long enough to both (a) warm up the strategy's
            longest lookback (``density_pullback.window`` = 168 bars for the value-area
            box, plus ``max_base_bars`` = 64 of base-length history ⇒ ~232 bars before
            the first valid signal) and (b) still contain the ENTRY of every position
            currently open — which for a trail ride is open-ended (the live XRP short
            reached 93 bars). A window that drops an open position's entry makes the
            strategy stop wanting it, and :func:`live_executor.reconcile` closes an
            unwanted live position at MARKET. Shortening this therefore silently
            flattens live trades. At 25 days (~609 bars) the headroom is ~284 bars of
            additional hold; the combo book's vol_expansion rank window also needs
            ≳520 bars.
        interval: GMO kline interval (``1hour``).

    Returns:
        Time-sorted bars strictly before the current (still-forming) hour.
    """
    session = requests.Session()
    today = datetime.now(_JST).date()
    out: list[Bar] = []
    for k in range(days, -1, -1):
        day = today - timedelta(days=k)
        out.extend(_to_bars(_day_records(session, symbol, interval, day, today)))
    out.sort(key=lambda b: b.timestamp)
    _prune_cache()
    current_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return [b for b in out if b.timestamp < current_hour]
