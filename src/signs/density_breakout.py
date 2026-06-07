"""Density-band breakout detector.

Hypothesis (the user's chart): over a trailing window (~1 week on 1h bars) price
spends most of its time inside a *dense band* — the market-profile value area
built from a time-at-price histogram (see :mod:`src.indicators.density`). The
band is a strong barrier; when price has been **consolidating inside** the band
and then **closes out through an edge**, it tends to **trend away** from the band
(the move continues for many hours to days):

- prior bar closed INSIDE the band, this bar CLOSES ABOVE the top edge -> LONG
- prior bar closed INSIDE the band, this bar CLOSES BELOW the bottom edge -> SHORT

This is the *opposite* trigger to :mod:`src.signs.density_band` (a bounce into the
edge from outside). Here the trade rides a breakout *out of* the value area, so a
pullback ("bounce") back to the band after entry is expected and tolerated — the
companion strategy puts the stop beyond the *opposite* edge, not at the broken
edge.

Causality: every decision at bar ``t`` uses only bars ``<= t``. The profile is
built over ``[t-window, t-1]`` (the breakout bar is excluded so it cannot move the
band it breaks); the "was inside" check uses the prior close; the breakout is read
off bar ``t``'s own close. No look-ahead.

The detector fires at the breakout bar's close (the framework's reference price);
the simulator fills at the next bar's open (two-bar rule).
"""

from __future__ import annotations

import pandas as pd

from src.core.types import Side
from src.indicators.density import time_at_price_profile, value_area
from src.signs.base import FireEvent, Sign


class DensityBreakoutSign(Sign):
    """Fires when price closes out of the dense band after consolidating in it."""

    name = "density_breakout"

    def __init__(
        self,
        window: int = 168,
        n_bins: int = 48,
        coverage: float = 0.70,
        max_band_pct: float | None = 0.02,
        confirm_bars: int = 1,
        min_break_frac: float = 0.0,
    ) -> None:
        """Initialise the detector.

        Args:
            window: Trailing bars used to build the time-at-price profile
                (168 = ~1 week on 1h bars).
            n_bins: Number of price bins in the histogram.
            coverage: Value-area fraction (0.70 = standard market profile).
            max_band_pct: Regime filter — only fire when the band height is at
                most this fraction of price (a *tight* box, like the congestion
                the user drew). Default ``0.02`` (2%); ``None`` disables it.
            confirm_bars: Number of consecutive closes that must sit beyond the
                same edge before firing (the bar just before the run must still be
                *inside* the band). ``1`` (default) = fire on the first breakout
                close; higher values demand the breakout *hold*, filtering
                fakeouts at the cost of a later (worse) entry.
            min_break_frac: Minimum breakout extent of the firing close beyond the
                edge, as a fraction of band height. ``0.0`` (default) = any close
                past the edge qualifies.

        Raises:
            ValueError: On non-positive ``window``/``n_bins``/``confirm_bars`` or
                out-of-range ``coverage``/``max_band_pct``/``min_break_frac``.
        """
        if window < 2:
            raise ValueError("window must be >= 2")
        if n_bins < 1:
            raise ValueError("n_bins must be >= 1")
        if not 0.0 < coverage <= 1.0:
            raise ValueError("coverage must be in (0, 1]")
        if max_band_pct is not None and max_band_pct <= 0.0:
            raise ValueError("max_band_pct must be > 0 when set")
        if confirm_bars < 1:
            raise ValueError("confirm_bars must be >= 1")
        if min_break_frac < 0.0:
            raise ValueError("min_break_frac must be >= 0")
        self.window = window
        self.n_bins = n_bins
        self.coverage = coverage
        self.max_band_pct = max_band_pct
        self.confirm_bars = confirm_bars
        self.min_break_frac = min_break_frac
        self.required_indicators = [f"density_{window}_{n_bins}"]

    def _eval_end(
        self,
        highs: list[float],
        lows: list[float],
        closes: list[float],
    ) -> tuple[Side, float, float, float] | None:
        """Evaluate whether the LAST bar breaks out of the dense band.

        The profile is built over all but the last bar; the last bar is the
        candidate breakout. Returns ``(side, score, band_lo, band_hi)`` or
        ``None``.
        """
        n = len(highs)
        if n < self.window + 1:
            return None

        prof_hi = highs[-(self.window + 1) : -1]
        prof_lo = lows[-(self.window + 1) : -1]
        centers, weights = time_at_price_profile(prof_hi, prof_lo, self.n_bins)
        _poc, band_lo, band_hi = value_area(centers, weights, self.coverage)
        if band_hi <= band_lo:
            return None

        band_h = band_hi - band_lo
        close = closes[-1]
        k = self.confirm_bars

        # The bar just before the breakout run must have been INSIDE the band
        # (price was consolidating), and we need k+1 closes available.
        if n < k + 1:
            return None
        pre_close = closes[-(k + 1)]
        if not (band_lo <= pre_close <= band_hi):
            return None

        # Optional tight-box regime filter.
        if self.max_band_pct is not None and band_h > self.max_band_pct * close:
            return None

        # Confirmation: the last k closes must ALL sit beyond the same edge, and
        # the firing close must clear the edge by at least min_break_frac of the
        # band height. Score = breakout extent as a fraction of band height.
        run = closes[-k:]
        if all(c > band_hi for c in run):
            ext = (close - band_hi) / band_h
            if ext < self.min_break_frac:
                return None
            return Side.LONG, max(0.0, min(1.0, ext)), band_lo, band_hi
        if all(c < band_lo for c in run):
            ext = (band_lo - close) / band_h
            if ext < self.min_break_frac:
                return None
            score = max(0.0, min(1.0, ext))
            return Side.SHORT, score, band_lo, band_hi
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
        """Build a :class:`FireEvent` for bar ``t`` if it breaks out of the band.

        ``ref`` = the broken (near) edge, ``ref2`` = the opposite (far) edge — the
        latter is where the companion strategy places its structural stop, and the
        viz draws the box between them.
        """
        res = self._eval_end(highs[w0 : t + 1], lows[w0 : t + 1], closes[w0 : t + 1])
        if res is None:
            return None
        side, score, band_lo, band_hi = res
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
