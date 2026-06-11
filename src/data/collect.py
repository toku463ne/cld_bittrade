"""OHLCV collection entrypoint.

Pulls executions from the active feed (mock unless ``USE_LIVE_API=true``),
aggregates them into bars and upserts them into the ``ohlcv`` table.

Usage::

    uv run --env-file .env.dev python -m src.data.collect --timeframe 5m
"""

from __future__ import annotations

import argparse
from datetime import datetime

from loguru import logger
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.config import get_settings
from src.core.types import Bar, Timeframe
from src.data.feed import get_feed
from src.data.ohlcv import aggregate_ticks
from src.db import get_session
from src.logging_setup import configure_logging
from src.mock.mock_api import _ISO
from src.models import OHLCV


def _parse_exec_date(raw: str) -> datetime:
    """Parse a bitFlyer ``exec_date`` string into a UTC datetime.

    Live timestamps carry variable sub-second precision and a trailing ``Z``
    (e.g. ``2024-05-31T12:34:56.1234567Z``); the mock emits 3-digit precision.
    Both are normalised to UTC.

    Args:
        raw: The raw ``exec_date`` value.

    Returns:
        A timezone-aware UTC :class:`datetime`.
    """
    from datetime import timezone

    text = raw.replace("Z", "")
    # Python's fromisoformat accepts at most 6 fractional digits; trim extras.
    if "." in text:
        head, frac = text.split(".", 1)
        text = f"{head}.{frac[:6]}"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        for fmt in (_ISO, "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            raise
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def collect(timeframe: Timeframe, *, max_ticks: int = 20_000) -> list[Bar]:
    """Collect executions, aggregate to bars, and persist them.

    Args:
        timeframe: Bar timeframe to build.
        max_ticks: Max executions to pull from the feed in this run.

    Returns:
        The bars that were aggregated (and upserted).
    """
    settings = get_settings()
    feed = get_feed()
    logger.info(
        "Collecting {} executions for {} @ {} (live={})",
        max_ticks,
        settings.product_code,
        timeframe.value,
        settings.use_live_api,
    )

    ticks: list[tuple[datetime, float, float]] = []
    for execution in feed.iter_history(max_ticks):
        ticks.append(
            (_parse_exec_date(execution["exec_date"]), float(execution["price"]), float(execution["size"]))
        )
        if len(ticks) >= max_ticks:
            break

    ticks.sort(key=lambda t: t[0])
    bars = aggregate_ticks(ticks, timeframe)
    logger.info("Aggregated {} ticks into {} {} bars", len(ticks), len(bars), timeframe.value)
    _upsert_bars(bars, timeframe, settings.product_code)
    return bars


def _upsert_bars(bars: list[Bar], timeframe: Timeframe, product: str) -> None:
    """Idempotently upsert bars on the (product, timeframe, timestamp) key."""
    if not bars:
        logger.warning("No bars to persist.")
        return
    rows = [
        {
            "product": product,
            "timeframe": timeframe.value,
            "timestamp": b.timestamp,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
        }
        for b in bars
    ]
    with get_session() as session:
        stmt = pg_insert(OHLCV).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_ohlcv_bar",
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
            },
        )
        session.execute(stmt)
    logger.info("Upserted {} bars into ohlcv.", len(rows))


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Collect OHLCV bars for FX_BTC_JPY.")
    parser.add_argument(
        "--timeframe",
        choices=[tf.value for tf in Timeframe],
        default="5m",
        help="Bar timeframe to build.",
    )
    parser.add_argument(
        "--max-ticks", type=int, default=20_000, help="Max executions to pull."
    )
    args = parser.parse_args()

    configure_logging(get_settings().log_level)
    collect(Timeframe(args.timeframe), max_ticks=args.max_ticks)


if __name__ == "__main__":
    main()
