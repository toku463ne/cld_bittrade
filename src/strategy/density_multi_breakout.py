"""Strategy: density_multi_breakout (multi-position dense breakout).

The walk-forward-robust promotion of the research in
``src/backtest/analysis/density_multi_probe.py`` (and its walk-forward / slot
sweeps). Same dense-breakout entry as :class:`~src.strategy.density_breakout`
(price consolidates inside the ~1-week value-area box, then closes through an
edge), but built to **hold several positions at once** and to **exit into the
next dense zone**:

- **Entry** — value area over ``[t-window, t-1]`` (window=168, ~1 week on 1h);
  the prior close must be inside a *tight* box (``max_band_pct=0.03``) and this
  close must break an edge. Long on a top-edge break, short on a bottom-edge
  break. (Confirm_bars=1 equivalent — fire on the first breakout close.)
- **Exit**, whichever first:
  * far-edge **structural stop** (``sl_abs`` beyond the opposite edge + buffer);
  * dense **target** (``tp_abs``) — the next *pre-existing* heavy node beyond the
    broken edge, read from a 336-bar profile at entry ("exit into the next dense");
  * **time stop** (120 bars ≈ 5 days);
  * **stall** — a fresh tight box forms at the new level (the dynamic hook).

It declares ``max_slots = 5`` so the backtest runs through the
:class:`~src.simulator.multi_simulator.MultiSimulator` and is judged by the
annualised mark-to-market **equity Sharpe** (per-trade Sharpe understates the
diversification across overlapping slots). On 1h GMO (~5y), walk-forward across
6 folds: positive in all 6 (equity Sharpe IS +0.71 / OOS +1.36) — a modest,
regime-robust, market-neutral-ish diversifier (beats buy-and-hold in downturns,
trails it in strong bulls). See ``src/backtest/benchmark.md``.
"""

from __future__ import annotations

import numpy as np

from src.core.types import Bar, ExitConfig, ExitReason, Side, Signal
from src.exit.rules import OpenPosition
from src.indicators.density import time_at_price_profile, value_area
from src.strategy.base import Strategy


def _rolling_bands(
    highs: list[float], lows: list[float], window: int, n_bins: int, coverage: float
) -> tuple[np.ndarray, np.ndarray]:
    """Value-area band over ``[t-window, t-1]`` for each bar ``t`` (NaN if short)."""
    n = len(highs)
    bl = np.full(n, np.nan)
    bh = np.full(n, np.nan)
    for t in range(window, n):
        centers, weights = time_at_price_profile(highs[t - window : t], lows[t - window : t], n_bins)
        _poc, lo, hi = value_area(centers, weights, coverage)
        if hi > lo:
            bl[t] = lo
            bh[t] = hi
    return bl, bh


def _next_dense(
    highs: list[float],
    lows: list[float],
    e: int,
    edge: float,
    side: Side,
    *,
    target_window: int,
    n_bins: int,
    min_frac: float,
    min_dist: float = 0.0,
) -> float | None:
    """Heaviest pre-existing dense node beyond ``edge`` (the target), or ``None``.

    ``min_dist`` pushes the eligible zone past the box lip: a node must sit at
    least ``min_dist`` price units beyond the broken edge, so the target is a real
    "next" congestion rather than the top of the box just left.
    """
    w0 = max(0, e - target_window)
    if e - w0 < 10:
        return None
    centers, weights = time_at_price_profile(highs[w0:e], lows[w0:e], n_bins)
    mask = centers > edge + min_dist if side is Side.LONG else centers < edge - min_dist
    if not mask.any():
        return None
    w = weights[mask]
    peak = float(weights.max())
    if peak <= 0.0 or float(w.max()) < min_frac * peak:
        return None
    return float(centers[mask][int(w.argmax())])


