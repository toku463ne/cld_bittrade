"""Signal-detector base class.

A :class:`Sign` consumes an OHLCV DataFrame and emits :class:`FireEvent`
records. Outcomes (DR, signed return, etc.) are measured separately by the
benchmark pipeline (``src/backtest/``) using the zigzag definition in
``docs/evaluation_guide.md``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from src.core.types import Side


@dataclass(frozen=True, slots=True)
class FireEvent:
    """A single detector fire on bar T.

    Attributes:
        fired_at: Timestamp of the signal bar (bar T).
        side: Direction the detector predicts.
        score: Confidence in ``[0, 1]``.
        price: Close of the signal bar (reference price).
    """

    fired_at: datetime
    side: Side
    score: float
    price: float


class Sign(ABC):
    """Abstract directional detector.

    Subclasses set :attr:`name` and implement :meth:`detect`. The benchmark
    pipeline calls :meth:`detect` over a full bar series; strategies call it over
    a rolling buffer.
    """

    name: str = "base"
    required_indicators: list[str] = []

    @abstractmethod
    def detect(self, df: pd.DataFrame) -> list[FireEvent]:
        """Detect fires over an OHLCV frame.

        Args:
            df: Time-indexed OHLCV DataFrame (columns: open/high/low/close/volume).

        Returns:
            Fire events in ascending time order. Implementations MUST NOT use any
            data after a fire's bar to decide that fire (no look-ahead).
        """
        raise NotImplementedError

    def last_fire(self, df: pd.DataFrame) -> FireEvent | None:
        """Return the fire on the final bar of ``df``, if any.

        Convenience for incremental (per-bar) use by strategies.

        Args:
            df: OHLCV frame whose last row is the current bar.

        Returns:
            The :class:`FireEvent` whose ``fired_at`` equals the last index, else
            ``None``.
        """
        if df.empty:
            return None
        fires = self.detect(df)
        if not fires:
            return None
        last_ts = df.index[-1]
        tail = fires[-1]
        return tail if tail.fired_at == last_ts else None
