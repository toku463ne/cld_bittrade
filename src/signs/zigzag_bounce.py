"""Zigzag bounce detector.

Hypothesis: price tends to bounce near recent, established swing levels. We act
the moment an *early* peak forms at the right edge — a bar that, ``mid_size``
bars later (i.e. now), is the local extreme of its ``size``-left / ``mid_size``-
right window — and bet it will mature into a *confirmed* peak (``size`` bars on
the right, knowable only in the future) **when it sits near a recent confirmed
peak of the same type**:

- early HIGH near a recent confirmed HIGH (resistance)  -> SHORT (rejection)
- early LOW  near a recent confirmed LOW  (support)     -> LONG  (bounce)

Causality: every decision at bar ``t`` uses only bars ``≤ t``. The early-peak
check looks ``mid_size`` bars back; the recent confirmed peaks come from
:func:`~src.indicators.zigzag.detect_peaks` over the trailing window (those peaks
already have ``size`` bars of right-context within the window, so they are known
at ``t``). No look-ahead.
"""

from __future__ import annotations

import pandas as pd

from src.core.types import Side
from src.indicators.zigzag import Peak, confirmed_leg_sizes, detect_peaks
from src.signs.base import FireEvent, Sign


class ZigzagBounceSign(Sign):
    """Fires when a right-edge early peak sits near a recent confirmed peak."""

    name = "zigzag_bounce"

    def __init__(
        self,
        size: int = 10,
        mid_size: int = 3,
        windows: tuple[int, ...] = (60, 120, 180),
        tol_pct: float = 0.005,
        n_legs: int = 6,
    ) -> None:
        if mid_size >= size:
            raise ValueError("mid_size must be < size")
        if not windows:
            raise ValueError("windows must be non-empty")
        self.size = size
        self.mid_size = mid_size
        # Expanding lookback windows for the "outstanding" peak: try the first;
        # if no confirmed same-type peak is found, expand to the next.
        self.windows = tuple(sorted(windows))
        self.tol_pct = tol_pct
        self.n_legs = n_legs
        # Trailing window: widest lookback + left context for the early peak +
        # the confirmed peaks' own right-context.
        self.window = self.windows[-1] + 2 * size + mid_size + 5
        self.required_indicators = [f"zigzag_{size}_{mid_size}"]

    def _outstanding(
        self, peaks: list[Peak], is_high: bool, ep_idx: int
    ) -> Peak | None:
        """The 'outstanding' confirmed peak: the most extreme same-type peak in
        the smallest expanding window (60 -> 120 -> 180) that contains one.

        For a high it is the highest confirmed high; for a low, the lowest
        confirmed low. Returns the :class:`Peak` or ``None`` if no same-type
        confirmed peak exists within the widest window.
        """
        for win in self.windows:
            lo = ep_idx - win
            cand = [
                p
                for p in peaks
                if p.is_confirmed and p.is_high == is_high and lo <= p.bar_index < ep_idx
            ]
            if cand:
                return max(cand, key=lambda p: p.price) if is_high else min(
                    cand, key=lambda p: p.price
                )
        return None

    def _eval_end(
        self, highs: list[float], lows: list[float]
    ) -> tuple[Side, float, tuple[float, ...]] | None:
        """Evaluate whether the LAST bar of the window triggers a bounce.

        Returns ``(side, score, legs)`` or ``None``. The early-peak candidate is
        the bar ``mid_size`` positions before the end; it must sit within
        ``tol_pct`` of the *outstanding* confirmed peak of the same type.
        """
        n = len(highs)
        ep_idx = n - 1 - self.mid_size
        left = ep_idx - self.size
        if left < 0:
            return None

        # Right-edge early peak: extreme over [left .. now].
        is_high = highs[ep_idx] == max(highs[left:n])
        is_low = lows[ep_idx] == min(lows[left:n])
        if is_high == is_low:  # neither, or ambiguous flat window
            return None

        peaks = detect_peaks(highs, lows, self.size, self.mid_size)
        ep_price = highs[ep_idx] if is_high else lows[ep_idx]
        if ep_price <= 0.0:
            return None

        outstanding = self._outstanding(peaks, is_high, ep_idx)
        if outstanding is None:
            return None
        dist = abs(outstanding.price - ep_price) / ep_price
        if dist > self.tol_pct:
            return None

        side = Side.SHORT if is_high else Side.LONG
        score = max(0.0, min(1.0, 1.0 - dist / self.tol_pct))
        legs = confirmed_leg_sizes(peaks)[-self.n_legs :]
        return side, score, legs

    def last_fire(self, df: pd.DataFrame) -> FireEvent | None:  # noqa: D102 (override)
        if df.empty:
            return None
        res = self._eval_end(df["high"].tolist(), df["low"].tolist())
        if res is None:
            return None
        side, score, legs = res
        return FireEvent(
            fired_at=df.index[-1].to_pydatetime(),
            side=side,
            score=score,
            price=float(df["close"].iloc[-1]),
            legs=legs,
        )

    def detect(self, df: pd.DataFrame) -> list[FireEvent]:  # noqa: D102 (inherited)
        if df.empty:
            return []
        highs = df["high"].tolist()
        lows = df["low"].tolist()
        closes = df["close"].tolist()
        idx = df.index
        fires: list[FireEvent] = []
        w = self.window
        for t in range(len(df)):
            w0 = max(0, t - w + 1)
            res = self._eval_end(highs[w0 : t + 1], lows[w0 : t + 1])
            if res is not None:
                side, score, legs = res
                fires.append(
                    FireEvent(idx[t].to_pydatetime(), side, score, float(closes[t]), legs)
                )
        return fires
