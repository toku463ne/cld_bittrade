"""Strategy: random_hedge_density — better-priced (density-edge) limit entries.

The payoff step of the random_hedge arc. ``random_hedge`` proved the EXIT (zs SL +
next-dense TP + ratchet) cannot make edge from a *random, market-priced* entry, and
the bad-entry probe showed the only shippable entry lever is a *risk* gate (skip
high vol). This strategy keeps that exact exit framework but replaces the random
**market** fill with a **better-priced limit** fill, then measures the lift over
the random null baseline.

On a random bar it places, instead of a market pair:

- a **buy-limit at the value-area LOW** (dense support), and
- a **sell-limit at the value-area HIGH** (dense resistance),

each resting for ``limit_window`` bars and filling only if price trades to it (else
cancelled). A leg is placed only when its limit is a genuine concession (long limit
below the close, short limit above) — never marketable. So the pair "fades the box
edges": buy support / sell resistance, with the exit's next-dense TP naturally
becoming the *other* side of the range. It is therefore a **mean-reversion** entry
(wins in ranges, gives a leg back on breakouts), judged by the mark-to-market
equity Sharpe vs the random-entry baseline.

The entry-pricing is the only change; SL band, dense TP and the ratchet are
inherited from :class:`~src.strategy.random_hedge.RandomHedgeStrategy` unchanged.
The volatility / choppiness bad-entry gates (``max_atr_rank`` / ``max_chop_rank``)
still apply to the random fire decision.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from src.core.types import Bar, ExitConfig, Side, Signal
from src.exit.base import ExitContext
from src.indicators.density import time_at_price_profile, value_area
from src.indicators.zigzag import detect_peaks
from src.strategy.density_multi_breakout import _next_dense
from src.strategy.random_hedge import RandomHedgeStrategy


class RandomHedgeDensityStrategy(RandomHedgeStrategy):
    """Random-bar hedged pair, but each leg enters via a density-edge limit order."""

    name = "random_hedge_density"
    description = (
        "Better-priced entry test: on random bars rest a buy-limit at the "
        "value-area low and a sell-limit at the value-area high (fade the box "
        "edges); same zs SL + next-dense TP + ratchet exit. Lift over random_hedge."
    )

    def __init__(
        self,
        *,
        va_window: int = 168,
        va_bins: int = 48,
        va_coverage: float = 0.70,
        limit_window: int = 24,
        **kwargs: object,
    ) -> None:
        """Initialise.

        Args:
            va_window: Trailing bars for the value-area (entry) profile.
            va_bins: Histogram bins for that profile.
            va_coverage: Value-area coverage fraction (market-profile default 0.70).
            limit_window: Bars a resting limit order stays working before cancel.
            **kwargs: Forwarded to :class:`RandomHedgeStrategy` (entry_prob, seed,
                exit params, the bad-entry gates, ...).

        Raises:
            ValueError: On out-of-range parameters.
        """
        super().__init__(**kwargs)  # type: ignore[arg-type]
        if va_window < 2:
            raise ValueError("va_window must be >= 2")
        if limit_window < 1:
            raise ValueError("limit_window must be >= 1")
        self.va_window = va_window
        self.va_bins = va_bins
        self.va_coverage = va_coverage
        self.limit_window = limit_window
        self.warmup = max(self.warmup, va_window + 1)
        self.max_buffer = self.warmup + 2

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
            close = closes[t]
            # Value area over the trailing window [t-va_window, t-1] (causal).
            centers, weights = time_at_price_profile(
                highs[t - self.va_window : t], lows[t - self.va_window : t], self.va_bins
            )
            _poc, va_lo, va_hi = value_area(centers, weights, self.va_coverage)

            legs = self._legs(peak_idx, peak_price, t)
            ctx = ExitContext(side=Side.LONG, entry_price=close, zs_history=legs)
            band = self._zs.band(ctx)
            sl_abs = self._zs.exit_config(ctx).sl_abs
            ts = bars[t].timestamp

            pair: list[Signal] = []
            # Long leg: buy support, but only as a genuine discount (limit < close).
            if va_lo < close:
                pair.append(
                    self._limit_signal(highs, lows, t, ts, va_lo, Side.LONG, band, sl_abs)
                )
            # Short leg: sell resistance, only as a genuine premium (limit > close).
            if va_hi > close:
                pair.append(
                    self._limit_signal(highs, lows, t, ts, va_hi, Side.SHORT, band, sl_abs)
                )
            if pair:
                out[ts] = pair
        return out

    def _limit_signal(
        self,
        highs: list[float],
        lows: list[float],
        t: int,
        ts: datetime,
        limit: float,
        side: Side,
        band: float,
        sl_abs: float | None,
    ) -> Signal:
        """Build one resting-limit leg with the inherited next-dense TP / zs SL."""
        target = _next_dense(
            highs, lows, t, limit, side,
            target_window=self.target_window, n_bins=self.n_bins,
            min_frac=self.target_min_frac, min_dist=self.target_min_dist_frac * band,
        )
        cfg = ExitConfig(
            sl_abs=sl_abs,
            tp_abs=abs(target - limit) if target is not None else None,
            time_stop_bars=self.time_stop_bars,
        )
        return Signal(
            side=side,
            timestamp=ts,
            price=limit,
            score=1.0,
            reason=self.name,
            ref_time=ts,
            ref_price=target,
            exit_config=cfg,
            limit_price=limit,
            limit_expiry_bars=self.limit_window,
        )
