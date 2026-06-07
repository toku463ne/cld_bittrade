"""Strategy: density_breakout_vol (A/B sibling of density_breakout).

Identical to :class:`src.strategy.density_breakout.DensityBreakoutStrategy` in
entry/exit mechanics, but the dense band is built from a **volume-at-price
acceptance profile** (candle body = acceptance, wicks = rejection) instead of the
time-at-price profile. See :mod:`src.signs.density_breakout_vol`.

Purpose: A/B the two density definitions under an identical exit (far-edge
structural stop + optional ATR trail + time stop), so any backtest difference is
attributable to the profile alone. Pre-register the ship gate and run the full
OOS rebenchmark before believing any improvement — volume-weighting is intuitive
but, on this project's deep data, intuition has a poor hit rate.
"""

from __future__ import annotations

from src.core.types import Bar, ExitConfig, Side, Signal
from src.indicators.density import VolTransform
from src.signs.density_breakout_vol import DensityBreakoutVolSign
from src.strategy.base import Strategy


class DensityBreakoutVolStrategy(Strategy):
    """Volume-acceptance dense-band breakout (A/B sibling of density_breakout)."""

    name = "density_breakout_vol"
    description = (
        "Breakout out of the dense band built from a VOLUME-at-price acceptance "
        "profile (body=acceptance, wicks=rejection): price consolidates inside, "
        "then closes through an edge -> ride the trend (hourly). Structural stop "
        "beyond the opposite edge + optional ATR trail. A/B sibling of "
        "density_breakout (which uses a time-at-price profile)."
    )

    def __init__(
        self,
        window: int = 168,
        n_bins: int = 48,
        coverage: float = 0.70,
        max_band_pct: float | None = 0.02,
        confirm_bars: int = 1,
        min_break_frac: float = 0.0,
        body_ratio: float = 0.7,
        vol_clip: float | None = 8.0,
        vol_transform: VolTransform = "linear",
        sl_buffer: float = 0.10,
        trail_atr_mult: float | None = None,
        max_bars: int = 120,
    ) -> None:
        """Initialise the strategy.

        Args mirror :class:`DensityBreakoutStrategy` (window, n_bins, coverage,
        max_band_pct, confirm_bars, min_break_frac, sl_buffer, trail_atr_mult,
        max_bars). The profile-specific knobs:

        Args:
            body_ratio: Body-vs-wick weight in the volume profile, in ``[0, 1]``
                (``0.5`` = plain volume profile; ``> 0.5`` = acceptance tilt).
            vol_clip: Cap on a bar's normalised volume so one outsized print
                cannot dominate the band. ``None`` disables it. Default 8.0.
            vol_transform: Concave volume compression (``linear``/``sqrt``/``log``).
                Default ``"linear"`` (raw volume + ``vol_clip``) — best OOS of the
                three in the smoke A/B; ``sqrt``/``log`` cut drawdown but did not
                improve OOS. A knob for the rebenchmark to settle.

        Raises:
            ValueError: On negative ``sl_buffer`` or non-positive ``max_bars`` /
                ``trail_atr_mult`` (sign-level params validated by the sign).
        """
        super().__init__()
        if sl_buffer < 0.0:
            raise ValueError("sl_buffer must be >= 0")
        if max_bars <= 0:
            raise ValueError("max_bars must be > 0")
        if trail_atr_mult is not None and trail_atr_mult <= 0.0:
            raise ValueError("trail_atr_mult must be > 0 when set")
        self._sign = DensityBreakoutVolSign(
            window=window,
            n_bins=n_bins,
            coverage=coverage,
            max_band_pct=max_band_pct,
            confirm_bars=confirm_bars,
            min_break_frac=min_break_frac,
            body_ratio=body_ratio,
            vol_clip=vol_clip,
            vol_transform=vol_transform,
        )
        self._sl_buffer = sl_buffer
        self._trail_atr_mult = trail_atr_mult
        self._max_bars = max_bars
        self.required_indicators = self._sign.required_indicators
        # Bound the buffer to the sign's window plus the confirmation run and the
        # prior "inside" bar so on_bar and the benchmark's detect() agree.
        self.window = window + confirm_bars + 1
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
            # Distance from entry (signal close, just past the broken edge) out
            # beyond the opposite edge — a wide stop that tolerates a pullback
            # all the way back through the band.
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
