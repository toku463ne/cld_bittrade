"""Rolling correlation of returns between two price series.

Correlates **returns** (not price levels) — two trending series look correlated
on levels even with unrelated moves, so return-correlation is the honest measure.
Ported/adapted from cld_trade_advisor ``src/indicators/moving_corr.py``.
"""

from __future__ import annotations

import pandas as pd


def moving_corr(
    base: pd.Series,
    other: pd.Series,
    window: int = 24,
) -> pd.Series:
    """Rolling Pearson correlation of the two series' returns.

    Args:
        base: Price series (e.g. BTC close), DatetimeIndex.
        other: Other price series aligned to the same index (e.g. SP500 close,
            forward-filled onto ``base``'s timestamps).
        window: Rolling window in bars.

    Returns:
        Correlation series in ``[-1, 1]`` aligned to ``base.index``; NaN for the
        warmup region and where either return is undefined.
    """
    min_periods = max(5, window // 2)
    aligned = pd.concat(
        [base.pct_change().rename("a"), other.pct_change().rename("b")], axis=1
    )
    return aligned["a"].rolling(window, min_periods=min_periods).corr(aligned["b"])
