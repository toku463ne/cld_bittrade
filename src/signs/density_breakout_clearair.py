"""Density-band breakout with a "clear-air" swing filter.

Same trigger as :class:`src.signs.density_breakout.DensityBreakoutSign` (ride a
close out of the value area), plus ONE extra knob: suppress the fire when the
**nearest recent zigzag swing in the breakout direction** sits too close — an
overhead swing high for a LONG, an underfoot swing low for a SHORT. The diagnostic
(``src/backtest/analysis/entry_filter_probe.py``) found that breakouts firing with
a swing within ~0.5% of entry underperform those that break into *clear air*: the
move stalls immediately on the overhead supply. So this is a loss-avoidance gate,
not a new entry. Note the mechanism is "needs room to run," not the originally
hypothesised "trapped-trader resistance" — the empirical sign is the same.

This is a clean single-knob A/B over ``density_breakout``: ``clear_air_pct == 0.0``
reproduces it exactly (nothing is ever cancelled). Causality is preserved — a
swing at bar ``p`` is consulted only once it is confirmable by the fire bar
(``p + zigzag_size <= t``); no look-ahead.
"""

from __future__ import annotations

import pandas as pd

from src.core.types import Side
from src.indicators.zigzag import detect_peaks
from src.signs.base import FireEvent, Sign
from src.signs.density_breakout import DensityBreakoutSign


class DensityBreakoutClearairSign(Sign):
    """density_breakout, minus breakouts that have no clear air ahead of them."""

    name = "density_breakout_clearair"

    def __init__(
        self,
        window: int = 168,
        n_bins: int = 48,
        coverage: float = 0.70,
        max_band_pct: float | None = 0.02,
        confirm_bars: int = 1,
        min_break_frac: float = 0.0,
        zigzag_size: int = 12,
        clear_air_pct: float = 0.005,
        swing_lookback: int = 168,
    ) -> None:
        """Initialise the detector.

        Args:
            window: Trailing bars for the time-at-price profile (see the base sign).
            n_bins: Histogram price bins (see the base sign).
            coverage: Value-area fraction (see the base sign).
            max_band_pct: Tight-box regime filter (see the base sign).
            confirm_bars: Consecutive closes beyond the edge to fire (base sign).
            min_break_frac: Minimum breakout extent past the edge (base sign).
            zigzag_size: Bars required on each side of a confirmed swing
                (:func:`src.indicators.zigzag.detect_peaks`). The probe showed the
                cancellation sign is stable across 8/12/16; 12 is the middle.
            clear_air_pct: Cancel the fire if the nearest same-direction swing is
                within this fraction of the entry price. ``0.0`` disables the
                filter (== plain ``density_breakout``). Default ``0.005`` (0.5%).
            swing_lookback: Only swings within this many bars before the fire are
                considered "recent". Defaults to ``window``.

        Raises:
            ValueError: On out-of-range parameters.
        """
        if zigzag_size < 2:
            raise ValueError("zigzag_size must be >= 2")
        if clear_air_pct < 0.0:
            raise ValueError("clear_air_pct must be >= 0")
        if swing_lookback < 1:
            raise ValueError("swing_lookback must be >= 1")
        self._base = DensityBreakoutSign(
            window=window,
            n_bins=n_bins,
            coverage=coverage,
            max_band_pct=max_band_pct,
            confirm_bars=confirm_bars,
            min_break_frac=min_break_frac,
        )
        self.zigzag_size = zigzag_size
        self.clear_air_pct = clear_air_pct
        self.swing_lookback = swing_lookback
        # Carry the base sign's framework hooks so the strategy can size its buffer.
        self.window = self._base.window
        self.required_indicators = self._base.required_indicators

    def _has_clear_air(
        self,
        highs: list[float],
        lows: list[float],
        t: int,
        entry: float,
        is_long: bool,
    ) -> bool:
        """True if no recent confirmable same-direction swing sits within
        ``clear_air_pct`` of ``entry`` (i.e. the breakout has room to run)."""
        if self.clear_air_pct <= 0.0:
            return True
        peaks = detect_peaks(highs, lows, size=self.zigzag_size)
        lo_bound = t - self.swing_lookback
        thresh = self.clear_air_pct * entry
        for p in peaks:
            if p.bar_index + self.zigzag_size > t or p.bar_index < lo_bound:
                continue  # not yet confirmable by t, or too old
            if is_long and p.is_high and 0.0 <= (p.price - entry) < thresh:
                return False
            if (not is_long) and (not p.is_high) and 0.0 <= (entry - p.price) < thresh:
                return False
        return True

    def detect(self, df: pd.DataFrame) -> list[FireEvent]:  # noqa: D102 (inherited)
        if df.empty:
            return []
        highs = df["high"].tolist()
        lows = df["low"].tolist()
        idx = df.index
        ts_to_pos = {ts: i for i, ts in enumerate(idx)}
        kept: list[FireEvent] = []
        for fire in self._base.detect(df):
            t = ts_to_pos[pd.Timestamp(fire.fired_at)]
            if self._has_clear_air(highs, lows, t, fire.price, fire.side is Side.LONG):
                kept.append(fire)
        return kept

    def last_fire(self, df: pd.DataFrame) -> FireEvent | None:  # noqa: D102 (override)
        fire = self._base.last_fire(df)
        if fire is None:
            return None
        highs = df["high"].tolist()
        lows = df["low"].tolist()
        t = len(df) - 1
        if self._has_clear_air(highs, lows, t, fire.price, fire.side is Side.LONG):
            return fire
        return None
