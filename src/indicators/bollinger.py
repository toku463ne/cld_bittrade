"""Bollinger Bands."""

from __future__ import annotations

import pandas as pd


def bollinger_bands(
    series: pd.Series, period: int = 20, num_std: float = 2.0
) -> pd.DataFrame:
    """Compute Bollinger Bands (middle / upper / lower).

    Args:
        series: Price series (typically close).
        period: Moving-average window (default 20).
        num_std: Band width in standard deviations (default 2.0).

    Returns:
        DataFrame with ``bb_mid``, ``bb_upper``, ``bb_lower`` columns aligned to
        ``series``; warmup values filled with ``0.0``.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    mid = series.rolling(window=period, min_periods=period).mean()
    std = series.rolling(window=period, min_periods=period).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    return pd.DataFrame(
        {
            "bb_mid": mid.fillna(0.0),
            "bb_upper": upper.fillna(0.0),
            "bb_lower": lower.fillna(0.0),
        }
    )
