"""Strategy: zigzag_bounce_ride — zigzag-bounce entry, tuned ride exit.

`zigzag_bounce` is a REJECT under its own ZS fixed TP/SL exit (IS Sharpe −0.10 /
OOS −0.05, single position). This asks the `density_pullback` question of it: does
the bounce *direction* carry an edge once it is fed into the **tuned ride exit**
framework instead — multi-position, a next-dense take-profit, a zs-band stop, and
the slow ratchet (`sl_mult=0.75, recalc_bars=48, time_stop_bars=120`) that the
walk-forward settled on `density_pullback`?

Entry: every `ZigzagBounceSign` fire (a reaction off a recent swing level / wall),
direction unchanged. With ``pullback=False`` it fills at market (next open) — the
control; with ``pullback=True`` it rests a limit at the bounce's reference level
(buy the retest of support / sell the retest of resistance) when that is a genuine
concession, else falls back to market. The exit machinery is inherited from
:class:`~src.strategy.random_hedge.RandomHedgeStrategy` unchanged, so the result is
read as **lift over the random-entry null baseline** in the same exit.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from src.core.types import Bar, ExitConfig, Side, Signal
from src.exit.base import ExitContext
from src.signs.zigzag_bounce import ZigzagBounceSign
from src.strategy.density_multi_breakout import _next_dense
from src.strategy.random_hedge import RandomHedgeStrategy


class ZigzagBounceRideStrategy(RandomHedgeStrategy):
    """Zigzag-bounce direction fed into the tuned next-dense / ratchet ride exit."""

    name = "zigzag_bounce_ride"
    description = (
        "Zigzag-bounce entry (reaction off a recent swing/wall) routed into the "
        "tuned ride exit: zs SL + next-dense TP + slow ratchet, multi-position. "
        "Tests whether the bounce direction carries edge once the exit is swapped."
    )

    def __init__(
        self,
        *,
        size: int = 10,
        mid_size: int = 3,
        windows: tuple[int, ...] = (60, 120, 180),
        tol_pct: float = 0.005,
        wall_match: bool = True,
        wall_window: int | None = 120,
        reject_past_peak: bool = True,
        pullback: bool = False,
        limit_window: int = 24,
        **kwargs: object,
    ) -> None:
        """Initialise.

        Args:
            size: Zigzag peak half-width (the sign's swing definition).
            mid_size: Early-peak half-width (right-edge confirmation).
            windows: Trailing windows the sign scans for a matching swing level.
            tol_pct: Price tolerance for matching the early peak to a level.
            wall_match: Match the early peak to the nearest-in-price confirmed peak
                (the benchmark default).
            wall_window: Lookback for the wall match.
            reject_past_peak: Drop fires that chase past the matched level.
            pullback: If True, enter via a limit at the bounce's reference level
                (retest); else market (next open) — the control.
            limit_window: Bars a pullback limit rests before cancellation.
            **kwargs: Forwarded to :class:`RandomHedgeStrategy` (the tuned exit
                params + the bad-entry gates). ``entry_prob`` is unused.

        Raises:
            ValueError: On out-of-range parameters (via the parent / the sign).
        """
        kwargs.setdefault("recalc_bars", 48)  # tuned ride exit (density_pullback WF)
        kwargs.setdefault("sl_mult", 0.75)
        super().__init__(**kwargs)  # type: ignore[arg-type]
        if limit_window < 1:
            raise ValueError("limit_window must be >= 1")
        self._sign = ZigzagBounceSign(
            size=size, mid_size=mid_size, windows=windows, tol_pct=tol_pct,
            wall_match=wall_match, wall_window=wall_window, reject_past_peak=reject_past_peak,
        )
        self.pullback = pullback
        self.limit_window = limit_window
        self.warmup = max(self.warmup, self._sign.window)
        self.max_buffer = self.warmup + 2

    def precompute_multi(self, bars: list[Bar]) -> dict[datetime, list[Signal]] | None:  # noqa: D102
        if not bars:
            return {}
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        closes = [b.close for b in bars]
        df = pd.DataFrame(
            {
                "open": [b.open for b in bars],
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": [b.volume for b in bars],
            },
            index=pd.DatetimeIndex([b.timestamp for b in bars]),
        )
        fires = self._sign.detect(df)
        atr_s = self._atr_series(highs, lows, closes) if self.max_atr_rank is not None else None
        chop_s = (
            self._chop_series(highs, lows, closes, self.chop_window)
            if self.max_chop_rank is not None
            else None
        )
        ts_to_idx = {ts: i for i, ts in enumerate(df.index)}

        out: dict[datetime, list[Signal]] = {}
        for f in fires:
            t = ts_to_idx.get(pd.Timestamp(f.fired_at))
            if t is None or t < self.warmup:
                continue
            if not self._gate_ok(t, atr_s, chop_s):
                continue
            entry = f.price
            ctx = ExitContext(side=f.side, entry_price=entry, zs_history=f.legs)
            band = self._zs.band(ctx)
            sl_abs = self._zs.exit_config(ctx).sl_abs

            # Optional limit at the bounce's reference level (retest), only when it
            # is a genuine concession; otherwise enter at market.
            limit = None
            if self.pullback and f.ref_price is not None and (
                (f.side is Side.LONG and f.ref_price < entry)
                or (f.side is Side.SHORT and f.ref_price > entry)
            ):
                limit = f.ref_price
            ref = limit if limit is not None else entry

            target = _next_dense(
                highs, lows, t, ref, f.side,
                target_window=self.target_window, n_bins=self.n_bins,
                min_frac=self.target_min_frac, min_dist=self.target_min_dist_frac * band,
            )
            cfg = ExitConfig(
                sl_abs=sl_abs,
                tp_abs=abs(target - ref) if target is not None else None,
                time_stop_bars=self.time_stop_bars,
            )
            out[f.fired_at] = [
                Signal(
                    side=f.side,
                    timestamp=f.fired_at,
                    price=ref,
                    score=1.0,
                    reason=self.name,
                    ref_time=f.fired_at,
                    ref_price=target,
                    exit_config=cfg,
                    limit_price=limit,
                    limit_expiry_bars=self.limit_window if limit is not None else 0,
                )
            ]
        return out
