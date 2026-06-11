"""Resumable OHLCV history collection.

Unlike the one-shot :mod:`src.data.collect` path, this module is **resumable**:
it stores raw executions (idempotently, keyed by exchange id), tracks per-product
cursors in ``collection_checkpoint``, and rebuilds OHLCV by aggregating the
complete contiguous raw set. Re-running extends history:

- ``--direction back``    pages deeper into the past (``before = oldest_id``).
- ``--direction forward`` catches up to now (collect ids newer than ``newest_id``).
- ``--direction both``    forward then back.

Because OHLCV is rebuilt from the full raw set, boundary bars are always correct
across separately fetched ranges.

Usage (read-only; no API key, gated by ``USE_LIVE_API``)::

    USE_LIVE_API=true uv run --env-file .env.dev python -m src.data.history \
        --direction both --max-ticks 10000 --timeframe 1m
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime

from loguru import logger
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.config import get_settings
from src.core.types import Timeframe
from src.data.collect import _parse_exec_date
from src.data.feed import get_feed
from src.data.ohlcv import aggregate_ticks
from src.db import get_session
from src.logging_setup import configure_logging
from src.models import OHLCV, CollectionCheckpoint, Execution


@dataclass(frozen=True, slots=True)
class _Cursors:
    """Snapshot of a product's stored execution-id bounds."""

    oldest_id: int | None
    newest_id: int | None


def _load_cursors(product: str) -> _Cursors:
    with get_session() as session:
        ckpt = session.get(CollectionCheckpoint, product)
        if ckpt is None:
            return _Cursors(None, None)
        return _Cursors(ckpt.oldest_id, ckpt.newest_id)


def extend_history(
    direction: str,
    max_ticks: int,
    *,
    product: str | None = None,
) -> int:
    """Fetch a new range of raw executions in ``direction`` and store them.

    Args:
        direction: ``"back"`` (deeper past) or ``"forward"`` (catch up to now).
        max_ticks: Maximum executions to fetch this run.
        product: Product code (defaults to configured).

    Returns:
        The number of NEW executions inserted (duplicates are ignored).

    Raises:
        ValueError: If ``direction`` is not ``"back"`` or ``"forward"``.
    """
    if direction not in {"back", "forward"}:
        raise ValueError("direction must be 'back' or 'forward'")
    if max_ticks <= 0:
        logger.info("Extend {} skipped (max_ticks={}).", direction, max_ticks)
        return 0

    settings = get_settings()
    prod = product or settings.product_code
    cursors = _load_cursors(prod)

    if direction == "back":
        before = cursors.oldest_id  # None on first run -> start from latest
        stop_at_id = None
    else:  # forward
        before = None  # start from latest
        stop_at_id = cursors.newest_id  # collect only ids newer than this

    feed = get_feed(prod)
    logger.info(
        "Extend {} history for {} (live={}, before={}, stop_at_id={}, max_ticks={})",
        direction,
        prod,
        settings.use_live_api,
        before,
        stop_at_id,
        max_ticks,
    )

    rows: list[dict[str, object]] = []
    for ex in feed.iter_history(max_ticks, before=before, stop_at_id=stop_at_id):
        rows.append(
            {
                "product": prod,
                "id": int(ex["id"]),
                "exec_date": _parse_exec_date(ex["exec_date"]),
                "price": float(ex["price"]),
                "size": float(ex["size"]),
                "side": (ex.get("side") or None),
            }
        )

    inserted = _store_executions(prod, rows)
    _refresh_checkpoint(prod)
    logger.info("Extend {} done: fetched {}, newly inserted {}.", direction, len(rows), inserted)
    return inserted


def _store_executions(product: str, rows: list[dict[str, object]]) -> int:
    """Idempotently insert raw executions; return the count newly inserted."""
    if not rows:
        return 0
    with get_session() as session:
        before_count = session.scalar(
            select(func.count()).select_from(Execution).where(Execution.product == product)
        )
        stmt = pg_insert(Execution).values(rows).on_conflict_do_nothing(
            index_elements=["product", "id"]
        )
        session.execute(stmt)
        session.flush()
        after_count = session.scalar(
            select(func.count()).select_from(Execution).where(Execution.product == product)
        )
    return int((after_count or 0) - (before_count or 0))


