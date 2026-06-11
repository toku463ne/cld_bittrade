"""A/B + walk-forward for the vol_expansion_ride contra-extreme entry knob.

The shipped ``vol_expansion_ride`` enters on every squeeze→2×ATR burst in the
burst-bar direction. A chart-driven idea: skip "two-sided / directionless"
expansions — a burst bar that, before closing in the ride direction, printed an
extreme AGAINST it (a LONG bar undercutting the prior-N low, a SHORT bar making a
higher high than the prior-N high). Per-trade mean-return gradient was +ve in 6/6
WF folds (mean +0.44%); this script tests whether that survives on the **equity
metric** (annualised mark-to-market Sharpe), where the filter also drops ~27% of
trades and so could hurt DD/concurrency on this multi-position strategy.

It mirrors ``src.backtest.cycle`` (same IS/OOS split, same
``annualized_sharpe_from_levels`` equity Sharpe vs B&H, same quarterly relative
consistency) but instantiates the strategy directly so the ``skip_contra_extreme``
knob can be toggled (the registry/cycle path uses default args). It also runs the
project's fixed-config walk-forward (analysis A) on both arms.

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.vol_expansion_contra_ab

Env knobs: ``VE_TF`` (1h), ``VE_PRODUCT`` (GMO_BTC_JPY), ``VE_FOLDS`` (6),
``VE_LB`` (contra lookback, default 1).
"""

from __future__ import annotations

import os

import numpy as np
from loguru import logger

from src.backtest.cycle import _quarter_consistency
from src.backtest.metrics import annualized_sharpe_from_levels
from src.backtest.sign_benchmark import split_in_out_sample
from src.core.types import Bar, Timeframe, Trade
from src.data.cache import load_cache
from src.simulator import MultiSimulator
from src.simulator.simulator import DEFAULT_FEE_RATE
from src.strategy.vol_expansion_ride import VolExpansionRideStrategy


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


def _build(lb: int | None) -> VolExpansionRideStrategy:
    return VolExpansionRideStrategy(skip_contra_extreme=lb)


def _run(
    bars: list[Bar], lb: int | None, size: float, rate: float
) -> tuple[list[float], list[Trade]]:
    """Run one arm on a bar segment. Returns ``(equity_curve, trades)``."""
    res = MultiSimulator(_build(lb), size=size, fee_rate=rate).run(bars)
    return res.equity_curve, res.trades


def run_ab() -> None:
    """Run the IS/OOS gate A/B and the fixed-config walk-forward for both arms."""
    tf = Timeframe(os.environ.get("VE_TF", "1h"))
    product = os.environ.get("VE_PRODUCT", "GMO_BTC_JPY")
    k = int(os.environ.get("VE_FOLDS", 6))
    lb = int(os.environ.get("VE_LB", 1))
    size = 0.001
    rate = DEFAULT_FEE_RATE
    ppy = (365 * 24 * 3600) / tf.seconds

    bars = load_cache(tf, product=product).bars
    if not bars:
        raise RuntimeError(f"No {tf.value} bars for {product}.")
    n = len(bars)
    in_bars, oos_bars = split_in_out_sample(bars)

    arms: list[tuple[str, int | None]] = [("baseline (shipped)", None), (f"contra lb={lb}", lb)]

    # ---- Gate A: IS/OOS equity Sharpe vs B&H + quarterly consistency ----------
    bench_in = annualized_sharpe_from_levels([b.close for b in in_bars], ppy, pct=True)
    bench_oos = annualized_sharpe_from_levels([b.close for b in oos_bars], ppy, pct=True)
    print(f"\n=== A/B GATE  ({product} {tf.value}, IS/OOS 80/20) ===")
    print(f"    B&H eqSharpe: IS={bench_in:+.3f}  OOS={bench_oos:+.3f}")
    for label, arm in arms:
        eq_in, tr_in = _run(in_bars, arm, size, rate)
        eq_oos, tr_oos = _run(oos_bars, arm, size, rate)
        es_in = annualized_sharpe_from_levels(eq_in, ppy)
        es_oos = annualized_sharpe_from_levels(eq_oos, ppy)
        strat_cons, bench_cons = _quarter_consistency(tr_in, in_bars)
        consistent = strat_cons >= bench_cons
        ship = (es_in >= bench_in) and (es_oos >= bench_oos) and consistent
        print(
            f"\n    {label}:"
            f"\n      n_trades: IS={len(tr_in)}  OOS={len(tr_oos)}"
            f"\n      eqSharpe IS={es_in:+.3f} (B&H {bench_in:+.3f}, {'>=' if es_in >= bench_in else '<'})"
            f"  OOS={es_oos:+.3f} (B&H {bench_oos:+.3f}, {'>=' if es_oos >= bench_oos else '<'})"
            f"\n      consistency: {strat_cons:.0%} vs B&H {bench_cons:.0%} -> {'pass' if consistent else 'FAIL'}"
            f"\n      SHIP={ship}"
        )

    # ---- Fixed-config walk-forward (analysis A) for both arms ------------------
    bounds = _fold_bounds(n, k)
    bh_by_fold = [_bh_sharpe(bars[bounds[i]:bounds[i + 1]], ppy) for i in range(k)]
    labels = [
        f"{bars[bounds[i]].timestamp:%Y-%m-%d}->{bars[bounds[i + 1] - 1].timestamp:%Y-%m-%d}"
        for i in range(k)
    ]
    print(f"\n=== FIXED-CONFIG WALK-FORWARD across {k} folds ===")
    print("    fold periods + B&H Sharpe:")
    for i in range(k):
        print(f"      f{i + 1} {labels[i]}   B&H eqSh={bh_by_fold[i]:+.2f}")
    for label, arm in arms:
        print(f"\n    {label}:")
        wins = beats = 0
        es_list = []
        for i in range(k):
            a, b = bounds[i], bounds[i + 1]
            eq, tr = _run(bars[a:b], arm, size, rate)
            es = annualized_sharpe_from_levels(eq, ppy)
            es_list.append(es)
            if es > 0:
                wins += 1
            beat = es > bh_by_fold[i]
            if beat:
                beats += 1
            print(f"      f{i + 1} eqSh={es:+.2f}  n={len(tr):<4} {'beat B&H' if beat else ''}")
        print(f"      => {wins}/{k} folds +ve, {beats}/{k} beat B&H, mean eqSh={np.mean(es_list):+.2f}")


if __name__ == "__main__":
    from src.config import get_settings
    from src.logging_setup import configure_logging

    configure_logging(get_settings().log_level)
    run_ab()
