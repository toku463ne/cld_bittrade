"""Slot-count sweep for the multi-position dense-breakout (w=168, mbp=0.03).

The walk-forward (see :mod:`density_multi_walkforward`) left exactly one
regime-robust config: ``window=168, max_band_pct=0.03`` with the target/stall
dense-aware exits. This sweeps how many concurrent **slots** to hold, judged by
the metric we trust — per-fold equity-Sharpe consistency across the 6 folds —
plus the IS/OOS headline.

On ``unit`` (per-slot size): with uniform sizing the per-slot unit is a pure
linear scalar on the equity curve, so it leaves the equity **Sharpe unchanged**
and scales only net JPY and the JPY drawdown linearly. (And per CLAUDE.md size is
pinned at the 0.001 min lot until something ships.) So the Sharpe-relevant lever
is the slot *count*, which changes the equity-curve shape via how many overlapping
trades are diversified; ``unit`` is reported analytically. Max gross exposure at N
slots is ``N x unit`` BTC.

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.density_multi_slotsweep

Env knobs: ``DM_TF`` (1h), ``DM_PRODUCT`` (GMO_BTC_JPY), ``DM_FOLDS`` (6),
``DM_UNIT`` (0.001), and the exit knobs (``DM_TIMESTOP`` etc.).
"""

from __future__ import annotations

import os

from loguru import logger

from src.backtest.analysis.density_multi_probe import (
    Config,
    _equity_sharpe,
    _net_jpy,
    simulate,
)
from src.backtest.analysis.density_multi_walkforward import _bh_sharpe, _fold_bounds
from src.backtest.analysis.density_multi_probe import _precompute_bands
from src.backtest.sign_benchmark import split_in_out_sample
from src.core.types import Timeframe
from src.data.cache import load_cache

WINDOW = 168
MAX_BAND_PCT = 0.03
SLOTS = (1, 2, 3, 4, 5, 6, 8, 10)


def _cfg(slots: int, unit: float) -> Config:
    return Config(
        window=WINDOW,
        max_band_pct=MAX_BAND_PCT,
        max_slots=slots,
        unit=unit,
        time_stop_bars=int(os.environ.get("DM_TIMESTOP", 120)),
        target_window=int(os.environ.get("DM_TARGET_WINDOW", 336)),
        sl_buffer=float(os.environ.get("DM_SL_BUFFER", 0.10)),
        min_hold=int(os.environ.get("DM_MINHOLD", 6)),
    )


def run_slotsweep() -> None:
    """Sweep max_slots at w=168/mbp=0.03 and print per-fold + IS/OOS metrics."""
    tf = Timeframe(os.environ.get("DM_TF", "1h"))
    product = os.environ.get("DM_PRODUCT", "GMO_BTC_JPY")
    k = int(os.environ.get("DM_FOLDS", 6))
    unit = float(os.environ.get("DM_UNIT", 0.001))
    ppy = (365 * 24 * 3600) / tf.seconds

    bars = load_cache(tf, product=product).bars
    if not bars:
        raise RuntimeError(f"No {tf.value} bars for {product}.")
    n = len(bars)
    bounds = _fold_bounds(n, k)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]

    logger.info("slotsweep {} {}: {} bars, w={} mbp={} — precomputing bands",
                product, tf.value, n, WINDOW, MAX_BAND_PCT)
    bl, bh = _precompute_bands(highs, lows, WINDOW, 48, 0.70)
    in_bars, oos_bars = split_in_out_sample(bars)
    cut = len(in_bars)

    bh_by_fold = [_bh_sharpe(bars[bounds[i]:bounds[i + 1]], ppy) for i in range(k)]

    print(f"\n=== SLOT SWEEP  w={WINDOW} mbp={MAX_BAND_PCT}  {product} {tf.value}  unit={unit} ===")
    print("    per-fold B&H eqSh: " + " ".join(f"f{i + 1}={bh_by_fold[i]:+.2f}" for i in range(k)))
    print("    (eqSh = annualised mark-to-market equity Sharpe; net/DD scale linearly with unit)")
    header = (f"\n    {'slots':>5} {'fold+':>5} {'IS':>6} {'OOS':>6} "
              f"{'netIS':>9} {'netOOS':>9} {'ddOOS':>8} {'maxexpBTC':>9}")
    print(header)

    rows: list[tuple[int, int, float, float]] = []
    for slots in SLOTS:
        cfg = _cfg(slots, unit)
        # Per-fold consistency (fixed config per fold).
        folds_pos = 0
        fold_es: list[float] = []
        for i in range(k):
            a, b = bounds[i], bounds[i + 1]
            _tr, _f, eq = simulate(bars[a:b], bl[a:b], bh[a:b], cfg)
            es, _dd = _equity_sharpe(eq, ppy)
            fold_es.append(es)
            if es > 0:
                folds_pos += 1
        # IS / OOS headline.
        tr_in, _fi, eq_in = simulate(in_bars, bl[:cut], bh[:cut], cfg)
        tr_oos, _fo, eq_oos = simulate(oos_bars, bl[cut:], bh[cut:], cfg)
        es_in, _ddi = _equity_sharpe(eq_in, ppy)
        es_oos, dd_oos = _equity_sharpe(eq_oos, ppy)
        print(f"    {slots:>5} {folds_pos:>3}/{k} {es_in:>+6.2f} {es_oos:>+6.2f} "
              f"{_net_jpy(tr_in):>+9.0f} {_net_jpy(tr_oos):>+9.0f} {dd_oos:>8.0f} "
              f"{slots * unit:>9.3f}")
        rows.append((slots, folds_pos, es_in, es_oos))

    print("\n    per-fold eqSh by slot count:")
    for slots in SLOTS:
        cfg = _cfg(slots, unit)
        fe = []
        for i in range(k):
            a, b = bounds[i], bounds[i + 1]
            _tr, _f, eq = simulate(bars[a:b], bl[a:b], bh[a:b], cfg)
            fe.append(_equity_sharpe(eq, ppy)[0])
        print(f"    slots={slots:>2}: " + " ".join(f"{v:+.2f}" for v in fe))

    best = max(rows, key=lambda r: (r[1], r[2] + r[3]))
    print(f"\n    => most consistent: slots={best[0]} ({best[1]}/{k} folds+, "
          f"IS {best[2]:+.2f} / OOS {best[3]:+.2f})")
    print("    NOTE: unit is a linear PnL/DD scalar (Sharpe-invariant); pinned at "
          "0.001 min lot until ship. Gross exposure = slots x unit BTC.")


if __name__ == "__main__":
    from src.config import get_settings
    from src.logging_setup import configure_logging

    configure_logging(get_settings().log_level)
    run_slotsweep()
