"""Deterministic synthetic tick generator.

Produces a reproducible random-walk price path for ``FX_BTC_JPY`` so the mock
REST/WS layers can run without any recorded data. Seeded for determinism so
tests are repeatable.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True, slots=True)
class SyntheticTick:
    """One synthetic execution tick.

    Attributes:
        exec_date: Execution timestamp (UTC).
        price: Trade price in JPY.
        size: Trade size in BTC.
        side: ``"BUY"`` or ``"SELL"``.
        tick_id: Monotonic id.
    """

    exec_date: datetime
    price: float
    size: float
    side: str
    tick_id: int


def generate_ticks(
    *,
    start: datetime | None = None,
    count: int = 10_000,
    start_price: float = 5_000_000.0,
    seed: int = 42,
    step_seconds: float = 1.0,
    vol: float = 0.0006,
) -> Iterator[SyntheticTick]:
    """Yield a deterministic random-walk sequence of ticks.

    Args:
        start: First tick timestamp (defaults to a fixed 2026-01-01 UTC anchor).
        count: Number of ticks to produce.
        start_price: Initial BTC/JPY price.
        seed: RNG seed for reproducibility.
        step_seconds: Seconds between consecutive ticks.
        vol: Per-tick lognormal volatility.

    Yields:
        :class:`SyntheticTick` instances in time order.
    """
    rng = random.Random(seed)
    ts = start or datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    price = start_price
    for i in range(count):
        # Lognormal random-walk step keeps prices positive.
        price *= 1.0 + rng.gauss(0.0, vol)
        side = "BUY" if rng.random() > 0.5 else "SELL"
        size = round(rng.uniform(0.001, 0.5), 4)
        yield SyntheticTick(
            exec_date=ts,
            price=round(price, 1),
            size=size,
            side=side,
            tick_id=i + 1,
        )
        ts += timedelta(seconds=step_seconds)
