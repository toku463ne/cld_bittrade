"""Strategy: density_pullback — directional pullback entry on a dense breakout.

The momentum counterpart to ``random_hedge_density`` (which faded the box and was
rejected). Same question — does a *better-priced* entry lift the random_hedge exit
framework? — but the opposite sign: instead of fading, ride *with* a real
directional signal and just wait for a better fill.

Entry: the ``density_multi_breakout`` signal (price consolidates in the tight
~1-week value-area box, then closes through an edge → LONG on a top break, SHORT on
a bottom break). Rather than enter at the breakout close, rest a **limit at the
broken edge** (a genuine concession — for a LONG the edge is below the breakout
close, for a SHORT above) and fill only if price **pulls back** to it within
``limit_window`` bars, else cancel. So it buys the retest of broken resistance /
sells the retest of broken support — a momentum-with-pullback entry.

The exit is the random_hedge framework, unchanged (zs-band SL + next-dense TP +
periodic ratchet), so the only variable vs the random baseline is the entry — the
lift is the "is a better-priced directional entry worth anything?" measurement.
``pullback=False`` enters at the breakout close (market) instead, as the control
that isolates the price-improvement from the directional signal itself.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from src.core.types import Bar, ExitConfig, ExitReason, Side, Signal
from src.exit.base import ExitContext
from src.exit.rules import OpenPosition
from src.indicators.density import time_at_price_profile, value_area
from src.strategy.density_multi_breakout import _next_dense, _rolling_bands
from src.strategy.random_hedge import RandomHedgeStrategy


def _recency_weights(window: int, strength: float) -> NDArray[np.float64]:
    """Per-bar weights over a trailing window (index 0 = oldest, -1 = newest).

    Log-shaped recency ramp: the most-recent bar gets ``1 + strength`` times the
    weight of the oldest, and the lift falls off as ``log1p(age)`` so the boost
    is concentrated on the last fraction of the window while older bars decay
    *gently* toward the ``1.0`` baseline (never to zero) — a bar from 3-5 days
    ago still carries most of its weight. ``strength <= 0`` -> uniform (the plain
    time-equal profile).
    """
    if strength <= 0.0:
        return np.ones(window, dtype=np.float64)
    pos = np.arange(window, dtype=np.float64)  # 0 = oldest ... window-1 = newest
    age = (window - 1) - pos  # 0 = newest ... window-1 = oldest
    lift = 1.0 - np.log1p(age) / np.log1p(window - 1)  # 1 at newest, 0 at oldest
    out: NDArray[np.float64] = 1.0 + strength * lift
    return out


def _rolling_bands_recency(
    highs: list[float],
    lows: list[float],
    window: int,
    n_bins: int,
    coverage: float,
    recency: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Like :func:`_rolling_bands` but tilts each window by a recency ramp."""
    n = len(highs)
    bl = np.full(n, np.nan)
    bh = np.full(n, np.nan)
    w = _recency_weights(window, recency)
    for t in range(window, n):
        centers, weights = time_at_price_profile(
            highs[t - window : t], lows[t - window : t], n_bins, weights=w
        )
        _poc, lo, hi = value_area(centers, weights, coverage)
        if hi > lo:
            bl[t] = lo
            bh[t] = hi
    return bl, bh


