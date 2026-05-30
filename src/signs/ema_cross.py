"""EMA crossover detector (diagnostic baseline sign)."""

from __future__ import annotations

import pandas as pd

from src.core.types import Side
from src.indicators import ema
from src.signs.base import FireEvent, Sign


class EmaCrossSign(Sign):
    """Fires LONG when EMA(fast) crosses above EMA(slow); SHORT on the reverse.

    The score reflects the magnitude of the separation at the cross, normalised
    by price, squashed into ``[0, 1]``.
    """

    name = "ema_cross"

    def __init__(self, fast: int = 9, slow: int = 21) -> None:
        if fast >= slow:
            raise ValueError("fast period must be < slow period")
        self.fast = fast
        self.slow = slow
        self.required_indicators = [f"ema_{fast}", f"ema_{slow}"]

    def detect(self, df: pd.DataFrame) -> list[FireEvent]:  # noqa: D102 (inherited)
        if df.empty:
            return []
        close = df["close"]
        fast = ema(close, self.fast)
        slow = ema(close, self.slow)
        warm = (fast > 0.0) & (slow > 0.0)
        diff = fast - slow
        prev_diff = diff.shift(1)

        cross_up = warm & (prev_diff <= 0.0) & (diff > 0.0)
        cross_dn = warm & (prev_diff >= 0.0) & (diff < 0.0)

        fires: list[FireEvent] = []
        for ts in df.index[cross_up | cross_dn]:
            up = bool(cross_up.loc[ts])
            sep = abs(float(diff.loc[ts])) / float(close.loc[ts])
            score = float(min(1.0, sep / 0.002))  # 0.2% separation -> score 1.0
            fires.append(
                FireEvent(
                    fired_at=ts.to_pydatetime(),
                    side=Side.LONG if up else Side.SHORT,
                    score=score,
                    price=float(close.loc[ts]),
                )
            )
        return fires
