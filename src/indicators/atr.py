"""Average True Range and its rolling average (volatility filter input)."""

from __future__ import annotations

import pandas as pd


def _true_range(df: pd.DataFrame) -> pd.Series:
    """Compute the True Range from an OHLC frame."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute ATR using Wilder's smoothing.

    Args:
        df: OHLC DataFrame with ``high``, ``low``, ``close`` columns.
        period: ATR lookback (default 14).

    Returns:
        ATR series; warmup values filled with ``0.0``.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    tr = _true_range(df)
    out = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    return out.fillna(0.0)


def atr_average(atr_series: pd.Series, period: int = 20) -> pd.Series:
    """Rolling simple average of ATR (the volatility-filter reference line).

    Args:
        atr_series: An ATR series (from :func:`atr`).
        period: Averaging window (default 20).

    Returns:
        Rolling-mean series; warmup values filled with ``0.0``.
    """
    # Treat warmup 0.0 as missing so the average is not biased downward.
    masked = atr_series.where(atr_series > 0.0)
    out = masked.rolling(window=period, min_periods=period).mean()
    return out.fillna(0.0)
