"""Diagnostic: do a dwell-count or a swing-proximity filter carry signal?

Decides — *before* writing any sign/strategy — whether either of two proposed
density_breakout entry filters has differential edge:

1. **Dwell bonus** (more entries via a quality gate): tag each fire with the
   length of the consecutive pre-breakout *dwell* — how many bars in a row, just
   before the breakout, closed inside the same (±1) price bin of the band's grid.
   If high-dwell fires have a better horizon return than low-dwell fires, a
   min-dwell gate (with a relaxed ``max_band_pct``) could add good entries.

2. **Zigzag cancellation** (fewer losses): tag each fire with the distance to the
   nearest recent zigzag swing *in the breakout direction* (an overhead swing
   high for a LONG, an underfoot swing low for a SHORT) — the "trapped traders"
   level that should fight the breakout. If near-swing fires underperform
   far-from-swing fires, cancelling them lifts the average. Reported for zigzag
   ``size`` in {8, 12, 16}; the verdict must hold the *same sign* across all three
   to count as robust (not a size-fit artifact).

The edge that matters is the multi-hour/day RIDE, so we score the horizon-matched
signed forward return (48h, 96h), same as the entry-horizon probe — NOT the first
swing. No exit logic; pure entry-subset quality.

Causality: the band grid and dwell use only bars ``< t``; a swing at bar ``p`` is
counted only once it is confirmable by the fire bar (``p + size <= t``). No
look-ahead.

Usage::

    uv run --env-file .env.bt python -m src.backtest.analysis.entry_filter_probe \
        --timeframe 1h --product GMO_BTC_JPY
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from loguru import logger

from src.backtest.sign_benchmark import split_in_out_sample
from src.core.types import Side, Timeframe
from src.data.cache import load_cache
from src.indicators.zigzag import detect_peaks
from src.logging_setup import configure_logging
from src.signs.registry import get_sign

HORIZON_HOURS = [48, 96]
WINDOW = 168  # band/profile + dwell-grid + swing-lookback window (~1 week 1h)
N_BINS = 48
ZIGZAG_SIZES = [8, 12, 16]
# Distance-to-swing buckets, as a fraction of entry price.
DIST_EDGES = [0.005, 0.01, 0.02]


def _bph(tf: Timeframe) -> float:
    return 60.0 / {"1m": 1, "5m": 5, "15m": 15, "1h": 60}[tf.value]


def _bin_of(price: float, lo: float, hi: float, n_bins: int) -> int:
    """Index of the price's bin on the ``[lo, hi]`` grid, clipped to range."""
    if hi <= lo:
        return 0
    k = int((price - lo) / (hi - lo) * n_bins)
    return max(0, min(n_bins - 1, k))


def _dwell(closes: np.ndarray, lows: np.ndarray, highs: np.ndarray, t: int) -> int:
    """Consecutive pre-breakout closes sitting in the same (±1) band bin.

    The grid is the band's own grid over ``[t-WINDOW, t-1]`` (same as the sign).
    Counts back from ``close[t-1]`` while each earlier close stays within one bin.
    """
    s0 = t - WINDOW
    lo = float(lows[s0:t].min())
    hi = float(highs[s0:t].max())
    ref = _bin_of(float(closes[t - 1]), lo, hi, N_BINS)
    run = 1
    j = t - 2
    while j >= s0 and abs(_bin_of(float(closes[j]), lo, hi, N_BINS) - ref) <= 1:
        run += 1
        j -= 1
    return run


def _swing_dist(
    peaks_by_size: dict[int, list[tuple[int, bool, float]]],
    size: int,
    t: int,
    entry: float,
    is_long: bool,
) -> float:
    """Fraction-of-price distance to the nearest recent same-direction swing.

    LONG -> nearest swing HIGH at/above entry (overhead resistance); SHORT ->
    nearest swing LOW at/below entry. Only swings confirmable by ``t``
    (``bar_index + size <= t``) and within the trailing window are considered.
    ``inf`` when there is no such swing (nothing in the way).
    """
    best = np.inf
    lo_bound = t - WINDOW
    for bar_index, is_high, price in peaks_by_size[size]:
        if bar_index + size > t or bar_index < lo_bound:
            continue
        if is_long and is_high and price >= entry:
            best = min(best, (price - entry) / entry)
        elif (not is_long) and (not is_high) and price <= entry:
            best = min(best, (entry - price) / entry)
    return best


