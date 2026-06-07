"""Strategy: density_breakout_clearair.

Identical to :class:`src.strategy.density_breakout.DensityBreakoutStrategy` in
entry trigger and exit (far-edge structural stop + optional ATR trail + time
stop), with one added entry gate: cancel a breakout that has **no clear air** in
its direction — a recent zigzag swing within ``clear_air_pct`` of entry (overhead
high for a LONG, underfoot low for a SHORT). See
``src/signs/density_breakout_clearair.py`` for the hypothesis and the
``entry_filter_probe`` result that motivated it (near-swing breakouts stall;
clear-air breakouts run). ``clear_air_pct == 0.0`` reduces to ``density_breakout``.

Judge by portfolio Sharpe NET of the frequency it costs (the filter cancels the
bulk of fires): the question is whether the per-trade quality lift survives the
trade-count loss.
"""

from __future__ import annotations

from src.core.types import Bar, ExitConfig, Side, Signal
from src.signs.density_breakout_clearair import DensityBreakoutClearairSign
from src.strategy.base import Strategy


class DensityBreakoutClearairStrategy(Strategy):
    """Dense-band breakout that only takes breakouts into clear air."""

    name = "density_breakout_clearair"
    description = (
        "density_breakout, minus breakouts with a recent swing too close in the "
        "trade direction (no room to run). Far-edge structural stop + optional "
        "ATR trail. Loss-avoidance filter; judge net of the frequency it costs."
    )

    def __init__(
        self,
        window: int = 168,
        n_bins: int = 48,
        coverage: float = 0.70,
        max_band_pct: float | None = 0.02,
        confirm_bars: int = 1,
        min_break_frac: float = 0.0,
        zigzag_size: int = 12,
        clear_air_pct: float = 0.005,
        swing_lookback: int = 168,
        sl_buffer: float = 0.10,
        trail_atr_mult: float | None = None,
        max_bars: int = 120,
    ) -> None:
        """Initialise the strategy.

        Args mirror :class:`DensityBreakoutStrategy` plus the clear-air knobs
        (``zigzag_size``, ``clear_air_pct``, ``swing_lookback``) documented on
        :class:`DensityBreakoutClearairSign`.

        Raises:
            ValueError: On negative ``sl_buffer`` or non-positive ``max_bars`` /
                ``trail_atr_mult``.
        """
        super().__init__()
        if sl_buffer < 0.0:
            raise ValueError("sl_buffer must be >= 0")
        if max_bars <= 0:
            raise ValueError("max_bars must be > 0")
        if trail_atr_mult is not None and trail_atr_mult <= 0.0:
            raise ValueError("trail_atr_mult must be > 0 when set")
        self._sign = DensityBreakoutClearairSign(
            window=window,
            n_bins=n_bins,
            coverage=coverage,
            max_band_pct=max_band_pct,
            confirm_bars=confirm_bars,
            min_break_frac=min_break_frac,
            zigzag_size=zigzag_size,
            clear_air_pct=clear_air_pct,
            swing_lookback=swing_lookback,
        )
        self._sl_buffer = sl_buffer
        self._trail_atr_mult = trail_atr_mult
        self._max_bars = max_bars
        self.required_indicators = self._sign.required_indicators
        # Buffer must hold the band window, the confirmation run, the prior
        # "inside" bar, AND enough history that every swing in the lookback is
        # confirmable (lookback + zigzag_size bars), so on_bar and detect() agree.
        self.window = max(window, swing_lookback) + zigzag_size + confirm_bars + 1
        self.max_buffer = self.window
        self.warmup = self.window
        self._fallback = ExitConfig(sl_pct=0.03, time_stop_bars=max_bars)

    def on_bar(self, bar: Bar) -> Signal | None:  # noqa: D102 (inherited)
        fire = self._sign.last_fire(self.buffer_frame())
        if fire is None:
            return None
        near = fire.ref_price  # broken edge
        far = fire.ref2_price  # opposite edge = structural stop level
        if near is None or far is None:
            cfg = self._fallback
        else:
            band_h = abs(near - far)
            if fire.side is Side.LONG:
                sl_abs = (fire.price - far) + self._sl_buffer * band_h
            else:
                sl_abs = (far - fire.price) + self._sl_buffer * band_h
            sl_abs = max(sl_abs, self._sl_buffer * band_h)
            cfg = ExitConfig(
                sl_abs=sl_abs,
                trail_atr_mult=self._trail_atr_mult,
                time_stop_bars=self._max_bars,
            )
        return Signal(
            side=fire.side,
            timestamp=fire.fired_at,
            price=fire.price,
            score=fire.score,
            reason=self._sign.name,
            ref_time=fire.ref_time,
            ref_price=fire.ref_price,
            ref2_time=fire.ref2_time,
            ref2_price=fire.ref2_price,
            exit_config=cfg,
        )

    def get_exit_rules(self) -> ExitConfig:  # noqa: D102 (inherited)
        return self._fallback
