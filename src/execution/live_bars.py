"""Fetch recent CLOSED 1h bars from GMO public klines, for live signal generation.

Reuses the backtest importer's kline fetch/parse (same source as our data), so the
live bar series is identical in shape to what the strategies were validated on. The
still-forming current hour is dropped — strategies act only on closed bars.

Completed GMO trading days are **immutable**, so they are cached on disk and fetched
exactly once; only the day still accumulating is re-fetched each run. A GMO kline
``date=D`` bucket is **not** the calendar day: it runs 06:00 JST on D to 06:00 JST on
D+1. Before caching, every hourly run re-downloaded ~25 unchanged days per book — 52
requests per cycle across two books, enough to trip GMO's rate limit and send :func:`_fetch_klines` up its 3→6→12→24→48s
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
# A GMO kline ``date=D`` bucket spans 06:00 JST on D → 06:00 JST on D+1, so a day is
# only complete six hours after calendar midnight. Freezing it at midnight instead cost
# the live feed the 01:00–05:00 JST bars permanently and froze the 00:00 JST bar
# mid-formation — see :func:`_trading_day`.
_DAY_START_HOUR_JST = 6
_CACHE_DEFAULT = Path(__file__).resolve().parents[2] / "logs" / "kline_cache"
_CACHE_KEEP_DAYS = 90  # prune beyond this so the cache cannot grow without bound
_FETCH_SLEEP_S = 0.25  # public rate-limit courtesy, paid only on a real request


def cache_dir() -> Path:
    """Resolve the kline cache directory (``KLINE_CACHE`` env or ``logs/kline_cache``)."""
    return Path(os.environ.get("KLINE_CACHE") or _CACHE_DEFAULT)


def _now_jst() -> datetime:
    """Current time in JST. A seam so the day-boundary logic is testable."""
    return datetime.now(_JST)


def _trading_day(now: datetime) -> date:
    """The GMO trading day currently accumulating bars.

    GMO buckets klines by a day that starts at 06:00 JST, so between midnight and
    06:00 JST the bars still landing belong to *yesterday's* ``date=`` bucket. Using
    the calendar date here is what truncated every cached day at 18 of its 24 bars.
    """
    return (now - timedelta(hours=_DAY_START_HOUR_JST)).date()


def _cache_file(symbol: str, interval: str, day: date) -> Path:
    """Path of one completed day's cached klines."""
    return cache_dir() / f"{symbol}_{interval}_{day:%Y%m%d}.json"


def _read_cache(path: Path) -> list[dict[str, str]] | None:
    """Load one cached day, or None when absent/unreadable/unusable.

    Any problem degrades to a re-fetch rather than raising: a corrupt cache file must
    cost one request, never a trading cycle.

    A **bare list** is the pre-fix format, written whenever a day looked complete at
    calendar midnight — six hours early. Every such file is short by the 01:00–05:00
    JST bars and ends on a partial 00:00 JST bar, so it is rejected here: the day is
    re-fetched once and rewritten whole. No manual cache purge is needed on deploy.
    """
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None  # pre-fix bare list: truncated at midnight, must be re-fetched
    records = data.get("records")
    if not isinstance(records, list) or not records:
        return None
    return records


def _write_cache(
    path: Path, records: list[dict[str, str]], *, fetched_at: datetime
) -> None:
    """Persist one completed day. Never raises into the caller (caching != trading).

    Written to a per-process temp file and renamed, so neither an interrupted write nor
    a second process writing the same day can leave a torn file that later reads back
    as a valid — but short — day.

    ``fetched_at`` is stamped in mainly to distinguish this envelope from the pre-fix
    bare list, which carried no record of whether the day had actually closed when it
    was written.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump({"fetched_at": fetched_at.isoformat(), "records": records}, fh)
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
    session: requests.Session, symbol: str, interval: str, day: date, current: date,
    *, now: datetime
) -> list[dict[str, str]]:
    """One GMO trading day's raw klines, served from the cache when the day is closed.

    Only days strictly before ``current`` are cacheable — ``current`` is still
    accumulating bars. An empty or failed fetch is never cached: :func:`_fetch_klines`
    returns ``None`` once it exhausts its retries, and persisting that would turn a
    single throttled request into a permanently missing day in every future replay.

    Args:
        session: Reusable HTTP session.
        symbol: GMO symbol.
        interval: GMO kline interval.
        day: The GMO trading day to fetch.
        current: The trading day still accumulating — the cacheability boundary
            (:func:`_trading_day`, **not** the calendar date).
        now: Fetch time, stamped into any file written.

    Returns:
        The day's raw kline dicts (empty when unavailable).
    """
    if day >= current:
        return _fetch(session, symbol, interval, day)
    path = _cache_file(symbol, interval, day)
    cached = _read_cache(path)
    if cached is not None:
        return cached
    records = _fetch(session, symbol, interval, day)
    if records:
        _write_cache(path, records, fetched_at=now)
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

    The window walks GMO **trading** days (06:00 JST → 06:00 JST), not calendar days.
    Walking calendar days additionally requested a bucket that had not begun during
    00:00–06:00 JST, and its 404 sent :func:`_fetch_klines` up the full 3→6→12→24→48s
    retry ladder — ~93s of dead time between the bar close and the entry order, on
    every one of those six runs a day.

    Args:
        symbol: GMO symbol (``BTC_JPY`` / ``XRP_JPY`` / ``ETH_JPY``).
        days: How many trading days back to pull (≈ ``24 × days`` hourly bars).
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
    now = _now_jst()
    current = _trading_day(now)
    out: list[Bar] = []
    for k in range(days, -1, -1):
        day = current - timedelta(days=k)
        out.extend(
            _to_bars(_day_records(session, symbol, interval, day, current, now=now))
        )
    out.sort(key=lambda b: b.timestamp)
    _prune_cache()
    current_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return [b for b in out if b.timestamp < current_hour]
