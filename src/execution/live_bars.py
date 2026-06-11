"""Fetch recent CLOSED 1h bars from GMO public klines, for live signal generation.

Reuses the backtest importer's kline fetch/parse (same source as our data), so the
live bar series is identical in shape to what the strategies were validated on. The
still-forming current hour is dropped — strategies act only on closed bars.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import requests

from src.core.types import Bar
from src.data.import_gmo import _fetch_klines, _to_bars

_JST = timezone(timedelta(hours=9))


def recent_bars(symbol: str, *, days: int = 25, interval: str = "1hour") -> list[Bar]:
    """Return recent CLOSED ``interval`` bars for ``symbol`` (newest last).

    Args:
        symbol: GMO symbol (``BTC_JPY`` / ``XRP_JPY`` / ``ETH_JPY``).
        days: How many JST days back to pull (≈ ``24 × days`` hourly bars). The
            combo book needs ≳520 bars (vol_expansion rank window) — 25 days is safe.
        interval: GMO kline interval (``1hour``).

    Returns:
        Time-sorted bars strictly before the current (still-forming) hour.
    """
    session = requests.Session()
    today = datetime.now(_JST).date()
    out: list[Bar] = []
    for k in range(days, -1, -1):
        day = today - timedelta(days=k)
        out.extend(_to_bars(_fetch_klines(session, symbol, interval, day) or []))
        time.sleep(0.25)  # public rate-limit courtesy
    out.sort(key=lambda b: b.timestamp)
    current_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return [b for b in out if b.timestamp < current_hour]
