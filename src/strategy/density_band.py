"""Strategy: density_band.

Trades rebounds off the dense band (market-profile value area) on hourly bars —
see ``src/signs/density_band.py`` for the entry hypothesis. The exit is band-
relative and attached per-trade to each :class:`Signal`:

- the **far edge** of the band is the invalidation level: if price closes through
  the band (the rebound failed), the stop sits just beyond the far edge;
- the take-profit is a multiple of the band height back toward where price came
  from.

Because entry distances are price-relative, they are sized from the signal-bar
close even though the simulator fills at the next bar's open (two-bar rule).
"""

from __future__ import annotations

from src.core.types import Bar, ExitConfig, Side, Signal
from src.signs.density_band import DensityBandSign
from src.strategy.base import Strategy


class DensityBandStrategy(Strategy):
    """Dense-band rebound strategy with a band-relative TP/SL exit."""

    name = "density_band"
    description = (
        "Rebound off the dense band (time-at-price value area): price returns "
        "from outside to touch the near edge -> trade the bounce (hourly). "
        "Band-relative TP/SL exit."
    )

    def __init__(
        self,
        window: int = 168,
        n_bins: int = 48,
        coverage: float = 0.70,
        tol_pct: float = 0.002,
        pierce_frac: float = 1.0,
        tp_mult: float = 1.0,
        sl_buffer: float = 0.25,
        max_bars: int = 48,
    ) -> None:
        """Initialise the strategy.

        Args:
            window: Trailing bars for the time-at-price profile (168 = ~1 week 1h).
            n_bins: Histogram price bins.
            coverage: Value-area fraction (0.70 = standard market profile).
            tol_pct: Edge-touch tolerance (fraction of edge price).
            pierce_frac: Max band-height pierce past the near edge to still count
                as a bounce.
            tp_mult: Take-profit distance as a multiple of the band height.
            sl_buffer: Stop placed this fraction of the band height *beyond* the
                far edge (the rebound is invalidated if price escapes the band).
            max_bars: Time stop in bars.

        Raises:
            ValueError: On non-positive ``tp_mult``/``max_bars`` or negative
                ``sl_buffer``.
        """
        super().__init__()
        if tp_mult <= 0.0:
            raise ValueError("tp_mult must be > 0")
        if sl_buffer < 0.0:
            raise ValueError("sl_buffer must be >= 0")
        if max_bars <= 0:
            raise ValueError("max_bars must be > 0")
        self._sign = DensityBandSign(
            window=window,
            n_bins=n_bins,
            coverage=coverage,
            tol_pct=tol_pct,
            pierce_frac=pierce_frac,
        )
        self._tp_mult = tp_mult
        self._sl_buffer = sl_buffer
        self._max_bars = max_bars
        self.required_indicators = self._sign.required_indicators
        # Bound the buffer to the sign's window so on_bar and the benchmark's
        # detect() see the same lookback and cannot drift. +2 covers the
        # current bar and the prior-close "stage" bar.
        self.window = window + 2
        self.max_buffer = self.window
        self.warmup = self.window
        # Static fallback if a signal somehow lacks a per-trade config.
        self._fallback = ExitConfig(
            tp_pct=0.01, sl_pct=0.01, time_stop_bars=max_bars
        )

    def on_bar(self, bar: Bar) -> Signal | None:  # noqa: D102 (inherited)
        fire = self._sign.last_fire(self.buffer_frame())
        if fire is None:
            return None
        # ref_price = near edge (touched), ref2_price = far edge.
        near = fire.ref_price
        far = fire.ref2_price
        if near is None or far is None:
            cfg = self._fallback
        else:
            band_h = abs(near - far)
            tp_abs = self._tp_mult * band_h
            # Distance from the entry (signal close) out past the far edge.
            if fire.side is Side.LONG:
                sl_abs = (fire.price - far) + self._sl_buffer * band_h
            else:
                sl_abs = (far - fire.price) + self._sl_buffer * band_h
            sl_abs = max(sl_abs, self._sl_buffer * band_h)
            cfg = ExitConfig(
                tp_abs=tp_abs, sl_abs=sl_abs, time_stop_bars=self._max_bars
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
