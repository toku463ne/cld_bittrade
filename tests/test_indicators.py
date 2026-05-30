"""Indicator unit tests (no DB / no API — pure functions)."""

from __future__ import annotations

import pandas as pd

from src.indicators import atr, atr_average, bollinger_bands, ema, rsi


def _ohlc(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.001 for c in closes],
            "low": [c * 0.999 for c in closes],
            "close": closes,
            "volume": [1.0] * len(closes),
        }
    )


def test_ema_warmup_is_zero_then_tracks() -> None:
    s = pd.Series([float(i) for i in range(1, 51)])
    out = ema(s, 9)
    # First (period-1) values are warmup -> 0.0 by convention.
    assert out.iloc[:8].eq(0.0).all()
    assert out.iloc[-1] > 0.0


def test_rsi_bounds() -> None:
    closes = [100 + (i % 5) for i in range(60)]
    out = rsi(_ohlc(closes)["close"], 14)
    nonwarm = out[out > 0.0]
    assert (nonwarm <= 100.0).all()
    assert (nonwarm >= 0.0).all()


def test_atr_positive_and_average_aligns() -> None:
    closes = [100 + i * 0.5 for i in range(80)]
    a = atr(_ohlc(closes), 14)
    avg = atr_average(a, 20)
    assert (a[a > 0.0] > 0.0).all()
    assert len(avg) == len(a)


def test_bollinger_band_order() -> None:
    closes = [100 + (i % 7) for i in range(60)]
    bb = bollinger_bands(_ohlc(closes)["close"], 20)
    warm = bb[bb["bb_mid"] > 0.0]
    assert (warm["bb_upper"] >= warm["bb_mid"]).all()
    assert (warm["bb_mid"] >= warm["bb_lower"]).all()
