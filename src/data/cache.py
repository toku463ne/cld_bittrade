"""DataCache — loads OHLCV bars from the DB for indicators/backtests.

Per CLAUDE.md: warmup NaN values are stored as ``0.0`` in indicator arrays;
callers filter them with ``value or None``. The cache returns both the bar list
and a pandas DataFrame view for vectorised indicator computation.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from loguru import logger
from sqlalchemy import select

from src.config import get_settings
from src.core.types import Bar, Timeframe
from src.db import get_session
from src.models import OHLCV


class DataCache:
    """Loads and holds OHLCV bars for one (product, timeframe).

    Attributes:
        product: Product code.
        timeframe: Bar timeframe.
        bars: Loaded bars in ascending time order.
    """

    def __init__(self, product: str, timeframe: Timeframe) -> None:
        self.product = product
        self.timeframe = timeframe
        self.bars: list[Bar] = []

    def load(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        """Load bars from the DB into the cache.

        Args:
            start: Inclusive lower bound on bar timestamp.
            end: Inclusive upper bound on bar timestamp.

        Returns:
            The loaded bars (also stored on ``self.bars``).
        """
        stmt = (
            select(OHLCV)
            .where(OHLCV.product == self.product, OHLCV.timeframe == self.timeframe.value)
            .order_by(OHLCV.timestamp)
        )
        if start is not None:
            stmt = stmt.where(OHLCV.timestamp >= start)
        if end is not None:
            stmt = stmt.where(OHLCV.timestamp <= end)

        with get_session() as session:
            rows = session.execute(stmt).scalars().all()

        self.bars = [
            Bar(r.timestamp, r.open, r.high, r.low, r.close, r.volume) for r in rows
        ]
        logger.info(
            "DataCache loaded {} {} bars for {}",
            len(self.bars),
            self.timeframe.value,
            self.product,
        )
        return self.bars

    def to_frame(self) -> pd.DataFrame:
        """Return the cached bars as a time-indexed DataFrame.

        Returns:
            A DataFrame indexed by timestamp with OHLCV columns.
        """
        if not self.bars:
            return pd.DataFrame(
                columns=["open", "high", "low", "close", "volume"]
            ).rename_axis("timestamp")
        df = pd.DataFrame(
            {
                "timestamp": [b.timestamp for b in self.bars],
                "open": [b.open for b in self.bars],
                "high": [b.high for b in self.bars],
                "low": [b.low for b in self.bars],
                "close": [b.close for b in self.bars],
                "volume": [b.volume for b in self.bars],
            }
        ).set_index("timestamp")
        return df


def load_cache(
    timeframe: Timeframe,
    *,
    product: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> DataCache:
    """Convenience constructor that loads in one call.

    Args:
        timeframe: Bar timeframe.
        product: Product code (defaults to configured product).
        start: Inclusive lower timestamp bound.
        end: Inclusive upper timestamp bound.

    Returns:
        A loaded :class:`DataCache`.
    """
    cache = DataCache(product or get_settings().product_code, timeframe)
    cache.load(start=start, end=end)
    return cache
