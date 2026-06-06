"""Strategy: density_volwall_breakout.

Trades breakouts out of a **volume-only wall** — a high-volume price zone that the
time-at-price profile never flags as a value area (see
``src/signs/density_volwall_breakout.py`` for the entry hypothesis and
``src/backtest/analysis/volume_walls_probe.py`` for the negative result). This is
the user's *additive* volume idea made viewable on the Backtest tab; the exit
mechanics mirror :class:`src.strategy.density_breakout.DensityBreakoutStrategy`
exactly so the two are apples-to-apples:

- **Structural stop** beyond the **opposite** edge of the broken wall (a pullback
  back into the wall is tolerated).
- Optional **ATR trailing stop** (``None`` by default — a trail clips the trend
  winners a ride exists to capture).
- **Time stop** as a generous backstop.

A trend-ride has a *low* win rate with *large* winners by design — judge it by
portfolio Sharpe / payoff ratio, not detection rate.
"""

from __future__ import annotations

from src.core.types import Bar, ExitConfig, Side, Signal
from src.signs.density_volwall_breakout import DensityVolwallBreakoutSign
from src.strategy.base import Strategy


class DensityVolwallBreakoutStrategy(Strategy):
    """Volume-only-wall breakout with a far-edge structural stop + optional trail."""

    name = "density_volwall_breakout"
    description = (
        "Breakout out of a VOLUME-only wall (a high-volume zone the time profile "
        "misses): price consolidates inside, then closes through an edge -> ride "
        "the trend (hourly). Structural stop beyond the opposite edge + optional "
        "ATR trail. The user's additive-volume idea (probe verdict: no edge)."
    )

    def __init__(
        self,
        window: int = 168,
        n_bins: int = 48,
        prominence_k: float = 1.0,
        max_band_pct: float | None = 0.02,
        vol_clip: float | None = 8.0,
        sl_buffer: float = 0.10,
        trail_atr_mult: float | None = None,
        max_bars: int = 120,
    ) -> None:
        """Initialise the strategy.

        Args:
            window: Trailing bars for both profiles (168 = ~1 week 1h).
            n_bins: Histogram price bins (shared grid).
            prominence_k: Wall threshold in std above the mean (see the sign).
            max_band_pct: Tight-wall regime filter (see the sign). Default 0.02.
            vol_clip: Per-bar volume cap for the volume profile (see the sign).
            sl_buffer: Structural stop placed this fraction of the wall height
                *beyond* the opposite edge.
            trail_atr_mult: ATR trailing-stop multiple. ``None`` (default)
                disables the trail.
            max_bars: Time-stop backstop in bars (120 = ~5 days on 1h).

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
        self._sign = DensityVolwallBreakoutSign(
            window=window,
            n_bins=n_bins,
            prominence_k=prominence_k,
            max_band_pct=max_band_pct,
            vol_clip=vol_clip,
        )
        self._sl_buffer = sl_buffer
        self._trail_atr_mult = trail_atr_mult
        self._max_bars = max_bars
        self.required_indicators = self._sign.required_indicators
        # The sign needs window+1 bars for the profile plus the prior "inside" bar.
        self.window = window + 2
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
