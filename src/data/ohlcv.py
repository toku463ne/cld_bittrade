"""Tick-to-OHLCV aggregation.

Aggregates raw executions into fixed-width OHLCV bars for a given timeframe.
Bar timestamps are floored to the timeframe boundary (bar open time).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from src.core.types import Bar, Timeframe


def floor_to_timeframe(ts: datetime, timeframe: Timeframe) -> datetime:
    """Floor a timestamp to the start of its timeframe bucket (UTC).

    Args:
        ts: The timestamp to floor.
        timeframe: Bar timeframe.

    Returns:
        The bucket open time in UTC.
    """
    ts = ts.astimezone(timezone.utc)
    epoch = int(ts.timestamp())
    floored = epoch - (epoch % timeframe.seconds)
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def aggregate_ticks(
    ticks: Iterable[tuple[datetime, float, float]],
    timeframe: Timeframe,
) -> list[Bar]:
    """Aggregate ``(timestamp, price, size)`` ticks into OHLCV bars.

    Args:
        ticks: Time-ordered ``(timestamp, price, size)`` tuples.
        timeframe: Target bar timeframe.

    Returns:
        Bars in ascending time order. Empty buckets are not emitted (no synthetic
        gap-filling — gaps are handled by the data cache at load time).
    """
    bars: list[Bar] = []
    cur_key: datetime | None = None
    o = h = low = c = 0.0
    vol = 0.0

    for ts, price, size in ticks:
        key = floor_to_timeframe(ts, timeframe)
        if cur_key is None:
            cur_key = key
            o = h = low = c = price
            vol = size
            continue
        if key != cur_key:
            bars.append(Bar(cur_key, o, h, low, c, vol))
            cur_key = key
            o = h = low = c = price
            vol = size
        else:
            h = max(h, price)
            low = min(low, price)
            c = price
            vol += size

    if cur_key is not None:
        bars.append(Bar(cur_key, o, h, low, c, vol))
    return bars
