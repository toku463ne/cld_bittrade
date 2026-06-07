"""Volume-only-wall breakout detector (the user's additive-volume idea).

The shipped :mod:`src.signs.density_breakout` rides a break out of the single
time-at-price value area. The user's intention for "volume" was *additive*: a
high-**volume** price zone should act as an **extra** wall that the time profile
misses, giving MORE breakout chances. The :mod:`src.signs.density_breakout_vol`
A/B did NOT test that (it *reweighted* one band); the additive idea was measured
by ``src/backtest/analysis/volume_walls_probe.py``, which found the added walls
are coin flips (DR ~0.49 at the ride horizon — no directional edge).

This sign exists to *see those added entries on the chart* (Backtest tab). It
fires only on a **vol_only** wall: a volume-profile wall whose price zone overlaps
NO time-profile wall — i.e. exactly the "extra" barrier the time profile would
never have produced — when price was consolidating inside it and then closes out
through an edge. The trigger / causality / FireEvent box semantics are otherwise
word-for-word the same as :class:`DensityBreakoutSign`.

Causality: both profiles are built over ``[t-window, t-1]`` on a shared price grid
(the breakout bar is excluded so it cannot move the wall it breaks); the "was
inside" check uses the prior close; the breakout is read off bar ``t``'s own
close. No look-ahead.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.core.types import Side
from src.indicators.density import (
    find_walls,
    time_at_price_profile,
    volume_acceptance_profile,
)
from src.signs.base import FireEvent, Sign

Wall = tuple[float, float, float]


def _overlaps(a: Wall, walls: list[Wall]) -> bool:
    """True if wall ``a``'s ``[lo, hi]`` zone overlaps any wall in ``walls``."""
    return any(a[0] <= w[1] and w[0] <= a[1] for w in walls)


class DensityVolwallBreakoutSign(Sign):
    """Fires on a breakout out of a volume-only wall (no overlapping time wall)."""

    name = "density_volwall_breakout"

    def __init__(
        self,
        window: int = 168,
        n_bins: int = 48,
        prominence_k: float = 1.0,
        max_band_pct: float | None = 0.02,
        vol_clip: float | None = 8.0,
    ) -> None:
        """Initialise the detector.

        Args:
            window: Trailing bars used to build both profiles (168 = ~1 week 1h).
            n_bins: Number of price bins in each histogram (shared grid).
            prominence_k: A bin joins a wall when its weight exceeds
                ``mean + prominence_k * std`` of the profile (see
                :func:`src.indicators.density.find_walls`).
            max_band_pct: Tight-wall regime filter — only fire when the wall's
                width is at most this fraction of price (mirrors the shipped
                breakout's tight-box filter). Default ``0.02`` (2%); ``None``
                disables it.
            vol_clip: Per-bar volume cap (in window-mean units) for the volume
                profile, so one outsized print cannot define a wall. Default 8.0.

        Raises:
            ValueError: On out-of-range parameters.
        """
        if window < 2:
            raise ValueError("window must be >= 2")
        if n_bins < 1:
            raise ValueError("n_bins must be >= 1")
        if prominence_k < 0.0:
            raise ValueError("prominence_k must be >= 0")
        if max_band_pct is not None and max_band_pct <= 0.0:
            raise ValueError("max_band_pct must be > 0 when set")
        if vol_clip is not None and vol_clip <= 0.0:
            raise ValueError("vol_clip must be > 0 when set")
        self.window = window
        self.n_bins = n_bins
        self.prominence_k = prominence_k
        self.max_band_pct = max_band_pct
        self.vol_clip = vol_clip
        self.required_indicators = []

    def _eval_end(
        self,
        opens: list[float],
        highs: list[float],
        lows: list[float],
        closes: list[float],
        volumes: list[float],
    ) -> tuple[Side, float, float, float] | None:
        """Evaluate whether the LAST bar breaks out of a vol_only wall.

        Both profiles are built over all but the last bar; the last bar is the
        candidate breakout. Returns ``(side, score, wall_lo, wall_hi)`` for the
        broken volume-only wall, or ``None``.
        """
        n = len(highs)
        if n < self.window + 1:
            return None

        sl = slice(-(self.window + 1), -1)  # the breakout bar is excluded
        h = np.asarray(highs[sl], dtype=np.float64)
        low_arr = np.asarray(lows[sl], dtype=np.float64)
        lo_b = float(low_arr.min())
        hi_b = float(h.max())
        if hi_b <= lo_b:
            return None

        ct, wt = time_at_price_profile(h, low_arr, self.n_bins, lo=lo_b, hi=hi_b)
        cv, wv = volume_acceptance_profile(
            opens[sl],
            highs[sl],
            lows[sl],
            closes[sl],
            volumes[sl],
            self.n_bins,
            body_ratio=0.5,
            lo=lo_b,
            hi=hi_b,
            vol_clip=self.vol_clip,
        )
        walls_t = find_walls(ct, wt, prominence_k=self.prominence_k)
        walls_v = find_walls(cv, wv, prominence_k=self.prominence_k)

        pre_close = closes[-2]
        close = closes[-1]

        for wall in walls_v:
            wlo, whi, _peak = wall
            if not (wlo <= pre_close <= whi):
                continue
            if _overlaps(wall, walls_t):  # not a vol_only wall
                continue
            wall_h = whi - wlo
            if self.max_band_pct is not None and wall_h > self.max_band_pct * close:
                continue
            if close > whi:
                score = max(0.0, min(1.0, (close - whi) / wall_h))
                return Side.LONG, score, wlo, whi
            if close < wlo:
                score = max(0.0, min(1.0, (wlo - close) / wall_h))
                return Side.SHORT, score, wlo, whi
        return None

    def _fire(
        self,
        opens: list[float],
        highs: list[float],
        lows: list[float],
        closes: list[float],
        volumes: list[float],
        idx: pd.Index,
        t: int,
        w0: int,
    ) -> FireEvent | None:
        """Build a :class:`FireEvent` for bar ``t`` if it breaks a vol_only wall.

        ``ref`` = the broken (near) edge, ``ref2`` = the opposite (far) edge — the
        companion strategy puts its structural stop beyond the far edge and the viz
        draws the box between them (same convention as ``density_breakout``).
        """
        res = self._eval_end(
            opens[w0 : t + 1],
            highs[w0 : t + 1],
            lows[w0 : t + 1],
            closes[w0 : t + 1],
            volumes[w0 : t + 1],
        )
        if res is None:
            return None
        side, score, wall_lo, wall_hi = res
        ts = idx[t].to_pydatetime()
        near, far = (wall_hi, wall_lo) if side is Side.LONG else (wall_lo, wall_hi)
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
        volumes = df["volume"].tolist()
        t = len(df) - 1
        w0 = max(0, t - self.window)
        return self._fire(opens, highs, lows, closes, volumes, df.index, t, w0)

    def detect(self, df: pd.DataFrame) -> list[FireEvent]:  # noqa: D102 (inherited)
        if df.empty:
            return []
        opens = df["open"].tolist()
        highs = df["high"].tolist()
        lows = df["low"].tolist()
        closes = df["close"].tolist()
        volumes = df["volume"].tolist()
        idx = df.index
        fires: list[FireEvent] = []
        for t in range(len(df)):
            w0 = max(0, t - self.window)
            fire = self._fire(opens, highs, lows, closes, volumes, idx, t, w0)
            if fire is not None:
                fires.append(fire)
        return fires
