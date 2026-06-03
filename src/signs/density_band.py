"""Density-band bounce detector.

Hypothesis: over a trailing window (~1 week on 1h bars) price spends most of its
time inside a *dense band* — the market-profile value area built from a
time-at-price histogram (see :mod:`src.indicators.density`). Being **above** vs
**below** that band are different "stages"; crossing the band takes energy, so
when price returns to the band from the outside it tends to **rebound off the
near edge** rather than punch straight through:

- price was ABOVE the band, then descends to TOUCH the top edge -> LONG  (rebound)
- price was BELOW the band, then rises  to TOUCH the bottom edge -> SHORT (reject)

The band is recomputed every bar from the trailing window, so it drifts as the
distribution of recent prices changes.

Causality: every decision at bar ``t`` uses only bars ``<= t``. The profile is
built over ``[t-window, t-1]`` (the current bar is excluded so the touching bar
cannot move the band it touches); the "stage" comes from the prior close; the
touch is read off bar ``t``'s own low/high. No look-ahead.

Entry-mechanic note: the intended live entry is a touch/stop order at a level a
little inside the band, not a market fill at the bar close. This detector fires
at the touch bar's close (the framework's reference price) so the *directional*
edge can be measured first; honoring the level entry needs simulator support and
is tracked as a follow-up in ``docs/strategy/density_band.md``.
"""

from __future__ import annotations

import pandas as pd

from src.core.types import Side
from src.indicators.density import time_at_price_profile, value_area
from src.signs.base import FireEvent, Sign


class DensityBandSign(Sign):
    """Fires when price returns from outside to touch the dense-band edge."""

    name = "density_band"

    def __init__(
        self,
        window: int = 168,
        n_bins: int = 48,
        coverage: float = 0.70,
        tol_pct: float = 0.002,
        pierce_frac: float = 1.0,
    ) -> None:
        """Initialise the detector.

        Args:
            window: Trailing bars used to build the time-at-price profile
                (168 = ~1 week on 1h bars).
            n_bins: Number of price bins in the histogram.
            coverage: Value-area fraction (0.70 = standard market profile).
            tol_pct: "Near" tolerance for the edge touch, as a fraction of the
                edge price. The bar must reach within ``tol_pct`` of the edge.
            pierce_frac: Reject the fire if the bar pierces deeper than this
                fraction of the band height past the near edge (1.0 = only reject
                a full pass-through of the far edge). Guards against treating a
                clean break of the band as a bounce.

        Raises:
            ValueError: On non-positive ``window``/``n_bins`` or out-of-range
                ``coverage``/``pierce_frac``.
        """
        if window < 2:
            raise ValueError("window must be >= 2")
        if n_bins < 1:
            raise ValueError("n_bins must be >= 1")
        if not 0.0 < coverage <= 1.0:
            raise ValueError("coverage must be in (0, 1]")
        if not 0.0 < pierce_frac <= 1.0:
            raise ValueError("pierce_frac must be in (0, 1]")
        self.window = window
        self.n_bins = n_bins
        self.coverage = coverage
        self.tol_pct = tol_pct
        self.pierce_frac = pierce_frac
        self.required_indicators = [f"density_{window}_{n_bins}"]

    def _eval_end(
        self,
        highs: list[float],
        lows: list[float],
        closes: list[float],
    ) -> tuple[Side, float, float, float, float] | None:
        """Evaluate whether the LAST bar touches the dense band from outside.

        The profile is built over all but the last bar; the last bar is the
        candidate touch. Returns ``(side, score, poc, band_lo, band_hi)`` or
        ``None``.
        """
        n = len(highs)
        if n < self.window + 1:
            return None

        prof_hi = highs[-(self.window + 1) : -1]
        prof_lo = lows[-(self.window + 1) : -1]
        centers, weights = time_at_price_profile(prof_hi, prof_lo, self.n_bins)
        poc, band_lo, band_hi = value_area(centers, weights, self.coverage)
        if band_hi <= band_lo:
            return None

        prev_close = closes[-2]
        bar_hi = highs[-1]
        bar_lo = lows[-1]
        band_h = band_hi - band_lo

        # Above-stage rebound: prior close above the band, this bar's low dips to
        # the top edge (within tol) without piercing too far through.
        if prev_close > band_hi:
            tol = self.tol_pct * band_hi
            floor = band_hi - self.pierce_frac * band_h
            if band_hi - tol <= bar_lo <= band_hi + tol and bar_lo >= floor:
                gap = abs(bar_lo - band_hi)
                score = max(0.0, min(1.0, 1.0 - gap / tol)) if tol > 0 else 1.0
                return Side.LONG, score, poc, band_lo, band_hi

        # Below-stage rejection: prior close below the band, this bar's high rises
        # to the bottom edge (within tol) without piercing too far through.
        if prev_close < band_lo:
            tol = self.tol_pct * band_lo
            ceil = band_lo + self.pierce_frac * band_h
            if band_lo - tol <= bar_hi <= band_lo + tol and bar_hi <= ceil:
                gap = abs(bar_hi - band_lo)
                score = max(0.0, min(1.0, 1.0 - gap / tol)) if tol > 0 else 1.0
                return Side.SHORT, score, poc, band_lo, band_hi

        return None

    def _fire(
        self,
        highs: list[float],
        lows: list[float],
        closes: list[float],
        idx: pd.Index,
        t: int,
        w0: int,
    ) -> FireEvent | None:
        """Build a :class:`FireEvent` for bar ``t`` if it touches the band.

        ``w0`` is the start index of the slice passed to :meth:`_eval_end`. The
        band edges are reported as references (the viz draws the box from
        ``ref`` = near edge and ``ref2`` = far edge).
        """
        res = self._eval_end(highs[w0 : t + 1], lows[w0 : t + 1], closes[w0 : t + 1])
        if res is None:
            return None
        side, score, _poc, band_lo, band_hi = res
        ts = idx[t].to_pydatetime()
        near, far = (band_hi, band_lo) if side is Side.LONG else (band_lo, band_hi)
        return FireEvent(
            fired_at=ts,
            side=side,
            score=score,
            price=float(closes[t]),
            ref_time=ts,
            ref_price=near,
            ref2_time=ts,
            ref2_price=far,
        )

    def last_fire(self, df: pd.DataFrame) -> FireEvent | None:  # noqa: D102 (override)
        if df.empty:
            return None
        highs = df["high"].tolist()
        lows = df["low"].tolist()
        closes = df["close"].tolist()
        t = len(df) - 1
        w0 = max(0, t - self.window)
        return self._fire(highs, lows, closes, df.index, t, w0)

    def detect(self, df: pd.DataFrame) -> list[FireEvent]:  # noqa: D102 (inherited)
        if df.empty:
            return []
        highs = df["high"].tolist()
        lows = df["low"].tolist()
        closes = df["close"].tolist()
        idx = df.index
        fires: list[FireEvent] = []
        for t in range(len(df)):
            w0 = max(0, t - self.window)
            fire = self._fire(highs, lows, closes, idx, t, w0)
            if fire is not None:
                fires.append(fire)
        return fires
