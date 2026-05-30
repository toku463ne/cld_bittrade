"""Exponential moving average."""

from __future__ import annotations

import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """Compute the exponential moving average.

    Args:
        series: Price series (typically close).
        period: EMA span (e.g. 9 or 21).

    Returns:
        EMA series aligned to ``series``. The first ``period - 1`` values are set
        to ``0.0`` (warmup convention).
    """
    if period <= 0:
        raise ValueError("period must be positive")
    out = series.ewm(span=period, adjust=False, min_periods=period).mean()
    return out.fillna(0.0)
