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
        max_atr_rank: float | None = None,
        atr_rank_window: int = 500,
        max_chop_rank: float | None = None,
        chop_window: int = 14,
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
            max_atr_rank: If set, skip entries whose causal ATR(14) trailing
                percentile rank is >= this (drop high-volatility bars — the only
                robust *bad-entry* signature found for the hedged pair; see
                ``random_hedge_badentry_probe``). ``None`` = no filter (baseline).
            atr_rank_window: Trailing-bar window for the ATR percentile rank.
            max_chop_rank: If set, skip entries whose causal Choppiness-Index
                trailing percentile rank is >= this (drop sideways/whippy bars).
                Choppiness is an *ATR-independent* per-trade predictor (it still
                separates pair winners/losers after the ATR-Q4 cut), but the
                filter does NOT improve the portfolio equity Sharpe — the removed
                trades are only mildly negative and the lost diversification
                outweighs them (a per-trade-signal ≠ portfolio-metric case; see
                ``random_hedge_badentry_probe`` and the strategy doc §6). Kept as
                a research lever, off by default.
            chop_window: Lookback for the Choppiness Index (and its rank window).

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
        if max_atr_rank is not None and not 0.0 < max_atr_rank <= 1.0:
            raise ValueError("max_atr_rank must be in (0, 1]")
        self.max_atr_rank = max_atr_rank
        self.atr_rank_window = atr_rank_window
        if max_chop_rank is not None and not 0.0 < max_chop_rank <= 1.0:
            raise ValueError("max_chop_rank must be in (0, 1]")
        self.max_chop_rank = max_chop_rank
        self.chop_window = chop_window
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

    @staticmethod
    def _atr_series(
        highs: list[float], lows: list[float], closes: list[float], period: int = 14
    ) -> list[float]:
        """Causal ATR(14) over the full series (for the volatility bad-entry gate)."""
        import pandas as pd

        from src.indicators import atr

        df = pd.DataFrame({"high": highs, "low": lows, "close": closes})
        return [float(v) for v in atr(df, period).to_numpy()]

    @staticmethod
    def _chop_series(
        highs: list[float], lows: list[float], closes: list[float], window: int
    ) -> list[float]:
        """Causal Choppiness Index: 100·log10(ΣTR / range) / log10(window).

        High = sideways/choppy (a hedged pair gets whipsawed); low = trending.
        """
        import numpy as np
        import pandas as pd

        h, low, c = pd.Series(highs), pd.Series(lows), pd.Series(closes)
        prev = c.shift(1)
        tr = pd.concat([h - low, (h - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
        rng = (h.rolling(window).max() - low.rolling(window).min()).replace(0.0, np.nan)
        chop = 100.0 * np.log10(tr.rolling(window).sum() / rng) / np.log10(window)
        return [float(v) for v in chop.to_numpy()]

    def _gate_ok(
        self, t: int, atr_s: list[float] | None, chop_s: list[float] | None
    ) -> bool:
        """Bad-entry gates: reject high-volatility and/or sideways bars (causal)."""
        if atr_s is not None and self.max_atr_rank is not None:
            w = atr_s[max(0, t - self.atr_rank_window) : t + 1]
            if w and not np.isnan(atr_s[t]):
                rank = float(np.mean([v <= atr_s[t] for v in w if not np.isnan(v)]))
                if rank >= self.max_atr_rank:
                    return False
        if chop_s is not None and self.max_chop_rank is not None:
            w = chop_s[max(0, t - self.atr_rank_window) : t + 1]
            vals = [v for v in w if not np.isnan(v)]
            if vals and not np.isnan(chop_s[t]):
                rank = float(np.mean([v <= chop_s[t] for v in vals]))
                if rank >= self.max_chop_rank:
                    return False
        return True

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
        atr_s = self._atr_series(highs, lows, closes) if self.max_atr_rank is not None else None
        chop_s = (
            self._chop_series(highs, lows, closes, self.chop_window)
            if self.max_chop_rank is not None
            else None
        )
        rng = np.random.default_rng(self.seed)
        out: dict[datetime, list[Signal]] = {}
        for t in range(self.warmup, len(bars)):
            if rng.random() >= self.entry_prob:
                continue
            if not self._gate_ok(t, atr_s, chop_s):
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


class RandomHedgeVolfilterStrategy(RandomHedgeStrategy):
    """``random_hedge`` minus its one robust bad entry: high-volatility bars.

    The bad-entry probe found that a hedged pair LOSES when entered at high
    realized volatility (ATR top quartile) — both legs get whipsawed out — and
    this is the *only* context that is net-negative in BOTH the IS and OOS splits
    (the density_multi "low vol loses" finding is inverted for a neutral pair).
    Dropping just that quartile (``max_atr_rank=0.75``) turns the random null
    baseline from IS eqSharpe −0.35 to +0.34 (7/8 seeds improve) and halves the
    drawdown — a robust *bad-entry* gate, not a directional entry. Tighter cuts
    raise IS but overfit (OOS collapses), so the gentle Q4-only cut is the
    pre-registered setting. See ``random_hedge_badentry_probe``.
    """

    name = "random_hedge_volfilter"
    description = (
        "random_hedge with the one robust bad-entry removed: skip high-volatility "
        "(ATR top-quartile) bars, where a hedged pair gets both legs whipsawed."
    )

    def __init__(self, **kwargs: object) -> None:
        """Initialise with the Q4-ATR bad-entry gate + the walk-forward sweet-spot exit.

        Defaults: the ATR-Q4 bad-entry gate (``max_atr_rank=0.75``) plus the tuned
        exit (``recalc_bars=48``, ``sl_mult=0.75``, ``time_stop_bars=120``) — a slow
        ratchet with a tight stop that lets winners run. This config is 8-seed IS
        eqSharpe **+0.90** / OOS **+1.02** (vs B&H +0.64), 8/8 IS positive; both
        exit levers are confirmed out-of-sample on `density_pullback`
        (`density_pullback_exit_wf` — rc48 in every anchored fold, sl0.75 positive in
        6/6). All overridable.
        """
        kwargs.setdefault("max_atr_rank", 0.75)
        kwargs.setdefault("recalc_bars", 48)
        kwargs.setdefault("sl_mult", 0.75)
        super().__init__(**kwargs)  # type: ignore[arg-type]
