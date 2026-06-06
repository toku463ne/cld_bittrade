"""Probe: do VOLUME-defined walls ADD edge over TIME-defined walls?

Tests the user's actual intention (which the density_breakout_vol A/B did NOT —
that reweighted ONE value-area band; this is additive): high-VOLUME price zones
should act as *extra* walls the time profile misses, giving MORE breakout chances.

For each bar we build BOTH a time-at-price profile and a (plain) volume profile
over the trailing window ``[t-window, t-1]`` on a SHARED price grid, extract every
discrete wall from each (:func:`find_walls`), and look for a breakout *through* a
wall: the prior close sat inside a wall's zone and the current close crosses
beyond an edge (above -> LONG, below -> SHORT). Each breakout is classified:

- ``time``      : through a time-profile wall
- ``volume``    : through a volume-profile wall
- ``vol_only``  : through a volume wall whose zone overlaps NO time wall — the
                  ADDED chances; this is the class that decides the idea.

We then measure the signed forward return at the ride horizon, pooled by class,
plus a tight-box (<= max_band_pct wide) subset mirroring the shipped filter. If
``vol_only`` walls match/beat ``time`` walls they add value; if they are
coin-flips they only add noise trades. Direction is the question — the entry-edge
probe showed every breakout entry is ~DR 0.5, so "more walls" only helps if the
added ones are *better* barriers.

Usage::

    uv run --env-file .env.bt python -m src.backtest.analysis.volume_walls_probe \
        --timeframe 1h --product GMO_BTC_JPY
"""

from __future__ import annotations

import argparse

import numpy as np
from loguru import logger

from src.backtest.sign_benchmark import split_in_out_sample
from src.core.types import Timeframe
from src.data.cache import load_cache
from src.indicators.density import (
    find_walls,
    time_at_price_profile,
    volume_acceptance_profile,
)
from src.logging_setup import configure_logging

HORIZON_HOURS = [48, 96]


def _overlaps(a: tuple[float, float, float], walls: list[tuple[float, float, float]]) -> bool:
    """True if wall ``a``'s [lo,hi] zone overlaps any wall in ``walls``."""
    return any(a[0] <= w[1] and w[0] <= a[1] for w in walls)


def _breakout(
    wall: tuple[float, float, float], pre_close: float, close: float
) -> int:
    """+1 (long) / -1 (short) / 0 if ``close`` breaks out of ``wall`` after the
    prior close sat inside its zone."""
    lo, hi, _peak = wall
    if not (lo <= pre_close <= hi):
        return 0
    if close > hi:
        return 1
    if close < lo:
        return -1
    return 0


def run(
    tf: Timeframe,
    *,
    product: str | None,
    window: int = 168,
    n_bins: int = 48,
    prominence_k: float = 1.0,
    max_band_pct: float = 0.02,
    vol_clip: float = 8.0,
) -> None:
    """Detect time/volume/vol_only wall breakouts and score them by class."""
    cache = load_cache(tf, product=product)
    in_sample, _ = split_in_out_sample(cache.bars)
    o = np.array([b.open for b in in_sample], dtype=float)
    h = np.array([b.high for b in in_sample], dtype=float)
    low = np.array([b.low for b in in_sample], dtype=float)
    c = np.array([b.close for b in in_sample], dtype=float)
    v = np.array([b.volume for b in in_sample], dtype=float)
    n = len(c)
    minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}[tf.value]
    bph = 60.0 / minutes

    # records: (idx, side, class, width_frac)
    recs: list[tuple[int, int, str, float]] = []
    for t in range(window + 1, n):
        s0, s1 = t - window, t  # profile over [t-window, t-1]
        lo_b = float(low[s0:s1].min())
        hi_b = float(h[s0:s1].max())
        if hi_b <= lo_b:
            continue
        ct, wt = time_at_price_profile(h[s0:s1], low[s0:s1], n_bins, lo=lo_b, hi=hi_b)
        cv, wv = volume_acceptance_profile(
            o[s0:s1], h[s0:s1], low[s0:s1], c[s0:s1], v[s0:s1],
            n_bins, body_ratio=0.5, lo=lo_b, hi=hi_b, vol_clip=vol_clip,
        )
        walls_t = find_walls(ct, wt, prominence_k=prominence_k)
        walls_v = find_walls(cv, wv, prominence_k=prominence_k)
        pre, cl = float(c[t - 1]), float(c[t])

        for wall in walls_t:
            side = _breakout(wall, pre, cl)
            if side != 0:
                recs.append((t, side, "time", (wall[1] - wall[0]) / cl))
        for wall in walls_v:
            side = _breakout(wall, pre, cl)
            if side == 0:
                continue
            klass = "vol_only" if not _overlaps(wall, walls_t) else "volume"
            recs.append((t, side, klass, (wall[1] - wall[0]) / cl))

    logger.info(
        "{} {} — {} wall-breakouts (time={}, volume={}, vol_only={})",
        tf.value,
        product or "configured",
        len(recs),
        sum(1 for r in recs if r[2] == "time"),
        sum(1 for r in recs if r[2] in ("volume", "vol_only")),
        sum(1 for r in recs if r[2] == "vol_only"),
    )

    def _report(rows: list[tuple[int, int, str, float]], label: str) -> None:
        logger.info("--- {} ---", label)
        logger.info("  class    | horizon |    n |   DR  |  mean_r  | per-trade Sharpe")
        for klass in ("time", "volume", "vol_only"):
            sub = [r for r in rows if r[2] == klass]
            for hh in HORIZON_HOURS:
                hb = int(round(hh * bph))
                signed = [
                    side * (c[t + hb] - c[t]) / c[t]
                    for (t, side, _k, _wf) in sub
                    if t + hb < n
                ]
                if not signed:
                    continue
                arr = np.array(signed)
                dr = float((arr > 0).mean())
                mr = float(arr.mean())
                sh = mr / float(arr.std()) if arr.std() > 0 else 0.0
                logger.info(
                    "  {:<8} | {:>4}h | {:>4} | {:.3f} | {:+.5f} | {:+.4f}",
                    klass, hh, len(arr), dr, mr, sh,
                )

    _report(recs, "ALL walls")
    _report([r for r in recs if r[3] <= max_band_pct], f"TIGHT walls (<= {max_band_pct:.0%})")


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Volume-walls additive entry-edge probe.")
    parser.add_argument("--timeframe", choices=[tf.value for tf in Timeframe], default="1h")
    parser.add_argument("--product", default=None)
    parser.add_argument("--prominence-k", type=float, default=1.0)
    parser.add_argument("--window", type=int, default=168)
    args = parser.parse_args()
    configure_logging()
    run(
        Timeframe(args.timeframe),
        product=args.product,
        window=args.window,
        prominence_k=args.prominence_k,
    )


if __name__ == "__main__":
    main()
