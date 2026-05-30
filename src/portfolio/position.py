"""Position persistence helpers.

Thin ORM wrappers around the ``position`` and ``trade`` tables. Enforces the
minimum-lot constraint (0.001 BTC) and the single-strategy-live rule is left to
the operator (this layer records, it does not gate execution).
"""

from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy import select

from src.core.types import Side
from src.db import get_session
from src.models import Position

MIN_LOT = 0.001


def open_position(
    *,
    product: str,
    side: Side,
    entry_price: float,
    entry_time: datetime,
    size: float = MIN_LOT,
    strategy: str | None = None,
    note: str | None = None,
) -> int:
    """Record a newly opened live position.

    Args:
        product: Product code.
        side: Long or short.
        entry_price: Fill price.
        entry_time: Fill time.
        size: Position size in BTC. Must not exceed the minimum lot until the
            strategy has passed the benchmark pipeline.
        strategy: Originating strategy name.
        note: Free-text note.

    Returns:
        The new position's row id.

    Raises:
        ValueError: If ``size`` exceeds :data:`MIN_LOT`.
    """
    if size > MIN_LOT:
        raise ValueError(
            f"size {size} exceeds minimum lot {MIN_LOT}; lot increases are "
            "prohibited until the strategy passes the full benchmark pipeline."
        )
    with get_session() as session:
        pos = Position(
            product=product,
            strategy=strategy,
            side=side.value,
            size=size,
            entry_price=entry_price,
            entry_time=entry_time,
            status="open",
            note=note,
        )
        session.add(pos)
        session.flush()
        pos_id = pos.id
    logger.info("Registered open {} position #{} @ {}", side.value, pos_id, entry_price)
    return pos_id


def list_open_positions(product: str | None = None) -> list[Position]:
    """Return all open positions, optionally filtered by product.

    Args:
        product: Optional product filter.

    Returns:
        Open :class:`~src.models.Position` rows.
    """
    stmt = select(Position).where(Position.status == "open")
    if product is not None:
        stmt = stmt.where(Position.product == product)
    with get_session() as session:
        return list(session.execute(stmt).scalars().all())