class DensityPullbackStrategy(RandomHedgeStrategy):
    """Dense-breakout direction, entered on a limit pullback to the broken edge."""

    name = "density_pullback"
    description = (
        "Directional pullback: on a dense-box breakout, rest a limit at the broken "
        "edge and fill on the retest (buy broken resistance / sell broken support); "
        "same zs SL + next-dense TP + ratchet exit. Lift over random_hedge."
    )
    # Concurrency cap. The observed peak overlap is 10 (max_slots>=10 are identical
    # on every metric — the overlapping entries are additive edge, not redundancy,
    # see the knob history); 12 leaves headroom over that peak while making a live
    # budget a hard guarantee (peak exposure = max_slots * per-slot lot). Backtest
    # unchanged vs the inherited 50.
    max_slots = 12

    def __init__(
        self,
        *,
        window: int = 168,
        density_bins: int = 48,
        coverage: float = 0.70,
        max_band_pct: float = 0.03,
        limit_window: int = 6,
        pullback: bool = True,
        breakout_k: float = 0.0,
        recency: float = 1.0,
        accept_band: float | None = None,
        invalidation_depth: float | None = None,
        **kwargs: object,
    ) -> None:
        """Initialise.

        Args:
            window: Trailing bars for the value-area box (168 = ~1 week on 1h).
            density_bins: Histogram bins for the box profile.
            coverage: Value-area coverage fraction (0.70 standard).
            max_band_pct: Tight-box filter — fire only when box height <= this
                fraction of price.
            limit_window: Bars the pullback limit rests before cancellation. Kept
                short (6 = ~6h on 1h) so the fill is a *prompt* retest: a limit that
                rests ~a day (24) catches delayed reversals that crash back through
                the edge — a different trade, not a breakout retest (swept 3/6/12/
                18/24/36 → 6 is the balance: best IS Sharpe, 6/6 folds, OOS held).
            pullback: If True, enter via a limit at the broken edge (retest); if
                False, enter at the breakout close (market) — the control.
            breakout_k: Breakout-extent gate. The breakout close must clear the
                broken edge by at least ``breakout_k * (hi - lo)`` (a fraction of
                the box height), so a marginal close just past the lip does not
                qualify. ``0.0`` (default) recovers the bare ``close > hi`` test.
            recency: Log recency tilt on the value-area box (see
                :func:`_recency_weights`). ``0.0`` (default) = time-equal box.
            accept_band: Causal acceptance-band confirmation entry (replaces the
                passive-limit fill when set, with ``pullback=True``). After a
                breakout, wait up to ``limit_window`` bars for a bar that *closes*
                back into the band ``[hi - accept_band*(hi-lo), hi]`` (long) — a
                controlled pullback — then enter **market at the next bar's open**.
                If a bar first closes *below* the floor, the retest has failed and
                the setup is cancelled. No intrabar look-ahead (decisions on
                closes, fills at next open). ``None`` (default) = passive limit at
                the edge.
            invalidation_depth: Failed-breakout invalidation exit. If set, a
                position exits (at the close, via ``dynamic_exit``) when a bar
                **closes** back inside the value area by more than this fraction of
                the box height from the broken edge — for a LONG, ``close <
                hi − depth·(hi−lo)``; for a SHORT, ``close > lo + depth·(hi−lo)``.
                The hypothesis was that the breakout thesis is structurally dead
                once price is re-accepted inside the box, cutting the loser before
                the (generic) zs-band stop fires. The level is frozen from the
                signal-time box. ``None`` (default) = off, exit framework
                unchanged. Books as ``STOP_LOSS``. **Tested and REJECTED** — at
                depth >= 1.0 the zs stop always fires first (literal no-op);
                shallower depths clip the dip-then-run trail winners without
                cutting the stop bleed (see the 2026-06-10 knob history below).
            **kwargs: Forwarded to :class:`RandomHedgeStrategy` (exit params, the
                bad-entry gates, ...). ``entry_prob`` is unused (entries are the
                breakouts, not random).

        Raises:
            ValueError: On out-of-range parameters.
        """
        kwargs.setdefault("recalc_bars", 48)  # walk-forward sweet-spot exit (see §3/§4)
        kwargs.setdefault("sl_mult", 0.75)  # one-knob WF: tightest robust stop (6/6 folds)
        super().__init__(**kwargs)  # type: ignore[arg-type]
        if window < 2:
            raise ValueError("window must be >= 2")
        if max_band_pct <= 0.0:
            raise ValueError("max_band_pct must be > 0")
        if limit_window < 1:
            raise ValueError("limit_window must be >= 1")
        if breakout_k < 0.0:
            raise ValueError("breakout_k must be >= 0")
        if recency < 0.0:
            raise ValueError("recency must be >= 0")
        if accept_band is not None and accept_band <= 0.0:
            raise ValueError("accept_band must be > 0 or None")
        if invalidation_depth is not None and invalidation_depth <= 0.0:
            raise ValueError("invalidation_depth must be > 0 or None")
        self.invalidation_depth = invalidation_depth
        self.accept_band = accept_band
        self.window = window
        self.density_bins = density_bins
        self.coverage = coverage
        self.max_band_pct = max_band_pct
        self.limit_window = limit_window
        self.pullback = pullback
        self.breakout_k = breakout_k
        self.recency = recency
        self.warmup = max(self.warmup, window + 2)
        self.max_buffer = self.warmup + 2

    def precompute_multi(self, bars: list[Bar]) -> dict[datetime, list[Signal]] | None:  # noqa: D102
        if not bars:
            return {}
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        closes = [b.close for b in bars]
        from src.indicators.zigzag import detect_peaks

        peaks = detect_peaks(highs, lows, size=self.zigzag_size)
        peak_idx = [p.bar_index for p in peaks]
        peak_price = [p.price for p in peaks]
        atr_s = self._atr_series(highs, lows, closes) if self.max_atr_rank is not None else None
        chop_s = (
            self._chop_series(highs, lows, closes, self.chop_window)
            if self.max_chop_rank is not None
            else None
        )
        if self.recency > 0.0:
            band_lo, band_hi = _rolling_bands_recency(
                highs, lows, self.window, self.density_bins, self.coverage, self.recency
            )
        else:
            band_lo, band_hi = _rolling_bands(
                highs, lows, self.window, self.density_bins, self.coverage
            )
        self._ensure_trend(bars)

        out: dict[datetime, list[Signal]] = {}
        for t in range(self.warmup, len(bars)):
            lo, hi = float(band_lo[t]), float(band_hi[t])
            if not (hi > lo):
                continue
            prev = closes[t - 1]
            if not (lo <= prev <= hi):
                continue
            c = closes[t]
            if (hi - lo) > self.max_band_pct * c:
                continue
            # Breakout-extent gate: the close must clear the broken edge by at
            # least breakout_k of the box height (k=0 -> bare close-through).
            margin = self.breakout_k * (hi - lo)
            if c - hi > margin:
                side, near = Side.LONG, hi
            elif lo - c > margin:
                side, near = Side.SHORT, lo
            else:
                continue
            if not self._gate_ok(t, atr_s, chop_s):
                continue
            if not self._trend_ok(side, t):
                continue

            # Causal acceptance-band confirmation: wait for a bar to CLOSE back into
            # [floor, hi] (long) / [lo, ceil] (short) — a controlled pullback — then
            # enter market at the next open. A close past the floor/ceil first =
            # failed retest, skip. No look-ahead (decision on closes, fill next bar).
            entry_bar = t  # bar whose close the entry signal is read from
            if self.pullback and self.accept_band is not None:
                depth = self.accept_band * (hi - lo)
                floor, ceil = hi - depth, lo + depth
                conf: int | None = None
                for j in range(t + 1, min(t + 1 + self.limit_window, len(bars))):
                    cj = closes[j]
                    if side is Side.LONG:
                        if cj < floor:
                            break  # pulled back too far — failed retest
                        if cj <= hi:
                            conf = j  # closed back into the acceptance band
                            break
                    else:
                        if cj > ceil:
                            break
                        if cj >= lo:
                            conf = j
                            break
                if conf is None:
                    continue  # no controlled pullback within the window — no trade
                entry_bar = conf

            entry_ref = near if self.pullback else c  # the price the trade is built around
            legs = self._legs(peak_idx, peak_price, t)
            ctx = ExitContext(side=side, entry_price=entry_ref, zs_history=legs)
            band = self._zs.band(ctx)
            sl_abs = self._zs.exit_config(ctx).sl_abs
            target = _next_dense(
                highs, lows, t, entry_ref, side,
                target_window=self.target_window, n_bins=self.n_bins,
                min_frac=self.target_min_frac, min_dist=self.target_min_dist_frac * band,
            )
            cfg = ExitConfig(
                sl_abs=sl_abs,
                tp_abs=abs(target - entry_ref) if target is not None else None,
                time_stop_bars=self.time_stop_bars,
            )
            # Failed-breakout invalidation level, frozen from the signal-time box;
            # carried on ref2_price -> OpenPosition for the dynamic_exit check.
            inval: float | None = None
            if self.invalidation_depth is not None:
                depth_abs = self.invalidation_depth * (hi - lo)
                inval = (hi - depth_abs) if side is Side.LONG else (lo + depth_abs)
            # Confirmation mode enters market at entry_bar+1 open (limit_price=None);
            # passive-limit mode rests a limit at the edge; market mode fills next open.
            confirm = self.pullback and self.accept_band is not None
            ts = bars[entry_bar].timestamp
            out.setdefault(ts, []).append(
                Signal(
                    side=side,
                    timestamp=ts,
                    price=entry_ref,
                    score=1.0,
                    reason=self.name,
                    ref_time=bars[t].timestamp,
                    ref_price=target,
                    ref2_time=bars[t].timestamp if inval is not None else None,
                    ref2_price=inval,
                    exit_config=cfg,
                    limit_price=near if (self.pullback and not confirm) else None,
                    limit_expiry_bars=self.limit_window if (self.pullback and not confirm) else 0,
                )
            )
        return out

    def dynamic_exit(
        self, pos: OpenPosition, bar: Bar, i: int, entry_idx: int
    ) -> tuple[ExitReason, float] | None:  # noqa: D102 (inherited)
        # Ratchet / trail breach first (the inherited exit framework, unchanged).
        res = super().dynamic_exit(pos, bar, i, entry_idx)
        if res is not None:
            return res
        # Failed-breakout invalidation: a CLOSE re-accepted inside the box beyond
        # the frozen level kills the thesis -> exit at the close (the decision uses
        # only this bar's close; same fill convention as the density stall exit).
        if self.invalidation_depth is None or pos.ref2_price is None:
            return None
        c = bar.close
        if pos.side is Side.LONG and c < pos.ref2_price:
            return ExitReason.STOP_LOSS, c
        if pos.side is Side.SHORT and c > pos.ref2_price:
            return ExitReason.STOP_LOSS, c
        return None


