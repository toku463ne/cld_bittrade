"""A/B + walk-forward for the density_pullback failed-breakout invalidation exit.

The shipped ``density_pullback`` loses −3.95 sum_r to 325 stop_loss exits (58% of
trades, mean −1.22%, median 9 bars to fire) while 174 trail winners carry +5.27.
The zs-band stop is generic (inherited from random_hedge); the strategy has a
*structural* invalidation it ignores: once a bar **closes** back inside the value
area beyond ``depth`` × box-height from the broken edge, the breakout thesis is
dead. The ``invalidation_depth`` knob exits at that close instead of waiting for
the zs stop. The measured risk: trail winners that dip back into the box before
running — a too-shallow depth clips them.

Protocol (anti-knife-edge): the win must be **smooth across the depth sweep** and
hold across the fixed-config walk-forward folds; a single lucky depth cell that is
non-monotonic with its neighbours = overfit, reject (the confirm_bars lesson).

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.density_pullback_invalidation_ab

Env knobs: ``DP_TF`` (1h), ``DP_PRODUCT`` (GMO_BTC_JPY), ``DP_FOLDS`` (6),
``DP_DEPTHS`` (comma list, default ``0.25,0.5,0.75,1.0,1.25``).
"""

from __future__ import annotations

import os
from collections import Counter

import numpy as np
from loguru import logger

from src.backtest.cycle import _quarter_consistency
from src.backtest.metrics import annualized_sharpe_from_levels
from src.backtest.sign_benchmark import split_in_out_sample
from src.core.types import Bar, ExitReason, Timeframe, Trade
from src.data.cache import load_cache
from src.simulator import MultiSimulator
from src.simulator.simulator import DEFAULT_FEE_RATE
from src.strategy.density_pullback import DensityPullbackStrategy


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


def _run(
    bars: list[Bar], depth: float | None, size: float, rate: float
) -> tuple[list[float], list[Trade]]:
    """Run one arm on a bar segment. Returns ``(equity_curve, trades)``."""
    strat = DensityPullbackStrategy(invalidation_depth=depth)
    res = MultiSimulator(strat, size=size, fee_rate=rate).run(bars)
    return res.equity_curve, res.trades


def _exit_mix(trades: list[Trade]) -> str:
    """Compact exit-reason mix with the stop-loss bleed (sum_r of stops)."""
    mix = Counter(t.exit_reason.value for t in trades)
    stops = [t.return_pct for t in trades if t.exit_reason is ExitReason.STOP_LOSS]
    bleed = float(np.sum(stops)) if stops else 0.0
    parts = ", ".join(f"{k}={v}" for k, v in mix.most_common())
    return f"{parts} | stop bleed sum_r={bleed:+.2f}"


def run_ab() -> None:
    """Run the IS/OOS gate A/B and the fixed-config walk-forward for all arms."""
    tf = Timeframe(os.environ.get("DP_TF", "1h"))
    product = os.environ.get("DP_PRODUCT", "GMO_BTC_JPY")
    k = int(os.environ.get("DP_FOLDS", 6))
    depths = [
        float(d) for d in os.environ.get("DP_DEPTHS", "0.25,0.5,0.75,1.0,1.25").split(",")
    ]
    size = 0.001
    rate = DEFAULT_FEE_RATE
    ppy = (365 * 24 * 3600) / tf.seconds

    bars = load_cache(tf, product=product).bars
    if not bars:
        raise RuntimeError(f"No {tf.value} bars for {product}.")
    n = len(bars)
    in_bars, oos_bars = split_in_out_sample(bars)

    arms: list[tuple[str, float | None]] = [("baseline (shipped)", None)] + [
        (f"depth={d}", d) for d in depths
    ]

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
            f"\n      eqSharpe IS={es_in:+.3f}  OOS={es_oos:+.3f}"
            f"\n      consistency: {strat_cons:.0%} vs B&H {bench_cons:.0%} -> "
            f"{'pass' if consistent else 'FAIL'}"
            f"\n      IS exits: {_exit_mix(tr_in)}"
            f"\n      SHIP={ship}"
        )

    # ---- Fixed-config walk-forward (analysis A) for all arms -------------------
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
