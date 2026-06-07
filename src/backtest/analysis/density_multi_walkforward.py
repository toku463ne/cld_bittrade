"""Walk-forward robustness for the multi-position dense-breakout probe.

The single IS/OOS split in :mod:`density_multi_probe` left two doubts:
  * grid selection — is the winning ``(window, max_band_pct)`` cell just the
    luckiest of 16?
  * regime leakage — is the strong OOS only because the recent 20% fell and the
    strategy (not long-only) could short it?

This module answers both by slicing the full series into ``K`` consecutive folds
and running two analyses:

A. **Fixed-config across folds** — take a candidate cell and report its
   annualised mark-to-market equity Sharpe + net JPY in *each* fold, beside
   buy-and-hold's own annualised Sharpe for that fold. Shows whether one fixed
   config earns across bull / bear / chop, not just the last slice.

B. **Anchored walk-forward with re-selection** — for each fold ``k>=1`` pick the
   best cell by equity Sharpe on *all data before* the fold, then evaluate that
   (out-of-sample-chosen) cell on the fold. If the chosen-config sequence is
   positive across folds, the grid selection is not overfit.

Bands depend only on ``[t-window, t-1]`` so they are precomputed full-series once
per window and sliced per fold (a small warm-up loss at each fold start, same as
the project's existing OOS handling). No look-ahead.

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.density_multi_walkforward

Env knobs: ``DM_TF`` (1h), ``DM_PRODUCT`` (GMO_BTC_JPY), ``DM_FOLDS`` (6), plus
the same slot/exit knobs as the probe (``DM_SLOTS`` etc.).
"""

from __future__ import annotations

import os

import numpy as np
from loguru import logger

from src.backtest.analysis.density_multi_probe import (
    MAX_BAND_PCTS,
    WINDOWS,
    Config,
    _equity_sharpe,
    _net_jpy,
    _payoff,
    _precompute_bands,
    simulate,
)
from src.core.types import Bar, Timeframe
from src.data.cache import load_cache

# Candidate fixed configs for analysis A (the probe's strong cells + the
# original shipping window for reference).
CANDIDATES = ((48, 0.02), (72, 0.015), (168, 0.03), (168, 0.02))


def _bh_sharpe(bars: list[Bar], ppy: float) -> float:
    """Annualised Sharpe of buy-and-hold close-to-close returns over ``bars``."""
    if len(bars) < 3:
        return 0.0
    c = np.array([b.close for b in bars], dtype=float)
    r = np.diff(c) / c[:-1]
    sd = float(r.std(ddof=1))
    return float(r.mean() / sd * np.sqrt(ppy)) if sd > 0 else 0.0


def _fold_bounds(n: int, k: int) -> list[int]:
    """``k+1`` evenly spaced indices splitting ``n`` bars into ``k`` folds."""
    return [round(i * n / k) for i in range(k + 1)]


def _make_cfg(window: int, mbp: float) -> Config:
    return Config(
        window=window,
        max_band_pct=mbp,
        max_slots=int(os.environ.get("DM_SLOTS", 5)),
        unit=float(os.environ.get("DM_UNIT", 0.001)),
        time_stop_bars=int(os.environ.get("DM_TIMESTOP", 120)),
        target_window=int(os.environ.get("DM_TARGET_WINDOW", 336)),
        sl_buffer=float(os.environ.get("DM_SL_BUFFER", 0.10)),
        min_hold=int(os.environ.get("DM_MINHOLD", 6)),
    )


def _eval_segment(
    bars: list[Bar], bl: np.ndarray, bh: np.ndarray, cfg: Config, ppy: float
) -> tuple[float, float, float, int]:
    """Run one config on one bar segment. Returns ``(eqSharpe, netJPY, payoff, n)``."""
    trades, _fires, equity = simulate(bars, bl, bh, cfg)
    es, _dd = _equity_sharpe(equity, ppy)
    return es, _net_jpy(trades), _payoff(trades), len(trades)


