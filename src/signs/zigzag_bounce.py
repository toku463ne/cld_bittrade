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


def _leg_ewa(legs: tuple[float, ...], alpha: float = 0.3) -> float:
    """EWA of zigzag leg sizes (oldest-first; newest weighted by ``alpha``)."""
    out = legs[0]
    for leg in legs[1:]:
        out = alpha * leg + (1.0 - alpha) * out
    return out


class ZigzagBounceSign(Sign):
    """Fires when a right-edge early peak sits near a recent confirmed peak."""

    name = "zigzag_bounce"

    def __init__(
        self,
        size: int = 10,
        mid_size: int = 3,
        windows: tuple[int, ...] = (60, 120, 180),
        tol_pct: float = 0.005,
        tol_leg_frac: float | None = None,
        n_legs: int = 6,
        reverse_levels: bool = False,
        require_break: bool = True,
        dominant_window: int | None = None,
    ) -> None:
        if mid_size >= size:
            raise ValueError("mid_size must be < size")
        if not windows:
            raise ValueError("windows must be non-empty")
        if dominant_window is not None and dominant_window <= 0:
            raise ValueError("dominant_window must be > 0 when set")
        self.size = size
        self.mid_size = mid_size
        # Expanding lookback windows for the "outstanding" peak: try the first;
        # if no confirmed same-type peak is found, expand to the next.
        self.windows = tuple(sorted(windows))
        # Optional "dominant level": the most-extreme same-type confirmed peak
        # over this long lookback (~1 week on 1h) is added as a candidate even
        # when nearer minor peaks exist, so price can bounce off a long-standing
        # floor/ceiling (e.g. a weekly low retest). Nearest-in-price still wins.
        # None (default) = today's expanding-window-only behavior.
        self.dominant_window = dominant_window
        self.tol_pct = tol_pct
        # Optional volatility-scaled "near" band: when set, tolerance =
        # tol_leg_frac × EWA(recent zigzag legs) instead of tol_pct × price, so
        # "near" widens/tightens with the market's own swing size. Falls back to
        # tol_pct when there are no legs yet. Default None (fixed-pct baseline).
        self.tol_leg_frac = tol_leg_frac
        self.n_legs = n_legs
        # Optional S/R role reversal (off by default — same-type was cleanest on
        # the interim sample). When on, opposite-type levels also qualify; with
        # require_break they must have been crossed. A/B these once data is deep.
        self.reverse_levels = reverse_levels
        self.require_break = require_break
        # Trailing window: widest lookback (expanding or dominant, whichever is
        # larger) + left context for the early peak + the confirmed peaks' own
        # right-context.
        widest = max(self.windows[-1], dominant_window or 0)
        self.window = widest + 2 * size + mid_size + 5
        self.required_indicators = [f"zigzag_{size}_{mid_size}"]

    def _outstanding(
        self,
        peaks: list[Peak],
        ep_price: float,
        ep_idx: int,
        is_high: bool,
        highs: list[float],
        lows: list[float],
    ) -> Peak | None:
        """The outstanding reference level near the early peak.

        Within the smallest expanding window (60 -> 120 -> 180) that yields a
        confirmed peak, the nearest-in-price reference wins among:

        - **Same-type standout** (always): the most extreme same-type confirmed
          peak (highest high for an early high / lowest low for an early low) —
          a normal resistance/support retest.
        - **Role-reversal** (only if ``reverse_levels``): an opposite-type
          confirmed peak — a prior high as support, a prior low as resistance.
          If ``require_break`` (default), it must have been *crossed* (price
          traded through it) to count. Both default OFF/strict because same-type
          matching was cleanest on the interim sample; flip them to A/B once
          there is enough data.
        - **Dominant level** (only if ``dominant_window``): the most-extreme
          same-type confirmed peak over the long lookback, added even when the
          expanding window already found nearer minor peaks, so price can bounce
          off a long-standing floor/ceiling. Nearest-in-price still wins overall.
        """
        refs: list[Peak] = []
        for win in self.windows:
            lo = ep_idx - win
            cand = [p for p in peaks if p.is_confirmed and lo <= p.bar_index < ep_idx]
            if not cand:
                continue
            same = [p for p in cand if p.is_high == is_high]
            if same:
                refs.append(max(same, key=lambda p: p.price) if is_high
                            else min(same, key=lambda p: p.price))
            if self.reverse_levels:
                for p in cand:
                    if p.is_high == is_high:
                        continue
                    if self.require_break:
                        # early high: a prior LOW becomes resistance only if price
                        # later broke BELOW it; early low: a prior HIGH becomes
                        # support only if price later broke ABOVE it.
                        seg_lo = p.bar_index + 1
                        broke = (
                            min(lows[seg_lo : ep_idx + 1]) < p.price
                            if is_high
                            else max(highs[seg_lo : ep_idx + 1]) > p.price
                        )
                        if not broke:
                            continue
                    refs.append(p)
            if refs:
                break  # first non-empty expanding window only (existing behavior)

        # Dominant level: the same-type extreme over the long lookback. By being
        # the extreme it is by definition unbroken since it formed, so it is the
        # strongest standing support/resistance — included as an extra candidate.
        if self.dominant_window is not None:
            lo = ep_idx - self.dominant_window
            dom = [
                p for p in peaks
                if p.is_confirmed and p.is_high == is_high and lo <= p.bar_index < ep_idx
            ]
            if dom:
                refs.append(max(dom, key=lambda p: p.price) if is_high
                            else min(dom, key=lambda p: p.price))

        if refs:
            return min(refs, key=lambda p: abs(p.price - ep_price))
        return None

    def _eval_end(
        self, highs: list[float], lows: list[float]
    ) -> tuple[Side, float, tuple[float, ...], int, float] | None:
        """Evaluate whether the LAST bar of the window triggers a bounce.

        Returns ``(side, score, legs, outstanding_idx, outstanding_price)`` or
        ``None``. ``outstanding_idx`` is the window-relative bar index of the
        outstanding peak the early peak bounced off (the caller maps it to a
        timestamp). The early-peak candidate is the bar ``mid_size`` positions
        before the end; it must sit within ``tol_pct`` of that peak.
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

        outstanding = self._outstanding(peaks, ep_price, ep_idx, is_high, highs, lows)
        if outstanding is None:
            return None

        legs = confirmed_leg_sizes(peaks)[-self.n_legs :]
        # "Near" band: volatility-scaled (fraction of a recent zigzag leg) when
        # tol_leg_frac is set and legs exist; else fixed fraction of price.
        if self.tol_leg_frac is not None and legs:
            band = self.tol_leg_frac * _leg_ewa(legs)
        else:
            band = self.tol_pct * ep_price
        gap = abs(outstanding.price - ep_price)
        if band <= 0.0 or gap > band:
            return None

        side = Side.SHORT if is_high else Side.LONG
        score = max(0.0, min(1.0, 1.0 - gap / band))
        return side, score, legs, outstanding.bar_index, outstanding.price

    def last_fire(self, df: pd.DataFrame) -> FireEvent | None:  # noqa: D102 (override)
        if df.empty:
            return None
        res = self._eval_end(df["high"].tolist(), df["low"].tolist())
        if res is None:
            return None
        side, score, legs, out_idx, out_price = res
        return FireEvent(
            fired_at=df.index[-1].to_pydatetime(),
            side=side,
            score=score,
            price=float(df["close"].iloc[-1]),
            legs=legs,
            ref_time=df.index[out_idx].to_pydatetime(),
            ref_price=out_price,
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
                side, score, legs, out_idx, out_price = res
                fires.append(
                    FireEvent(
                        idx[t].to_pydatetime(), side, score, float(closes[t]), legs,
                        ref_time=idx[w0 + out_idx].to_pydatetime(),
                        ref_price=out_price,
                    )
                )
        return fires
