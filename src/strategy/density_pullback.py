"""Strategy: density_pullback — directional pullback entry on a dense breakout.

The momentum counterpart to ``random_hedge_density`` (which faded the box and was
rejected). Same question — does a *better-priced* entry lift the random_hedge exit
framework? — but the opposite sign: instead of fading, ride *with* a real
directional signal and just wait for a better fill.

Entry: the ``density_multi_breakout`` signal (price consolidates in the tight
~1-week value-area box, then closes through an edge → LONG on a top break, SHORT on
a bottom break). Rather than enter at the breakout close, rest a **limit at the
broken edge** (a genuine concession — for a LONG the edge is below the breakout
close, for a SHORT above) and fill only if price **pulls back** to it within
``limit_window`` bars, else cancel. So it buys the retest of broken resistance /
sells the retest of broken support — a momentum-with-pullback entry.

The exit is the random_hedge framework, unchanged (zs-band SL + next-dense TP +
periodic ratchet), so the only variable vs the random baseline is the entry — the
lift is the "is a better-priced directional entry worth anything?" measurement.
``pullback=False`` enters at the breakout close (market) instead, as the control
that isolates the price-improvement from the directional signal itself.
"""

from __future__ import annotations

from datetime import datetime

from src.core.types import Bar, ExitConfig, Side, Signal
from src.exit.base import ExitContext
from src.strategy.density_multi_breakout import _next_dense, _rolling_bands
from src.strategy.random_hedge import RandomHedgeStrategy


class DensityPullbackStrategy(RandomHedgeStrategy):
    """Dense-breakout direction, entered on a limit pullback to the broken edge."""

    name = "density_pullback"
    description = (
        "Directional pullback: on a dense-box breakout, rest a limit at the broken "
        "edge and fill on the retest (buy broken resistance / sell broken support); "
        "same zs SL + next-dense TP + ratchet exit. Lift over random_hedge."
    )

    def __init__(
        self,
        *,
        window: int = 168,
        density_bins: int = 48,
        coverage: float = 0.70,
        max_band_pct: float = 0.03,
        limit_window: int = 24,
        pullback: bool = True,
        **kwargs: object,
    ) -> None:
        """Initialise.

        Args:
            window: Trailing bars for the value-area box (168 = ~1 week on 1h).
            density_bins: Histogram bins for the box profile.
            coverage: Value-area coverage fraction (0.70 standard).
            max_band_pct: Tight-box filter — fire only when box height <= this
                fraction of price.
            limit_window: Bars the pullback limit rests before cancellation.
            pullback: If True, enter via a limit at the broken edge (retest); if
                False, enter at the breakout close (market) — the control.
            **kwargs: Forwarded to :class:`RandomHedgeStrategy` (exit params, the
                bad-entry gates, ...). ``entry_prob`` is unused (entries are the
                breakouts, not random).

        Raises:
            ValueError: On out-of-range parameters.
        """
        kwargs.setdefault("recalc_bars", 48)  # walk-forward sweet-spot exit (see §3/§4)
        kwargs.setdefault("sl_mult", 0.75)  # one-knob WF: tightest robust stop (6/6 folds)
        super().__init__(**kwargs)  # type: ignore[arg-type]
        if window < 2:
            raise ValueError("window must be >= 2")
        if max_band_pct <= 0.0:
            raise ValueError("max_band_pct must be > 0")
        if limit_window < 1:
            raise ValueError("limit_window must be >= 1")
        self.window = window
        self.density_bins = density_bins
        self.coverage = coverage
        self.max_band_pct = max_band_pct
        self.limit_window = limit_window
        self.pullback = pullback
        self.warmup = max(self.warmup, window + 2)
        self.max_buffer = self.warmup + 2

    def precompute_multi(self, bars: list[Bar]) -> dict[datetime, list[Signal]] | None:  # noqa: D102
        if not bars:
            return {}
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        closes = [b.close for b in bars]
        from src.indicators.zigzag import detect_peaks

        peaks = detect_peaks(highs, lows, size=self.zigzag_size)
        peak_idx = [p.bar_index for p in peaks]
        peak_price = [p.price for p in peaks]
        atr_s = self._atr_series(highs, lows, closes) if self.max_atr_rank is not None else None
        chop_s = (
            self._chop_series(highs, lows, closes, self.chop_window)
            if self.max_chop_rank is not None
            else None
        )
        band_lo, band_hi = _rolling_bands(highs, lows, self.window, self.density_bins, self.coverage)

        out: dict[datetime, list[Signal]] = {}
        for t in range(self.warmup, len(bars)):
            lo, hi = float(band_lo[t]), float(band_hi[t])
            if not (hi > lo):
                continue
            prev = closes[t - 1]
            if not (lo <= prev <= hi):
                continue
            c = closes[t]
            if (hi - lo) > self.max_band_pct * c:
                continue
            if c > hi:
                side, near = Side.LONG, hi
            elif c < lo:
                side, near = Side.SHORT, lo
            else:
                continue
            if not self._gate_ok(t, atr_s, chop_s):
                continue

            entry_ref = near if self.pullback else c  # the price the trade is built around
            legs = self._legs(peak_idx, peak_price, t)
            ctx = ExitContext(side=side, entry_price=entry_ref, zs_history=legs)
            band = self._zs.band(ctx)
            sl_abs = self._zs.exit_config(ctx).sl_abs
            target = _next_dense(
                highs, lows, t, entry_ref, side,
                target_window=self.target_window, n_bins=self.n_bins,
                min_frac=self.target_min_frac, min_dist=self.target_min_dist_frac * band,
            )
            cfg = ExitConfig(
                sl_abs=sl_abs,
                tp_abs=abs(target - entry_ref) if target is not None else None,
                time_stop_bars=self.time_stop_bars,
            )
            ts = bars[t].timestamp
            out[ts] = [
                Signal(
                    side=side,
                    timestamp=ts,
                    price=entry_ref,
                    score=1.0,
                    reason=self.name,
                    ref_time=ts,
                    ref_price=target,
                    exit_config=cfg,
                    limit_price=near if self.pullback else None,
                    limit_expiry_bars=self.limit_window if self.pullback else 0,
                )
            ]
        return out