def run_walkforward() -> None:
    """Run both walk-forward analyses and print the per-fold tables."""
    tf = Timeframe(os.environ.get("DM_TF", "1h"))
    product = os.environ.get("DM_PRODUCT", "GMO_BTC_JPY")
    k = int(os.environ.get("DM_FOLDS", 6))
    ppy = (365 * 24 * 3600) / tf.seconds

    bars = load_cache(tf, product=product).bars
    if not bars:
        raise RuntimeError(f"No {tf.value} bars for {product}.")
    n = len(bars)
    bounds = _fold_bounds(n, k)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]

    # Full-series bands once per window (sliced per fold below).
    logger.info("walkforward {} {}: {} bars, {} folds — precomputing bands", product, tf.value, n, k)
    bands: dict[int, tuple[np.ndarray, np.ndarray]] = {
        w: _precompute_bands(highs, lows, w, 48, 0.70) for w in WINDOWS
    }

    fold_label = []
    for i in range(k):
        a, b = bounds[i], bounds[i + 1]
        fold_label.append(f"{bars[a].timestamp:%Y-%m-%d}->{bars[b - 1].timestamp:%Y-%m-%d}")

    # ---- A. Fixed config across folds -------------------------------------
    print(f"\n=== A. FIXED-CONFIG across {k} folds  ({product} {tf.value}) ===")
    print("    (eqSh = annualised equity Sharpe; B&H = buy-and-hold annualised Sharpe same fold)")
    bh_by_fold = []
    for i in range(k):
        a, b = bounds[i], bounds[i + 1]
        bh_by_fold.append(_bh_sharpe(bars[a:b], ppy))
    print("\n    fold periods + B&H Sharpe:")
    for i in range(k):
        print(f"      f{i + 1} {fold_label[i]}   B&H eqSh={bh_by_fold[i]:+.2f}")

    for window, mbp in CANDIDATES:
        cfg = _make_cfg(window, mbp)
        bl_full, bh_full = bands[window]
        print(f"\n    w={window} mbp={mbp}:")
        wins = 0
        for i in range(k):
            a, b = bounds[i], bounds[i + 1]
            es, net, payoff, ntr = _eval_segment(bars[a:b], bl_full[a:b], bh_full[a:b], cfg, ppy)
            beat = "beat B&H" if es > bh_by_fold[i] else ""
            if es > 0:
                wins += 1
            print(f"      f{i + 1} eqSh={es:+.2f}  net={net:+8.0f}JPY  payoff={payoff:.2f}  "
                  f"n={ntr:<4} {beat}")
        print(f"      => {wins}/{k} folds equity-Sharpe-positive")

    # ---- B. Anchored walk-forward with re-selection -----------------------
    print("\n=== B. ANCHORED WALK-FORWARD (re-select best cell on data before each fold) ===")
    print("    train = all bars before the fold; test = the fold. Chosen cell is OOS.")
    wf_pos = 0
    wf_tested = 0
    wf_es: list[float] = []
    for i in range(1, k):
        tr_end = bounds[i]
        a, b = bounds[i], bounds[i + 1]
        # Select best cell on the anchored training window.
        best = None
        for window in WINDOWS:
            bl_full, bh_full = bands[window]
            for mbp in MAX_BAND_PCTS:
                cfg = _make_cfg(window, mbp)
                es_tr, _net, _po, _n = _eval_segment(
                    bars[:tr_end], bl_full[:tr_end], bh_full[:tr_end], cfg, ppy
                )
                if best is None or es_tr > best[0]:
                    best = (es_tr, window, mbp)
        assert best is not None
        _es_tr, bw, bmbp = best
        cfg = _make_cfg(bw, bmbp)
        bl_full, bh_full = bands[bw]
        es, net, payoff, ntr = _eval_segment(bars[a:b], bl_full[a:b], bh_full[a:b], cfg, ppy)
        wf_tested += 1
        wf_es.append(es)
        if es > 0:
            wf_pos += 1
        flag = "beat B&H" if es > bh_by_fold[i] else ""
        print(f"    f{i + 1} {fold_label[i]}  chose w={bw} mbp={bmbp}  "
              f"test eqSh={es:+.2f} (B&H {bh_by_fold[i]:+.2f})  net={net:+8.0f}JPY n={ntr:<4} {flag}")
    mean_es = float(np.mean(wf_es)) if wf_es else 0.0
    print(f"\n    => walk-forward: {wf_pos}/{wf_tested} folds positive, mean test eqSh={mean_es:+.2f}")


if __name__ == "__main__":
    from src.config import get_settings
    from src.logging_setup import configure_logging

    configure_logging(get_settings().log_level)
    run_walkforward()