class DensityMultiBreakoutStrategy(Strategy):
    """Multi-position dense breakout with dense-aware exits (5 slots)."""

    name = "density_multi_breakout"
    description = (
        "Multi-position dense-band breakout: enter on a close out of the tight "
        "value-area box, hold up to 5 overlapping slots, exit into the next "
        "pre-existing dense zone (or far-edge stop / stall / time stop)."
    )
    max_slots = 5

    def __init__(
        self,
        window: int = 168,
        n_bins: int = 48,
        coverage: float = 0.70,
        max_band_pct: float = 0.03,
        sl_buffer: float = 0.10,
        time_stop_bars: int = 120,
        min_hold: int = 6,
        target_window: int = 336,
        target_min_frac: float = 0.40,
        target_min_dist_frac: float = 1.5,
    ) -> None:
        """Initialise the strategy (defaults = the walk-forward-robust config).

        Args:
            window: Trailing bars for the value-area profile (168 = ~1 week 1h).
            n_bins: Histogram price bins.
            coverage: Value-area fraction (0.70 = standard market profile).
            max_band_pct: Tight-box filter — fire only when the box height is at
                most this fraction of price. Also gates the stall exit.
            sl_buffer: Structural stop placed this fraction of the band height
                beyond the opposite edge.
            time_stop_bars: Time-stop backstop in bars (120 ≈ 5 days on 1h).
            min_hold: Bars to hold before the stall exit may trigger.
            target_window: Trailing bars for the pre-existing dense target profile.
            target_min_frac: A target node must weigh at least this fraction of
                the profile's point-of-control to count.
            target_min_dist_frac: The target node must sit at least this fraction
                of the band height *beyond* the broken edge. ``1.5`` (default)
                skips the box lip so the target is a real next congestion — this
                is the cost-robust setting (positive IS+OOS even at a stressed
                40 bp round-trip; see ``density_multi_target_cost.py``). ``0.0``
                allows the nearest node (tiny scalps, fragile to spread).

        Raises:
            ValueError: On non-positive ``window``/``time_stop_bars`` or
                out-of-range ``coverage``/``max_band_pct``.
        """
        super().__init__()
        if window < 2:
            raise ValueError("window must be >= 2")
        if not 0.0 < coverage <= 1.0:
            raise ValueError("coverage must be in (0, 1]")
        if max_band_pct <= 0.0:
            raise ValueError("max_band_pct must be > 0")
        if time_stop_bars <= 0:
            raise ValueError("time_stop_bars must be > 0")
        self.window = window
        self.n_bins = n_bins
        self.coverage = coverage
        self.max_band_pct = max_band_pct
        self.sl_buffer = sl_buffer
        self.time_stop_bars = time_stop_bars
        self.min_hold = min_hold
        self.target_window = target_window
        self.target_min_frac = target_min_frac
        self.target_min_dist_frac = target_min_dist_frac
        self.required_indicators = [f"density_{window}_{n_bins}"]
        self.warmup = window + 2
        self.max_buffer = window + 2
        self._band_lo: np.ndarray = np.array([])
        self._band_hi: np.ndarray = np.array([])

    def _compute_bands(
        self, highs: list[float], lows: list[float]
    ) -> tuple[np.ndarray, np.ndarray]:
        """Per-bar dense band over ``[t-window, t-1]`` (the 70% value area).

        Overridable so variants can swap the band definition (e.g. the
        relative-density band) while reusing the entry/exit machinery.
        """
        return _rolling_bands(highs, lows, self.window, self.n_bins, self.coverage)

    def precompute(self, bars: list[Bar]) -> dict[object, Signal] | None:  # type: ignore[override]
        """Detect all entries over the full series and cache the rolling bands.

        The MultiSimulator looks up the returned ``{timestamp: Signal}`` map per
        bar; the cached bands feed :meth:`dynamic_exit` (the stall check).
        """
        if not bars:
            self._band_lo = self._band_hi = np.array([])
            return {}
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        closes = [b.close for b in bars]
        self._band_lo, self._band_hi = self._compute_bands(highs, lows)
        out: dict[object, Signal] = {}
        for t in range(self.window, len(bars)):
            lo, hi = float(self._band_lo[t]), float(self._band_hi[t])
            if not (hi > lo):
                continue
            prev = closes[t - 1]
            if not (lo <= prev <= hi):
                continue
            c = closes[t]
            if (hi - lo) > self.max_band_pct * c:
                continue
            if c > hi:
                side, near, far = Side.LONG, hi, lo
            elif c < lo:
                side, near, far = Side.SHORT, lo, hi
            else:
                continue
            band_h = hi - lo
            stop = far - self.sl_buffer * band_h if side is Side.LONG else far + self.sl_buffer * band_h
            target = _next_dense(
                highs, lows, t, near, side,
                target_window=self.target_window, n_bins=self.n_bins, min_frac=self.target_min_frac,
                min_dist=self.target_min_dist_frac * band_h,
            )
            cfg = ExitConfig(
                sl_abs=abs(c - stop),
                tp_abs=abs(target - c) if target is not None else None,
                time_stop_bars=self.time_stop_bars,
            )
            ts = bars[t].timestamp
            ext = (c - hi) / band_h if side is Side.LONG else (lo - c) / band_h
            out[ts] = Signal(
                side=side,
                timestamp=ts,
                price=c,
                score=max(0.0, min(1.0, ext)),
                reason=self.name,
                ref_time=ts,
                ref_price=near,
                ref2_time=ts,
                ref2_price=far,
                exit_config=cfg,
            )
        return out

    def dynamic_exit(
        self, pos: OpenPosition, bar: Bar, i: int, entry_idx: int
    ) -> tuple[ExitReason, float] | None:  # noqa: D102 (inherited)
        # Stall: after a minimum hold, a fresh TIGHT box has formed (price now
        # inside it) at a level at least one entry-box-height away from entry ->
        # the trend has stalled into a new consolidation; exit at close.
        if i - entry_idx < self.min_hold or i >= len(self._band_lo):
            return None
        lo, hi = float(self._band_lo[i]), float(self._band_hi[i])
        if not (hi > lo):
            return None
        c = bar.close
        if (hi - lo) > self.max_band_pct * c or not (lo <= c <= hi):
            return None
        near, far = pos.ref_price, pos.ref2_price
        band_h_entry = abs(near - far) if near is not None and far is not None else (hi - lo)
        if abs(0.5 * (lo + hi) - pos.entry_price) > band_h_entry:
            return ExitReason.TRAIL_STOP, c
        return None

    def on_bar(self, bar: Bar) -> Signal | None:  # noqa: D102 (inherited)
        # Entries come from precompute() via the MultiSimulator; the per-bar path
        # is unused for this strategy.
        return None

    def get_exit_rules(self) -> ExitConfig:  # noqa: D102 (inherited)
        return ExitConfig(time_stop_bars=self.time_stop_bars)