def _refresh_checkpoint(product: str) -> None:
    """Recompute the checkpoint cursors from the stored executions (authoritative)."""
    with get_session() as session:
        row = session.execute(
            select(
                func.min(Execution.id),
                func.max(Execution.id),
                func.min(Execution.exec_date),
                func.max(Execution.exec_date),
            ).where(Execution.product == product)
        ).one()
        oldest_id, newest_id, oldest_dt, newest_dt = row

        ckpt = session.get(CollectionCheckpoint, product)
        if ckpt is None:
            ckpt = CollectionCheckpoint(product=product)
            session.add(ckpt)
        ckpt.oldest_id = oldest_id
        ckpt.newest_id = newest_id
        ckpt.oldest_exec_date = oldest_dt
        ckpt.newest_exec_date = newest_dt
    logger.info(
        "Checkpoint {}: oldest_id={} newest_id={} range=[{} .. {}]",
        product,
        oldest_id,
        newest_id,
        oldest_dt,
        newest_dt,
    )


def reset_history(product: str | None = None) -> None:
    """Clear all resumable-collection state for a product.

    Deletes the product's raw ``execution`` rows, its ``collection_checkpoint``
    cursor, and the OHLCV bars derived from them. Use this to start clean (e.g.
    to remove synthetic mock data before collecting real data).

    Args:
        product: Product code (defaults to configured).
    """
    prod = product or get_settings().product_code
    with get_session() as session:
        n_exec = session.scalar(
            select(func.count()).select_from(Execution).where(Execution.product == prod)
        )
        n_ohlcv = session.scalar(
            select(func.count()).select_from(OHLCV).where(OHLCV.product == prod)
        )
        session.execute(delete(Execution).where(Execution.product == prod))
        session.execute(
            delete(CollectionCheckpoint).where(CollectionCheckpoint.product == prod)
        )
        session.execute(delete(OHLCV).where(OHLCV.product == prod))
    logger.warning(
        "Reset history for {}: deleted {} executions and {} ohlcv bars (+ checkpoint).",
        prod,
        n_exec or 0,
        n_ohlcv or 0,
    )


def rebuild_ohlcv(timeframe: Timeframe, *, product: str | None = None) -> int:
    """Rebuild OHLCV for ``timeframe`` from ALL stored raw executions.

    Aggregating the complete contiguous raw set guarantees correct boundary bars
    regardless of how the underlying executions were fetched.

    Args:
        timeframe: Bar timeframe to (re)build.
        product: Product code (defaults to configured).

    Returns:
        The number of bars upserted.
    """
    prod = product or get_settings().product_code
    with get_session() as session:
        rows = session.execute(
            select(Execution.exec_date, Execution.price, Execution.size)
            .where(Execution.product == prod)
            .order_by(Execution.exec_date)
        ).all()

    ticks: list[tuple[datetime, float, float]] = [
        (r[0], float(r[1]), float(r[2])) for r in rows
    ]
    bars = aggregate_ticks(ticks, timeframe)
    logger.info(
        "Rebuilt {} {} bars from {} raw executions.", len(bars), timeframe.value, len(ticks)
    )
    if not bars:
        return 0

    bar_rows = [
        {
            "product": prod,
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
        stmt = pg_insert(OHLCV).values(bar_rows)
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
    logger.info("Upserted {} {} bars.", len(bar_rows), timeframe.value)
    return len(bar_rows)


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Resumable OHLCV history collection.")
    parser.add_argument(
        "--direction",
        choices=["back", "forward", "both"],
        default="both",
        help="Extend deeper into the past, catch up to now, or both.",
    )
    parser.add_argument("--max-ticks", type=int, default=10_000, help="Max execs per direction.")
    parser.add_argument(
        "--timeframe",
        choices=[tf.value for tf in Timeframe],
        default="1m",
        help="Timeframe to rebuild after extending.",
    )
    parser.add_argument(
        "--no-rebuild", action="store_true", help="Skip the OHLCV rebuild step."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear the product's raw executions, checkpoint and OHLCV first. "
        "Combine with --max-ticks 0 --no-rebuild for a pure reset.",
    )
    args = parser.parse_args()

    configure_logging(get_settings().log_level)

    if args.reset:
        reset_history()

    directions = ["forward", "back"] if args.direction == "both" else [args.direction]
    total = 0
    for d in directions:
        total += extend_history(d, args.max_ticks)

    if not args.no_rebuild and args.max_ticks > 0:
        rebuild_ohlcv(Timeframe(args.timeframe))
    logger.info("History run complete: {} new executions inserted.", total)


if __name__ == "__main__":
    main()
