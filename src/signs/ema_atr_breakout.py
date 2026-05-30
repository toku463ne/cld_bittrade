"""EMA cross + ATR volatility-filter detector.

This is the canonical sign behind the ``ema_atr_breakout`` strategy:

- Long:  EMA(fast) crosses above EMA(slow) AND ATR(atr_period) > N-bar ATR avg
- Short: EMA(fast) crosses below EMA(slow) AND ATR(atr_period) > N-bar ATR avg

The ATR filter requires the cross to occur in an elevated-volatility regime.
"""

from __future__ import annotations

import pandas as pd

from src.core.types import Side
from src.indicators import atr, atr_average, ema
from src.signs.base import FireEvent, Sign


class EmaAtrBreakoutSign(Sign):
    """EMA crossover gated by an ATR-above-average volatility filter."""

    name = "ema_atr_breakout"

    def __init__(
        self,
        fast: int = 9,
        slow: int = 21,
        atr_period: int = 14,
        atr_avg_period: int = 20,
    ) -> None:
        if fast >= slow:
            raise ValueError("fast period must be < slow period")
        self.fast = fast
        self.slow = slow
        self.atr_period = atr_period
        self.atr_avg_period = atr_avg_period
        self.required_indicators = [
            f"ema_{fast}",
            f"ema_{slow}",
            f"atr_{atr_period}",
            f"atr_avg_{atr_avg_period}",
        ]

    def detect(self, df: pd.DataFrame) -> list[FireEvent]:  # noqa: D102 (inherited)
        if df.empty:
            return []
        close = df["close"]
        fast = ema(close, self.fast)
        slow = ema(close, self.slow)
        atr_s = atr(df, self.atr_period)
        atr_avg = atr_average(atr_s, self.atr_avg_period)

        warm = (fast > 0.0) & (slow > 0.0) & (atr_avg > 0.0)
        diff = fast - slow
        prev_diff = diff.shift(1)
        vol_ok = atr_s > atr_avg

        cross_up = warm & vol_ok & (prev_diff <= 0.0) & (diff > 0.0)
        cross_dn = warm & vol_ok & (prev_diff >= 0.0) & (diff < 0.0)

        fires: list[FireEvent] = []
        for ts in df.index[cross_up | cross_dn]:
            up = bool(cross_up.loc[ts])
            # Score blends EMA separation and how far ATR exceeds its average.
            sep = abs(float(diff.loc[ts])) / float(close.loc[ts])
            vol_excess = (float(atr_s.loc[ts]) / float(atr_avg.loc[ts])) - 1.0
            score = float(min(1.0, 0.5 * (sep / 0.002) + 0.5 * min(1.0, vol_excess)))
            fires.append(
                FireEvent(
                    fired_at=ts.to_pydatetime(),
                    side=Side.LONG if up else Side.SHORT,
                    score=max(0.0, score),
                    price=float(close.loc[ts]),
                )
            )
        return fires
