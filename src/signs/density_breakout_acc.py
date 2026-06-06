"""Density-band breakout detector — body/wick time-acceptance variant (A/B).

Identical trigger logic to :class:`src.signs.density_breakout.DensityBreakoutSign`
(consolidate inside the value area, then close out through an edge -> ride the
trend), but the dense band is built from a **body/wick-weighted time-at-price
profile** (:func:`src.indicators.density.time_acceptance_profile`) instead of the
plain uniform time profile. The candle **body** (open->close) counts as
*acceptance* and the **wicks** (hige) as *rejection*, so a level price merely
spiked to and rejected contributes less density than a level it traded through.

This isolates the body/wick (hige / marubozu) effect as a SINGLE knob vs the
shipping time profile — unlike :mod:`src.signs.density_breakout_vol`, which
changed both volume *and* body/wick at once. At ``body_ratio == 0.5`` the profile
is identical to the plain time profile, so the A/B is clean: any difference is the
hige weighting alone. Keep the trigger / causality / FireEvent semantics
word-for-word the same as the time sign.

Causality: the profile is built over ``[t-window, t-1]`` (the breakout bar is
excluded); the "was inside" check uses the prior close; the breakout is read off
bar ``t``'s own close. No look-ahead.
"""

from __future__ import annotations

import pandas as pd

from src.core.types import Side
from src.indicators.density import time_acceptance_profile, value_area
from src.signs.base import FireEvent, Sign


class DensityBreakoutAccSign(Sign):
    """Body/wick time-acceptance dense-band breakout (A/B sibling of density_breakout)."""

    name = "density_breakout_acc"

    def __init__(
        self,
        window: int = 168,
        n_bins: int = 48,
        coverage: float = 0.70,
        max_band_pct: float | None = 0.02,
        confirm_bars: int = 1,
        min_break_frac: float = 0.0,
        body_ratio: float = 0.7,
    ) -> None:
        """Initialise the detector.

        Args mirror :class:`DensityBreakoutSign` (window, n_bins, coverage,
        max_band_pct, confirm_bars, min_break_frac); see that class for their
        meaning. The profile-specific knob:

        Args:
            body_ratio: Weight on the candle body vs wicks when building the
                profile, in ``[0, 1]`` (see :func:`time_acceptance_profile`).
                ``0.5`` reproduces the plain uniform time profile exactly;
                ``> 0.5`` down-weights the wicks (hige = rejection). Default 0.7.

        Raises:
            ValueError: On out-of-range parameters (same bounds as the sibling
                sign, plus ``body_ratio`` in ``[0, 1]``).
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
        if not 0.0 <= body_ratio <= 1.0:
            raise ValueError("body_ratio must be in [0, 1]")
        self.window = window
        self.n_bins = n_bins
        self.coverage = coverage
        self.max_band_pct = max_band_pct
        self.confirm_bars = confirm_bars
        self.min_break_frac = min_break_frac
        self.body_ratio = body_ratio
        self.required_indicators = [f"density_acc_{window}_{n_bins}"]

    def _eval_end(
        self,
        opens: list[float],
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

        sl = slice(-(self.window + 1), -1)  # the breakout bar is excluded
        centers, weights = time_acceptance_profile(
            opens[sl],
            highs[sl],
            lows[sl],
            closes[sl],
            self.n_bins,
            body_ratio=self.body_ratio,
        )
        _poc, band_lo, band_hi = value_area(centers, weights, self.coverage)
        if band_hi <= band_lo:
            return None

        band_h = band_hi - band_lo
        close = closes[-1]
        k = self.confirm_bars

        # The bar just before the breakout run must have been INSIDE the band.
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
        opens: list[float],
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
        res = self._eval_end(
            opens[w0 : t + 1],
            highs[w0 : t + 1],
            lows[w0 : t + 1],
            closes[w0 : t + 1],
        )
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
        opens = df["open"].tolist()
        highs = df["high"].tolist()
        lows = df["low"].tolist()
        closes = df["close"].tolist()
        t = len(df) - 1
        w0 = max(0, t - self.window)
        return self._fire(opens, highs, lows, closes, df.index, t, w0)

    def detect(self, df: pd.DataFrame) -> list[FireEvent]:  # noqa: D102 (inherited)
        if df.empty:
            return []
        opens = df["open"].tolist()
        highs = df["high"].tolist()
        lows = df["low"].tolist()
        closes = df["close"].tolist()
        idx = df.index
        fires: list[FireEvent] = []
        for t in range(len(df)):
            w0 = max(0, t - self.window)
            fire = self._fire(opens, highs, lows, closes, idx, t, w0)
            if fire is not None:
                fires.append(fire)
        return fires
