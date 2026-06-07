"""Strategy: vol_expansion_ride — squeeze→expansion breakout into the ride exit.

Idea-stage candidate (Strategy idea #2). The recurring branch lesson is that *turnover
cost* kills edges, so this targets a **low-frequency, cost-light** trigger distinct from
the density box: a **volatility squeeze followed by an expansion**. When ATR has been
compressed (a squeeze) and a bar's true range bursts (TR ≥ ``expand_mult`` × prior ATR),
ride that bar's direction with the tuned ride exit (zs-band SL + next-dense TP + slow
ratchet) inherited from :class:`~src.strategy.random_hedge.RandomHedgeStrategy`.

Entry is market (next open). Squeeze→expansion is rare → few trades → cost-light, the
opposite of the 15m/5m density probe that died on turnover.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from src.core.types import Bar, ExitConfig, Side, Signal
from src.exit.base import ExitContext
from src.indicators.zigzag import detect_peaks
from src.strategy.density_multi_breakout import _next_dense
from src.strategy.random_hedge import RandomHedgeStrategy


class VolExpansionRideStrategy(RandomHedgeStrategy):
    """Ride a volatility expansion out of a squeeze, with the tuned ride exit."""

    name = "vol_expansion_ride"
    description = (
        "Squeeze→expansion: after compressed ATR, a true-range burst (TR >= mult × "
        "ATR) rides the burst bar's direction; zs SL + next-dense TP + slow ratchet."
    )

    def __init__(
        self,
        *,
        atr_period: int = 14,
        squeeze_rank_max: float = 0.25,
        expand_mult: float = 2.0,
        rank_window: int = 500,
        **kwargs: object,
    ) -> None:
        """Initialise.

        Args:
            atr_period: ATR lookback for squeeze/expansion.
            squeeze_rank_max: squeeze if the prior-bar ATR trailing-percentile rank
                is <= this (low-vol regime).
            expand_mult: expansion if the bar's true range >= this × the prior ATR.
            rank_window: trailing window for the ATR percentile rank.
            **kwargs: forwarded to RandomHedgeStrategy (the tuned ride exit + gates).
        """
        kwargs.setdefault("recalc_bars", 48)  # tuned ride exit
        # Tighter stop than the density ride: a vol-expansion entry has an immediate
        # directional thesis, so a wrong one is cut fast. sl=0.4 cuts the DD (1.29→0.77)
        # AND raises Sharpe; backtest keeps "improving" to ~0.15 but that is sub-bar-range
        # artifact (intrabar noise the bar sim can't see), so 0.4 is the realistic floor
        # (~one 1h-bar range). See docs/strategy/vol_expansion_ride.md §3.
        kwargs.setdefault("sl_mult", 0.4)
        # Skip counter-trend bursts (a down-burst in a strong uptrend bleeds): cuts DD
        # 0.77→0.47 and softens the bad regimes, for a modest Sharpe giveback (§3).
        kwargs.setdefault("drop_counter_trend", True)
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.atr_period = atr_period
        self.squeeze_rank_max = squeeze_rank_max
        self.expand_mult = expand_mult
        self.rank_window = rank_window
        self.warmup = max(self.warmup, rank_window + 2)
        self.max_buffer = self.warmup + 2

    def precompute_multi(self, bars: list[Bar]) -> dict[datetime, list[Signal]] | None:  # noqa: D102
        if not bars:
            return {}
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        closes = [b.close for b in bars]
        opens = [b.open for b in bars]
        peaks = detect_peaks(highs, lows, size=self.zigzag_size)
        peak_idx = [p.bar_index for p in peaks]
        peak_price = [p.price for p in peaks]
        atr_s = self._atr_series(highs, lows, closes, self.atr_period)
        self._ensure_trend(bars)  # for the optional drop_counter_trend gate
        # true range per bar
        tr = [highs[0] - lows[0]] + [
            max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            for i in range(1, len(bars))
        ]
        atr_arr = np.array(atr_s, dtype=float)

        out: dict[datetime, list[Signal]] = {}
        for t in range(self.warmup, len(bars)):
            a_prev = atr_arr[t - 1]
            if np.isnan(a_prev) or a_prev <= 0.0:
                continue
            # squeeze: prior ATR in the low tail of its trailing distribution
            w = atr_arr[max(0, t - 1 - self.rank_window) : t]
            vals = w[~np.isnan(w)]
            if vals.size == 0:
                continue
            rank = float(np.mean(vals <= a_prev))
            if rank > self.squeeze_rank_max:
                continue
            # expansion: this bar's true range bursts
            if tr[t] < self.expand_mult * a_prev:
                continue
            side = Side.LONG if closes[t] >= opens[t] else Side.SHORT
            if not self._gate_ok(t, None, None):
                continue
            if not self._trend_ok(side, t):  # optional: skip counter-trend bursts
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
