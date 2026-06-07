"""Target-distance & target-off vs cost, for density_multi (w=168/mbp=0.03/5-slot).

The chart showed the dense **target** exiting ~3 bars after entry at ~+0.4% — the
nearest heavy node sits just above the broken edge (the box lip), so target exits
are tiny and the most fragile to spread/fees. This tests two fixes against a
round-trip cost sweep:

* **target distance** — require the next dense node to sit at least
  ``target_min_dist_frac × band_height`` *beyond* the broken edge (skip the lip),
  so a target exit captures a real move;
* **target off** — drop the dense target entirely (far-edge stop + time stop only).

Judged by the annualised mark-to-market **equity Sharpe** (IS / OOS) across costs.
Also prints each variant's exit mix + median target hold/return so the "exits
soon" symptom can be seen to move.

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.density_multi_target_cost

Env: ``DM_TF`` (1h), ``DM_PRODUCT`` (GMO_BTC_JPY).
"""

from __future__ import annotations

import os
from dataclasses import replace

import numpy as np
from loguru import logger

from src.backtest.analysis.density_multi_probe import (
    Config,
    _equity_sharpe,
    _net_jpy,
    _precompute_bands,
    simulate,
)
from src.backtest.sign_benchmark import split_in_out_sample
from src.core.types import ExitReason, Timeframe, Trade
from src.data.cache import load_cache

WINDOW = 168
MAX_BAND_PCT = 0.03
FEES = (0.0, 0.0002, 0.0005, 0.001, 0.002)  # per side; round-trip = 2x

# (label, use_target, target_min_dist_frac)
VARIANTS = (
    ("target off", False, 0.0),
    ("dist 0.0 (current)", True, 0.0),
    ("dist 0.5 bh", True, 0.5),
    ("dist 1.0 bh", True, 1.0),
    ("dist 1.5 bh", True, 1.5),
    ("dist 2.0 bh", True, 2.0),
)


def _target_shape(trades: list[Trade]) -> str:
    tp = [t for t in trades if t.exit_reason is ExitReason.TAKE_PROFIT]
    if not tp:
        return "no target exits"
    hold = np.median([t.bars_held for t in tp])
    ret = np.median([t.gross_return_pct * 100 for t in tp])
    return f"target n={len(tp)} medHold={hold:.0f}h medGross={ret:+.2f}%"


def _mix(trades: list[Trade]) -> str:
    from collections import Counter

    c = Counter(t.exit_reason.value for t in trades)
    n = len(trades) or 1
    return " ".join(f"{k[:4]}={c[k] / n:.0%}" for k in
                    ["take_profit", "stop_loss", "time_stop", "trail_stop", "end_of_data"] if c.get(k))


def run() -> None:
    """Run the variant x cost grid and print equity-Sharpe tables."""
    tf = Timeframe(os.environ.get("DM_TF", "1h"))
    product = os.environ.get("DM_PRODUCT", "GMO_BTC_JPY")
    ppy = (365 * 24 * 3600) / tf.seconds

    bars = load_cache(tf, product=product).bars
    if not bars:
        raise RuntimeError(f"No {tf.value} bars for {product}.")
    in_bars, oos_bars = split_in_out_sample(bars)
    logger.info("target_cost {} {}: precomputing w={} bands", product, tf.value, WINDOW)
    bl_in, bh_in = _precompute_bands([b.high for b in in_bars], [b.low for b in in_bars], WINDOW, 48, 0.70)
    bl_oos, bh_oos = _precompute_bands([b.high for b in oos_bars], [b.low for b in oos_bars], WINDOW, 48, 0.70)

    base = Config(window=WINDOW, max_band_pct=MAX_BAND_PCT, max_slots=5)
    print(f"\n=== density_multi target-distance / off vs cost  {product} {tf.value} "
          f"(w={WINDOW} mbp={MAX_BAND_PCT} 5 slots)  [B&H IS eqSh +0.64] ===")

    for label, use_t, dist in VARIANTS:
        # Exit shape at the default 4 bps round-trip (per-side 0.0002).
        cfg0 = replace(base, use_target=use_t, target_min_dist_frac=dist, fee_rate=0.0002)
        tr_in0, _f, _eq = simulate(in_bars, bl_in, bh_in, cfg0)
        print(f"\n{label:>18}:  IS {_target_shape(tr_in0)}  | mix[{_mix(tr_in0)}]")
        # Cost sweep.
        print(f"   {'RTbps':>6} {'IS eqSh':>8} {'OOS eqSh':>8} {'netIS':>9} {'netOOS':>9}")
        for fee in FEES:
            cfg = replace(cfg0, fee_rate=fee)
            tr_in, _fi, eq_in = simulate(in_bars, bl_in, bh_in, cfg)
            tr_oos, _fo, eq_oos = simulate(oos_bars, bl_oos, bh_oos, cfg)
            es_in, _di = _equity_sharpe(eq_in, ppy)
            es_oos, _do = _equity_sharpe(eq_oos, ppy)
            print(f"   {fee * 2e4:>6.0f} {es_in:>+8.2f} {es_oos:>+8.2f} "
                  f"{_net_jpy(tr_in):>+9.0f} {_net_jpy(tr_oos):>+9.0f}")


if __name__ == "__main__":
    from src.config import get_settings
    from src.logging_setup import configure_logging

    configure_logging(get_settings().log_level)
    run()