def _fwd(closes: np.ndarray, idxs: np.ndarray, sides: np.ndarray, hb: int) -> np.ndarray:
    """Signed forward return at ``hb`` bars; NaN where the horizon runs off."""
    end = idxs + hb
    out = np.full(idxs.shape, np.nan)
    ok = end < closes.size
    out[ok] = sides[ok] * (closes[end[ok]] - closes[idxs[ok]]) / closes[idxs[ok]]
    return out


def _stat_row(label: str, signed: np.ndarray) -> None:
    s = signed[~np.isnan(signed)]
    if s.size == 0:
        logger.info("  {:<22} |   -- | ----- | -------- | -------", label)
        return
    dr = float((s > 0).mean())
    mr = float(s.mean())
    sh = mr / float(s.std()) if s.std() > 0 else 0.0
    logger.info("  {:<22} | {:>4} | {:.3f} | {:+.5f} | {:+.4f}", label, s.size, dr, mr, sh)


def run(tf: Timeframe, *, product: str | None) -> None:
    """Tag density_breakout fires by dwell and swing-distance; bin forward returns."""
    cache = load_cache(tf, product=product)
    in_sample, _ = split_in_out_sample(cache.bars)
    df = pd.DataFrame(
        {
            "open": [b.open for b in in_sample],
            "high": [b.high for b in in_sample],
            "low": [b.low for b in in_sample],
            "close": [b.close for b in in_sample],
            "volume": [b.volume for b in in_sample],
        },
        index=pd.DatetimeIndex([b.timestamp for b in in_sample], name="timestamp"),
    )
    closes = df["close"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    ts_to_idx = {ts: i for i, ts in enumerate(df.index)}
    bph = _bph(tf)

    fires = get_sign("density_breakout").detect(df)
    idxs, sides, longs = [], [], []
    for f in fires:
        i = ts_to_idx[pd.Timestamp(f.fired_at)]
        if i < WINDOW + 1:  # need a full window of prior bars for dwell/grid
            continue
        idxs.append(i)
        sides.append(1.0 if f.side is Side.LONG else -1.0)
        longs.append(f.side is Side.LONG)
    idxs_a = np.array(idxs)
    sides_a = np.array(sides)
    n_total = closes.size
    logger.info(
        "density_breakout {} {} — {} fires (>=window), {} bars",
        tf.value, product or "configured", len(idxs), n_total,
    )

    # Precompute peaks per zigzag size (full series; gated causally at use).
    peaks_by_size: dict[int, list[tuple[int, bool, float]]] = {}
    hl, ll = highs.tolist(), lows.tolist()
    for size in ZIGZAG_SIZES:
        peaks_by_size[size] = [
            (p.bar_index, p.is_high, p.price) for p in detect_peaks(hl, ll, size=size)
        ]

    dwell = np.array([_dwell(closes, lows, highs, t) for t in idxs_a])
    dist_by_size = {
        size: np.array(
            [
                _swing_dist(peaks_by_size, size, t, float(closes[t]), is_long)
                for t, is_long in zip(idxs_a, longs, strict=True)
            ]
        )
        for size in ZIGZAG_SIZES
    }

    for h in HORIZON_HOURS:
        hb = int(round(h * bph))
        signed = _fwd(closes, idxs_a, sides_a, hb)
        logger.info("=== horizon {}h ({}b) ===", h, hb)
        logger.info("  subset                 |    n |   DR  |  mean_r  | Sharpe")
        _stat_row("ALL", signed)

        logger.info("  -- IDEA 1: dwell-count buckets --")
        for lo_d, hi_d in [(1, 2), (3, 5), (6, 10), (11, 10**9)]:
            m = (dwell >= lo_d) & (dwell <= hi_d)
            tag = f"dwell {lo_d}-{hi_d if hi_d < 100 else '+'}"
            _stat_row(tag, np.where(m, signed, np.nan))

        logger.info("  -- IDEA 2: dist-to-swing buckets --")
        for size in ZIGZAG_SIZES:
            dist = dist_by_size[size]
            edges = [0.0, *DIST_EDGES, np.inf]
            for a, b in zip(edges[:-1], edges[1:], strict=True):
                m = (dist >= a) & (dist < b)
                hi_lbl = "none" if b == np.inf else f"{b:.1%}"
                tag = f"sz{size} swing {a:.1%}-{hi_lbl}"
                _stat_row(tag, np.where(m, signed, np.nan))


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Dwell / zigzag-cancellation entry-filter probe.")
    parser.add_argument("--timeframe", choices=[tf.value for tf in Timeframe], default="1h")
    parser.add_argument("--product", default=None)
    args = parser.parse_args()
    configure_logging()
    run(Timeframe(args.timeframe), product=args.product)


if __name__ == "__main__":
    main()
