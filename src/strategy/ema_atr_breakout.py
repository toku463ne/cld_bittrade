"""Reference strategy: EMA(9/21) cross + ATR(14) volatility filter.

Entry (delegated to :class:`~src.signs.ema_atr_breakout.EmaAtrBreakoutSign`):

- Long:  EMA(9) crosses above EMA(21) AND ATR(14) > 20-bar ATR average
- Short: EMA(9) crosses below EMA(21) AND ATR(14) > 20-bar ATR average

Exits (per CLAUDE.md):

- TP: entry ± ATR × 1.5
- SL: entry ± ATR × 0.8
- Time stop: 5 minutes (timeframe-dependent; expressed in bars at sim time)

The strategy delegates entry detection to the canonical sign so the per-fire
benchmark and the live entries cannot drift apart (failure-mode §5.3).
"""

from __future__ import annotations

from src.core.types import Bar, ExitConfig, Signal
from src.signs.ema_atr_breakout import EmaAtrBreakoutSign
from src.strategy.base import Strategy


class EmaAtrBreakoutStrategy(Strategy):
    """EMA cross + ATR-filter scalping strategy."""

    name = "ema_atr_breakout"
    description = "EMA(9/21) cross gated by an ATR(14) > 20-bar-avg volatility filter."
    required_indicators = ["ema_9", "ema_21", "atr_14", "atr_avg_20"]
    warmup = 40

    def __init__(
        self,
        fast: int = 9,
        slow: int = 21,
        atr_period: int = 14,
        atr_avg_period: int = 20,
        tp_atr_mult: float = 1.5,
        sl_atr_mult: float = 0.8,
        time_stop_bars: int = 5,
    ) -> None:
        super().__init__()
        self._sign = EmaAtrBreakoutSign(
            fast=fast, slow=slow, atr_period=atr_period, atr_avg_period=atr_avg_period
        )
        self._tp_atr_mult = tp_atr_mult
        self._sl_atr_mult = sl_atr_mult
        self._time_stop_bars = time_stop_bars

    def on_bar(self, bar: Bar) -> Signal | None:  # noqa: D102 (inherited)
        df = self.buffer_frame()
        fire = self._sign.last_fire(df)
        if fire is None:
            return None
        return Signal(
            side=fire.side,
            timestamp=fire.fired_at,
            price=fire.price,
            score=fire.score,
            reason=self._sign.name,
        )

    def get_exit_rules(self) -> ExitConfig:  # noqa: D102 (inherited)
        return ExitConfig(
            tp_atr_mult=self._tp_atr_mult,
            sl_atr_mult=self._sl_atr_mult,
            time_stop_bars=self._time_stop_bars,
        )
