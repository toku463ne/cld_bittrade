"""Technical indicators (EMA, ATR, RSI, Bollinger Bands).

All indicators operate on a price/OHLC DataFrame and return pandas Series/frames
aligned to the input index. Warmup periods are filled with ``0.0`` (not NaN) per
the project convention in CLAUDE.md; downstream code filters them with
``value or None``.
"""

from src.indicators.atr import atr, atr_average
from src.indicators.bollinger import bollinger_bands
from src.indicators.ema import ema
from src.indicators.rsi import rsi

__all__ = ["ema", "atr", "atr_average", "rsi", "bollinger_bands"]
