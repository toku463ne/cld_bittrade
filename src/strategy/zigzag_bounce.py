"""Strategy: zigzag_bounce.

Trades bounces off recent established swing levels on hourly bars (see
``src/signs/zigzag_bounce.py`` for the entry hypothesis). Exits use the
ZS-adaptive TP/SL rule (``src/exit/zs_tp_sl.py``): TP/SL are multiples of an
EWA of recent zigzag leg sizes, so the band scales with the market's own swing
size. The per-trade exit config is attached to each :class:`Signal`.
"""

from __future__ import annotations

from src.core.types import Bar, ExitConfig, Signal
from src.exit.base import ExitContext
from src.exit.zs_tp_sl import ZsTpSl
from src.signs.zigzag_bounce import ZigzagBounceSign
from src.strategy.base import Strategy


class ZigzagBounceStrategy(Strategy):
    """Early-peak-near-recent-peak bounce strategy with a ZS TP/SL exit."""

    name = "zigzag_bounce"
    description = (
        "Bounce off recent zigzag S/R: fire when a right-edge early peak forms "
        "near a recent confirmed peak (hourly). ZS-adaptive TP/SL exit."
    )

    def __init__(
        self,
        size: int = 10,
        mid_size: int = 3,
        windows: tuple[int, ...] = (60, 120, 180),
        tol_pct: float = 0.005,
        tol_leg_frac: float | None = None,
        reverse_levels: bool = False,
        require_break: bool = True,
        dominant_window: int | None = None,
        tp_mult: float = 1.0,
        sl_mult: float = 1.0,
        alpha: float = 0.3,
        min_legs: int = 3,
        fallback_pct: float = 0.01,
        max_bars: int = 48,
        winsorize_k: float | None = None,
    ) -> None:
        super().__init__()
        self._sign = ZigzagBounceSign(
            size=size, mid_size=mid_size, windows=windows, tol_pct=tol_pct,
            tol_leg_frac=tol_leg_frac,
            reverse_levels=reverse_levels, require_break=require_break,
            dominant_window=dominant_window,
        )
        self._exit_rule = ZsTpSl(
            tp_mult=tp_mult,
            sl_mult=sl_mult,
            alpha=alpha,
            min_legs=min_legs,
            fallback_pct=fallback_pct,
            max_bars=max_bars,
            winsorize_k=winsorize_k,
        )
        self.required_indicators = self._sign.required_indicators
        # Bounded buffer == the sign's trailing window so on_bar and the
        # benchmark's detect() see the same window and cannot drift.
        self.window = self._sign.window
        self.max_buffer = self._sign.window
        self.warmup = self._sign.window
        # Static fallback used only if a signal somehow lacks a per-trade config.
        self._fallback = ExitConfig(
            tp_pct=tp_mult * fallback_pct,
            sl_pct=sl_mult * fallback_pct,
            time_stop_bars=max_bars,
        )

    def on_bar(self, bar: Bar) -> Signal | None:  # noqa: D102 (inherited)
        fire = self._sign.last_fire(self.buffer_frame())
        if fire is None:
            return None
        cfg = self._exit_rule.exit_config(
            ExitContext(side=fire.side, entry_price=fire.price, zs_history=fire.legs)
        )
        return Signal(
            side=fire.side,
            timestamp=fire.fired_at,
            price=fire.price,
            score=fire.score,
            reason=self._sign.name,
            ref_time=fire.ref_time,
            ref_price=fire.ref_price,
            exit_config=cfg,
        )

    def get_exit_rules(self) -> ExitConfig:  # noqa: D102 (inherited)
        return self._fallback
