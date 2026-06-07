"""Strategy: rsi_extreme_ride — RSI extreme as a CONTINUATION signal, ride exit.

Idea-stage **hit** (own-merit hunt). We probed RSI extremes as *mean-reversion* (fade
oversold/overbought) — and that **lost** (IS −0.25 even gross). Flipping the direction
revealed the real edge: on 1h BTC an RSI extreme is a **continuation** signal — when RSI
crosses into oversold the move *keeps falling* (go SHORT), into overbought it *keeps
rising* (go LONG). One entry per excursion (low-freq, cost-light) into the inherited ride
exit (zs-band SL + next-dense TP + slow ratchet).

Evaluated on its own merit (lockbox OOS Sharpe, cost-robustness, DD): cost-robust, beats
B&H in both lockbox splits, **5/6 walk-forward folds** (the strongest new-idea robustness
on the branch). ``reversal=True`` recovers the rejected mean-reversion variant.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from src.core.types import Bar, ExitConfig, Side, Signal
from src.exit.base import ExitContext
from src.indicators.rsi import rsi
from src.indicators.zigzag import detect_peaks
from src.strategy.density_multi_breakout import _next_dense
from src.strategy.random_hedge import RandomHedgeStrategy


class RsiExtremeRideStrategy(RandomHedgeStrategy):
    """RSI extreme as continuation: oversold→short / overbought→long, ride exit."""

    name = "rsi_extreme_ride"
    description = (
        "RSI extreme = continuation: cross into oversold → short, overbought → long "
        "(one per excursion); zs SL + next-dense TP + slow ratchet. reversal=True = "
        "the rejected mean-reversion variant."
    )

    def __init__(
        self,
        *,
        rsi_period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        reversal: bool = False,
        **kwargs: object,
    ) -> None:
        """Initialise.

        Args:
            rsi_period: RSI lookback.
            oversold: trigger when RSI crosses below this.
            overbought: trigger when RSI crosses above this.
            reversal: if False (default) ride the extreme as continuation (the edge);
                if True, fade it (the rejected mean-reversion variant).
            **kwargs: forwarded to RandomHedgeStrategy (ride exit + gates).
        """
        kwargs.setdefault("recalc_bars", 48)  # ride exit
        kwargs.setdefault("sl_mult", 0.75)
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        self.reversal = reversal

    def precompute_multi(self, bars: list[Bar]) -> dict[datetime, list[Signal]] | None:  # noqa: D102
        if not bars:
            return {}
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        closes = [b.close for b in bars]
        peaks = detect_peaks(highs, lows, size=self.zigzag_size)
        peak_idx = [p.bar_index for p in peaks]
        peak_price = [p.price for p in peaks]
        rsi_s = rsi(pd.Series(closes), self.rsi_period).to_numpy(dtype=float)
        self._ensure_trend(bars)

        out: dict[datetime, list[Signal]] = {}
        for t in range(self.warmup, len(bars)):
            r, rp = rsi_s[t], rsi_s[t - 1]
            if np.isnan(r) or np.isnan(rp):
                continue
            if rp >= self.oversold and r < self.oversold:
                side = Side.LONG if self.reversal else Side.SHORT
            elif rp <= self.overbought and r > self.overbought:
                side = Side.SHORT if self.reversal else Side.LONG
            else:
                continue
            if not self._gate_ok(t, None, None) or not self._trend_ok(side, t):
                continue
            entry = closes[t]
            legs = self._legs(peak_idx, peak_price, t)
            ctx = ExitContext(side=side, entry_price=entry, zs_history=legs)
            band = self._zs.band(ctx)
            sl_abs = self._zs.exit_config(ctx).sl_abs
            target = _next_dense(
                highs, lows, t, entry, side,
                target_window=self.target_window, n_bins=self.n_bins,
                min_frac=self.target_min_frac, min_dist=self.target_min_dist_frac * band,
            )
            cfg = ExitConfig(
                sl_abs=sl_abs,
                tp_abs=abs(target - entry) if target is not None else None,
                time_stop_bars=self.time_stop_bars,
            )
            ts = bars[t].timestamp
            out[ts] = [
                Signal(
                    side=side, timestamp=ts, price=entry, score=1.0, reason=self.name,
                    ref_time=ts, ref_price=target, exit_config=cfg,
                )
            ]
        return out
