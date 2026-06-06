"""Strategy: random_hedge — random entry, hedged both sides, exit-driven.

A deliberate NULL-ENTRY experiment. Every probe on this branch concluded the
density breakout has no directional *entry* edge — the payoff lives in the EXIT /
position management. This strategy strips entry skill to zero to test that claim
head-on: at random bars it opens BOTH a long and a short (a market-neutral hedged
pair, two-bar fill), so the entry contributes no directional expectation and ALL
P&L comes from the asymmetric exits:

- **SL** — the ``ZsTpSl`` EWA band of recent zigzag leg sizes (adaptive
  volatility), ``sl_mult × band`` from entry.
- **TP** — the next *pre-existing* dense node beyond entry in the trade direction
  (``density_multi_breakout._next_dense``), so winners run to real congestion.
- **Ratchet** — every ``recalc_bars`` bars, if the leg is winning, trail the stop
  up to ``favorable_extreme − band`` (never loosened), via the ``dynamic_exit``
  hook. This is the "recalculate the SL toward the winner side" rule.

Entry is a placeholder (random, seeded for reproducibility) — the point is to see
whether the exit machinery alone is profitable, then replace the random entry with
a better-priced one once the exit is validated. Many overlapping pairs are held
(``max_slots`` high) and judged by the mark-to-market equity Sharpe, with a fixed
seed so the backtest is deterministic.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from src.core.types import Bar, ExitConfig, ExitReason, Side, Signal
from src.exit.base import ExitContext
from src.exit.rules import OpenPosition
from src.exit.zs_tp_sl import ZsTpSl
from src.indicators.zigzag import detect_peaks
from src.strategy.base import Strategy
from src.strategy.density_multi_breakout import _next_dense


class RandomHedgeStrategy(Strategy):
    """Random hedged-pair entries with zs SL, dense TP and a periodic SL ratchet."""

    name = "random_hedge"
    description = (
        "Null-entry control: open a long+short hedged pair on random bars; exit "
        "each leg on a zs-band stop, a next-dense take-profit, or a periodic "
        "ratcheting trail. Tests whether the EXIT alone carries the edge."
    )
    max_slots = 50

    def __init__(
        self,
        entry_prob: float = 0.01,
        seed: int = 0,
        zigzag_size: int = 12,
        max_legs: int = 8,
        sl_mult: float = 1.0,
        zs_alpha: float = 0.3,
        zs_min_legs: int = 3,
        zs_fallback_pct: float = 0.01,
        winsorize_k: float | None = 3.0,
        recalc_bars: int = 12,
        time_stop_bars: int = 120,
        target_window: int = 336,
        n_bins: int = 48,
        target_min_frac: float = 0.40,
        target_min_dist_frac: float = 1.0,
    ) -> None:
        """Initialise the strategy.

        Args:
            entry_prob: Per-bar probability of a (hedged-pair) entry event.
            seed: RNG seed for deterministic entries.
            zigzag_size: Bars on each side for a confirmed zigzag peak (leg sizing).
            max_legs: Most recent legs fed to the zs band.
            sl_mult: SL distance = ``sl_mult × zs_band``.
            zs_alpha: EWA smoothing for the zs band.
            zs_min_legs: Min legs before the EWA is trusted (else ``zs_fallback_pct``).
            zs_fallback_pct: Fallback band as a fraction of entry price.
            winsorize_k: Robust high-side leg cap before the EWA (see ``ZsTpSl``).
            recalc_bars: Recompute the trailing stop every this many bars.
            time_stop_bars: Force-exit backstop in bars.
            target_window: Trailing bars for the dense take-profit profile.
            n_bins: Histogram bins for the dense target.
            target_min_frac: A target node must weigh >= this fraction of the
                profile point-of-control.
            target_min_dist_frac: The target must sit >= this fraction of the zs
                band beyond entry (so the TP is not trivially close).

        Raises:
            ValueError: On out-of-range probability / parameters.
        """
        super().__init__()
        if not 0.0 < entry_prob <= 1.0:
            raise ValueError("entry_prob must be in (0, 1]")
        if recalc_bars < 1:
            raise ValueError("recalc_bars must be >= 1")
        if time_stop_bars <= 0:
            raise ValueError("time_stop_bars must be > 0")
        self.entry_prob = entry_prob
        self.seed = seed
        self.zigzag_size = zigzag_size
        self.max_legs = max_legs
        self.recalc_bars = recalc_bars
        self.time_stop_bars = time_stop_bars
        self.target_window = target_window
        self.n_bins = n_bins
        self.target_min_frac = target_min_frac
        self.target_min_dist_frac = target_min_dist_frac
        self._zs = ZsTpSl(
            sl_mult=sl_mult,
            alpha=zs_alpha,
            min_legs=zs_min_legs,
            fallback_pct=zs_fallback_pct,
            max_bars=time_stop_bars,
            winsorize_k=winsorize_k,
        )
        self.required_indicators = []
        self.warmup = max(target_window, zigzag_size * (max_legs + 2)) + 2
        self.max_buffer = self.warmup + 2
        # Per-position ratchet state, keyed by (entry_idx, side) — unique per
        # position and cleared each run. NOT id(pos): CPython reuses freed object
        # addresses, so a recycled id would leak a dead position's stop into a new
        # one (fake same-price exits).
        self._stop: dict[tuple[int, Side], float | None] = {}
        self._last_recalc: dict[tuple[int, Side], int] = {}

    def reset(self) -> None:  # noqa: D102 (override)
        super().reset()
        self._stop.clear()
        self._last_recalc.clear()

    def _legs(self, peak_idx: list[int], peak_price: list[float], t: int) -> tuple[float, ...]:
        """Recent zigzag leg sizes (price units, oldest-first) confirmable by ``t``."""
        prices = [
            peak_price[k]
            for k in range(len(peak_idx))
            if peak_idx[k] + self.zigzag_size <= t
        ]
        if len(prices) < 2:
            return ()
        recent = prices[-(self.max_legs + 1) :]
        legs = tuple(abs(recent[k + 1] - recent[k]) for k in range(len(recent) - 1))
        return legs

    def precompute_multi(self, bars: list[Bar]) -> dict[datetime, list[Signal]] | None:  # noqa: D102
        if not bars:
            return {}
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        closes = [b.close for b in bars]
        peaks = detect_peaks(highs, lows, size=self.zigzag_size)
        peak_idx = [p.bar_index for p in peaks]
        peak_price = [p.price for p in peaks]
        rng = np.random.default_rng(self.seed)
        out: dict[datetime, list[Signal]] = {}
        for t in range(self.warmup, len(bars)):
            if rng.random() >= self.entry_prob:
                continue
            entry = closes[t]
            legs = self._legs(peak_idx, peak_price, t)
            ctx = ExitContext(side=Side.LONG, entry_price=entry, zs_history=legs)
            band = self._zs.band(ctx)
            sl_abs = self._zs.exit_config(ctx).sl_abs
            ts = bars[t].timestamp
            pair: list[Signal] = []
            for side in (Side.LONG, Side.SHORT):
                target = _next_dense(
                    highs, lows, t, entry, side,
                    target_window=self.target_window, n_bins=self.n_bins,
                    min_frac=self.target_min_frac,
                    min_dist=self.target_min_dist_frac * band,
                )
                cfg = ExitConfig(
                    sl_abs=sl_abs,
                    tp_abs=abs(target - entry) if target is not None else None,
                    time_stop_bars=self.time_stop_bars,
                )
                pair.append(
                    Signal(
                        side=side,
                        timestamp=ts,
                        price=entry,
                        score=1.0,
                        reason=self.name,
                        ref_time=ts,
                        ref_price=target,
                        exit_config=cfg,
                    )
                )
            out[ts] = pair
        return out

    def dynamic_exit(
        self, pos: OpenPosition, bar: Bar, i: int, entry_idx: int
    ) -> tuple[ExitReason, float] | None:  # noqa: D102 (inherited)
        # Periodic ratchet. CAUSALITY: the breach is checked against the stop set
        # on a PRIOR bar, THEN the stop is recomputed (using favorable_extreme
        # through this bar) for FUTURE bars only. Checking the freshly-tightened
        # stop on the same bar whose high set it would book the bar's own range as
        # profit on both legs = look-ahead. The band is the original zs SL distance
        # (entry -> initial sl_price); evaluate_exit ignores pos.sl_price, so we own
        # the trailing check.
        key = (entry_idx, pos.side)
        if key not in self._stop:
            self._stop[key] = pos.sl_price
            self._last_recalc[key] = i
        long = pos.side is Side.LONG

        # 1. Breach check against the prior-bar stop (causal).
        stop = self._stop[key]
        if stop is not None and (
            (long and bar.low <= stop) or (not long and bar.high >= stop)
        ):
            return ExitReason.TRAIL_STOP, stop

        # 2. Periodic recompute for subsequent bars (never loosened).
        if pos.sl_price is None:
            return None
        band = abs(pos.entry_price - pos.sl_price)
        if band > 0.0 and i - self._last_recalc[key] >= self.recalc_bars:
            self._last_recalc[key] = i
            fe = pos.favorable_extreme
            winning = fe > pos.entry_price if long else fe < pos.entry_price
            if winning:
                new_stop = fe - band if long else fe + band
                cur = self._stop[key]
                if cur is None or (long and new_stop > cur) or (not long and new_stop < cur):
                    self._stop[key] = new_stop
        return None

    def on_bar(self, bar: Bar) -> Signal | None:  # noqa: D102 (inherited)
        return None  # entries come from precompute_multi via the MultiSimulator

    def get_exit_rules(self) -> ExitConfig:  # noqa: D102 (inherited)
        return ExitConfig(time_stop_bars=self.time_stop_bars)
