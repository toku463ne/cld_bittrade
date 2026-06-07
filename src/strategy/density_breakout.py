"""Strategy: density_breakout.

Trades breakouts *out of* the dense band (time-at-price value area) on hourly
bars — see ``src/signs/density_breakout.py`` for the entry hypothesis. The trade
is meant to **ride the trend for many hours to days**, so the exit is built to
tolerate a pullback back to the band after entry:

- **Structural stop** beyond the **opposite** band edge (per the user's rule:
  "a bounce back to the dense band is expected; the stop must be the other side
  of the band"). A pullback into the band does *not* stop the trade out.
- **ATR trailing stop** to ride and then protect the trend. Because the
  simulator's effective stop is the *closer* of the structural stop and the
  trailing level, the structural (far-edge) stop dominates early; the trail only
  binds once price has run far enough above the band that ``peak - trail`` rises
  above the opposite edge. The default trail multiple is deliberately loose
  (~one band height in ATR terms) so normal pullbacks to the band don't trip it.
- **Time stop** as a generous backstop (default ~5 days).

The exit is the explicit next tuning target (the user asked to adjust it later);
the entry trigger is the hypothesis under test. Note: a trend-ride has a *low*
win rate with *large* winners by design, so judge it by portfolio Sharpe / payoff
ratio, **not** by detection rate.
"""

from __future__ import annotations

from src.core.types import Bar, ExitConfig, Side, Signal
from src.signs.density_breakout import DensityBreakoutSign
from src.strategy.base import Strategy


class DensityBreakoutStrategy(Strategy):
    """Dense-band breakout strategy with a far-edge structural stop + ATR trail."""

    name = "density_breakout"
    description = (
        "Breakout out of the dense band (time-at-price value area): price "
        "consolidates inside, then closes through an edge -> ride the trend "
        "(hourly). Structural stop beyond the opposite edge + ATR trailing stop."
    )

    def __init__(
        self,
        window: int = 168,
        n_bins: int = 48,
        coverage: float = 0.70,
        max_band_pct: float | None = 0.02,
        confirm_bars: int = 1,
        min_break_frac: float = 0.0,
        sl_buffer: float = 0.10,
        trail_atr_mult: float | None = None,
        max_bars: int = 120,
    ) -> None:
        """Initialise the strategy.

        Args:
            window: Trailing bars for the time-at-price profile (168 = ~1 week 1h).
            n_bins: Histogram price bins.
            coverage: Value-area fraction (0.70 = standard market profile).
            max_band_pct: Tight-box regime filter (see the sign). Default 0.02
                (2%) — only trade breakouts out of a *tight* consolidation box;
                tuned on 5y GMO 1h (tightest threshold still robust OOS).
            confirm_bars: Consecutive closes beyond the edge required to fire
                (see the sign). Default 1.
            min_break_frac: Minimum breakout extent past the edge as a fraction of
                band height (see the sign). Default 0.0.
            sl_buffer: Structural stop placed this fraction of the band height
                *beyond* the opposite edge.
            trail_atr_mult: ATR trailing-stop multiple. ``None`` (default)
                disables the trail — exit is the far-edge structural stop or the
                time stop only. Tuning on 5y GMO 1h found any trail *hurts* (it
                clips the trend winners a ride exists to capture); removing it
                lifted both IS and OOS Sharpe. Set a (loose) multiple to re-enable.
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
        self._sign = DensityBreakoutSign(
            window=window,
            n_bins=n_bins,
            coverage=coverage,
            max_band_pct=max_band_pct,
            confirm_bars=confirm_bars,
            min_break_frac=min_break_frac,
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