# Knob history (2026-06-08):
#   * limit_window — bars the retest limit rests — cut 24 -> 6. At 24 (~1 day) the
#     limit caught delayed reversals crashing back through the edge (falling-knife
#     fills, e.g. the 2026-05-15 22:00 trade: filled 23 bars after breakout into a
#     1-bar -2% crash, instant stop). Swept 3/6/12/18/24/36; 6 is the balance —
#     best IS Sharpe (1.74->1.81), 6/6 folds, OOS held, fewer losers. Longer windows
#     lift OOS a touch but at lower IS and admit the stale knife-catches.
#   * recency — log recency-weighted value-area box — is now ON BY DEFAULT
#     (recency=1.0). Walk-forward-robust improvement over the old time-equal box
#     (positive in all 6 folds, beats B&H 5/6 vs 4/6; lockbox IS eqSharpe
#     1.39->1.74, IS DD 0.34->0.28, OOS 1.11->1.27). recency=0.0 recovers the old
#     time-equal box (the control). Sweep 1.0/2.0/3.0 -> 1.0 best.
#   * breakout_k — breakout-extent gate — was swept (0.10/0.15/0.25) and DROPPED:
#     non-monotonic, no edge gain over baseline. The knob stays (no-op at 0.0) for
#     future sweeps; no registered variant uses it.
#   * accept_band — causal acceptance-band CONFIRMATION entry (wait for an in-band
#     close, enter next open) — was built to test "blocking too-deep pullbacks cuts
#     losers". REJECTED: a *look-ahead* version (cancel a limit that the touch bar
#     pierces past) showed a monotone win, but the realizable causal version is
#     STRICTLY WORSE than the baseline passive limit (lockbox IS_sh 1.74->~1.2,
#     OOS 1.27->0.5-0.8, OOS@10bp 1.08->0.3-0.6, folds 6/6->4-5/6). The passive
#     limit fills precisely at the edge and catches fast retests the confirmation
#     misses; the look-ahead "win" was the artifact. Knob stays (no-op at None) as
#     the documented rejected control.
# Knob history (2026-06-10):
#   * invalidation_depth — failed-breakout invalidation exit (close re-accepted
#     inside the box beyond depth x box-height -> exit at close, before the zs
#     stop) — swept 0.25/0.5/0.75/1.0/1.25 + 6-fold WF. REJECTED: at depth >= 1.0
#     it is a literal no-op (the zs 0.75-band stop always fires first); everywhere
#     it acts (< 1.0) it is neutral-to-worse (WF mean 1.18 -> 1.05/0.92/1.14,
#     folds 6/6 -> 5/6 at 0.25/0.5, fold f2 flips negative) and the mechanism
#     evidence contradicts the hypothesis: the stop BLEED barely moves (-3.28 ->
#     -3.30; -2.61 only at 0.25) while trail winners are converted into stops
#     (IS trail 143 -> 95 at 0.25) — the dip-then-run winners ARE the trades that
#     close back inside the box. depth=0.5's 80/20-OOS bump (+0.95 -> +1.13) is a
#     single-split artifact contradicted by its WORST-of-sweep WF mean (+0.92).
#     Knob stays (no-op at None) as the documented rejected control. Harness:
#     src/backtest/analysis/density_pullback_invalidation_ab.py.
