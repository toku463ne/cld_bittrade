"""Relative Strength Index."""

from __future__ import annotations

import pandas as pd


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Compute RSI using Wilder's smoothing.

    Args:
        series: Price series (typically close).
        period: RSI lookback (default 14).

    Returns:
        RSI series in ``[0, 100]``; warmup values filled with ``0.0``.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, pd.NA)
    out = 100.0 - (100.0 / (1.0 + rs))
    # When avg_loss is 0 (all gains), RSI is 100.
    out = out.where(avg_loss != 0.0, 100.0)
    return out.fillna(0.0)
