"""Relative-density band probe (regime-adaptive "dense" vs the absolute filter).

Tests the user's idea: instead of the absolute tight-box filter
(``band_height <= max_band_pct x price``), define the dense band *relative* to the
window's own density distribution — the contiguous run of bins whose time-weight
exceeds ``mean + sigma_r x std`` around the Point-of-Control, with a scale-free
backstop (POC weight >= ``min_poc_ratio x`` the uniform weight) to skip
structureless periods (see :func:`src.indicators.density.relative_dense_band`).

The intent is **more entries** by catching concentrations the rigid width filter
misses (wide range, sharp peak). Reuses the multi-position engine + dense-aware
exits unchanged (5 slots, target_min_dist_frac=1.5); only the band definition
changes. Reports entry counts and IS/OOS annualised equity Sharpe across a cost
sweep, vs the shipped value-area baseline (w=168, max_band_pct=0.03).

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.density_relative_probe
"""

from __future__ import annotations

import os
from dataclasses import replace

import numpy as np
from loguru import logger

from src.backtest.analysis.density_multi_probe import (
    Config,
    _equity_sharpe,
    _precompute_bands,
    simulate,
)
from src.backtest.sign_benchmark import split_in_out_sample
from src.core.types import Bar, Timeframe
from src.data.cache import load_cache
from src.indicators.density import relative_dense_band, time_at_price_profile

WINDOW = 168
N_BINS = 48
FEES = (0.0002, 0.001, 0.002)  # per side; round-trip = 2x
SIGMAS = (1.0, 1.25, 1.5, 2.0)
POC_RATIOS = (2.0, 3.0)
# A loose absolute width backstop so the relative band can't be absurd.
LOOSE_MAX_BAND_PCT = 0.10


def _relative_bands(
    highs: list[float], lows: list[float], window: int, sigma_r: float, min_poc_ratio: float
) -> tuple[np.ndarray, np.ndarray]:
    """Relative dense band over ``[t-window, t-1]`` for each bar (NaN if none)."""
    n = len(highs)
    bl = np.full(n, np.nan)
    bh = np.full(n, np.nan)
    for t in range(window, n):
        centers, weights = time_at_price_profile(highs[t - window : t], lows[t - window : t], N_BINS)
        band = relative_dense_band(centers, weights, sigma_r, min_poc_ratio)
        if band is not None:
            bl[t], bh[t] = band
    return bl, bh


def _eval(
    in_bars: list[Bar],
    oos_bars: list[Bar],
    bl_in: np.ndarray,
    bh_in: np.ndarray,
    bl_oos: np.ndarray,
    bh_oos: np.ndarray,
    ppy: float,
) -> None:
    base = Config(
        window=WINDOW, max_band_pct=LOOSE_MAX_BAND_PCT, max_slots=5,
        use_target=True, target_min_dist_frac=1.5,
    )
    cfg0 = replace(base, fee_rate=0.0002)
    tr_in, fires_in, _e = simulate(in_bars, bl_in, bh_in, cfg0)
    tr_oos, fires_oos, _e2 = simulate(oos_bars, bl_oos, bh_oos, cfg0)
    cells = []
    for fee in FEES:
        cfg = replace(cfg0, fee_rate=fee)
        _ti, _fi, eq_in = simulate(in_bars, bl_in, bh_in, cfg)
        _to, _fo, eq_oos = simulate(oos_bars, bl_oos, bh_oos, cfg)
        cells.append((int(fee * 2e4), _equity_sharpe(eq_in, ppy)[0], _equity_sharpe(eq_oos, ppy)[0]))
    txt = "  ".join(f"{bp}bp IS{a:+.2f}/OOS{b:+.2f}" for bp, a, b in cells)
    print(f"    trIS={len(tr_in):>4} trOOS={len(tr_oos):>3}  | {txt}")


def run() -> None:
    """Sweep relative-band params vs cost and compare to the value-area baseline."""
    tf = Timeframe(os.environ.get("DM_TF", "1h"))
    product = os.environ.get("DM_PRODUCT", "GMO_BTC_JPY")
    ppy = (365 * 24 * 3600) / tf.seconds
    bars = load_cache(tf, product=product).bars
    if not bars:
        raise RuntimeError(f"No {tf.value} bars for {product}.")
    in_bars, oos_bars = split_in_out_sample(bars)
    in_h, in_l = [b.high for b in in_bars], [b.low for b in in_bars]
    oos_h, oos_l = [b.high for b in oos_bars], [b.low for b in oos_bars]

    print(f"\n=== relative-density band probe  {product} {tf.value} "
          f"(w={WINDOW}, 5 slots, target dist 1.5)  [B&H IS eqSh +0.64] ===")

    logger.info("baseline (value-area, max_band_pct=0.03)")
    blv_in, bhv_in = _precompute_bands(in_h, in_l, WINDOW, N_BINS, 0.70)
    blv_oos, bhv_oos = _precompute_bands(oos_h, oos_l, WINDOW, N_BINS, 0.70)
    # Baseline uses the absolute filter, so run it at max_band_pct=0.03.
    base_cfg = Config(window=WINDOW, max_band_pct=0.03, max_slots=5, use_target=True, target_min_dist_frac=1.5)
    print("\n  BASELINE value-area + max_band_pct=0.03:")
    cells = []
    tr_in, _f, _e = simulate(in_bars, blv_in, bhv_in, replace(base_cfg, fee_rate=0.0002))
    tr_oos, _f2, _e2 = simulate(oos_bars, blv_oos, bhv_oos, replace(base_cfg, fee_rate=0.0002))
    for fee in FEES:
        c = replace(base_cfg, fee_rate=fee)
        _a, _b, eqi = simulate(in_bars, blv_in, bhv_in, c)
        _c, _d, eqo = simulate(oos_bars, blv_oos, bhv_oos, c)
        cells.append((int(fee * 2e4), _equity_sharpe(eqi, ppy)[0], _equity_sharpe(eqo, ppy)[0]))
    print(f"    trIS={len(tr_in):>4} trOOS={len(tr_oos):>3}  | "
          + "  ".join(f"{bp}bp IS{a:+.2f}/OOS{b:+.2f}" for bp, a, b in cells))

    for poc in POC_RATIOS:
        print(f"\n  RELATIVE  min_poc_ratio={poc} (loose abs cap {LOOSE_MAX_BAND_PCT:.0%}):")
        for sig in SIGMAS:
            logger.info("relative sigma_r={} poc={}", sig, poc)
            bl_in, bh_in = _relative_bands(in_h, in_l, WINDOW, sig, poc)
            bl_oos, bh_oos = _relative_bands(oos_h, oos_l, WINDOW, sig, poc)
            print(f"  R={sig}:")
            _eval(in_bars, oos_bars, bl_in, bh_in, bl_oos, bh_oos, ppy)


if __name__ == "__main__":
    from src.config import get_settings
    from src.logging_setup import configure_logging

    configure_logging(get_settings().log_level)
    run()
