"""Cost-model robustness of the density_pullback ratchet (recalc_bars × cost basis).

``recalc_bars=48`` (the slow-ratchet sweet spot) was walk-forward-tuned under the
CALM cost model (2 bp/side, no swap, no burst spread). The swap-cost diagnostic
(2026-06-10) refuted the "swap leaks on long trail rides" worry — the 48–96h trail
winners pay the most swap but it is only ~3.4% of their PnL — but the realistic
basis (``--bitflyer-realistic``: swap 0.04%/day + 5× burst spread on stop exits)
still reshapes per-trade economics (stop buckets get 11–19% worse). This sweep
asks one pre-registered question: **does the ratchet optimum MOVE under the
realistic basis?** If the argmax stays at 48 on both bases, the exit tuning is
cost-model-robust and no change is made; if it moves, the exit was tuned to the
wrong cost model (a silent leak).

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.density_pullback_recalc_cost_ab

Env knobs: ``DP_TF`` (1h), ``DP_PRODUCT`` (GMO_BTC_JPY), ``DP_FOLDS`` (6),
``DP_RECALC`` (comma list, default ``24,36,48,72,96``).
"""

from __future__ import annotations

import os

import numpy as np

from src.backtest.metrics import annualized_sharpe_from_levels
from src.backtest.sign_benchmark import split_in_out_sample
from src.core.types import Bar, Timeframe, Trade
from src.data.cache import load_cache
from src.simulator import MultiSimulator
from src.simulator.simulator import DEFAULT_FEE_RATE
from src.strategy.density_pullback import DensityPullbackStrategy

# (label, daily_swap_rate, burst_cost_mult)
BASES: list[tuple[str, float, float]] = [
    ("calm", 0.0, 1.0),
    ("bitflyer-realistic", 0.0004, 5.0),
]


def _fold_bounds(n: int, k: int) -> list[int]:
    """``k+1`` evenly spaced indices splitting ``n`` bars into ``k`` folds."""
    return [round(i * n / k) for i in range(k + 1)]


def _run(
    bars: list[Bar], recalc: int, swap: float, burst: float
) -> tuple[list[float], list[Trade]]:
    """Run one (recalc, cost-basis) cell. Returns ``(equity_curve, trades)``."""
    strat = DensityPullbackStrategy(recalc_bars=recalc)  # type: ignore[arg-type]
    res = MultiSimulator(
        strat, size=0.001, fee_rate=DEFAULT_FEE_RATE,
        daily_swap_rate=swap, burst_cost_mult=burst,
    ).run(bars)
    return res.equity_curve, res.trades


def run_sweep() -> None:
    """recalc_bars × cost-basis grid: 80/20 gate Sharpes + fixed-config WF."""
    tf = Timeframe(os.environ.get("DP_TF", "1h"))
    product = os.environ.get("DP_PRODUCT", "GMO_BTC_JPY")
    k = int(os.environ.get("DP_FOLDS", 6))
    recalcs = [int(d) for d in os.environ.get("DP_RECALC", "24,36,48,72,96").split(",")]
    ppy = (365 * 24 * 3600) / tf.seconds

    bars = load_cache(tf, product=product).bars
    if not bars:
        raise RuntimeError(f"No {tf.value} bars for {product}.")
    n = len(bars)
    in_bars, oos_bars = split_in_out_sample(bars)
    bounds = _fold_bounds(n, k)

    for base_label, swap, burst in BASES:
        print(f"\n=== cost basis: {base_label} (swap={swap}, burst_mult={burst}) ===")
        print(f"    {'recalc':>7} | {'IS eqSh':>8} {'OOS eqSh':>8} | WF folds  mean")
        for rc in recalcs:
            eq_in, _ = _run(in_bars, rc, swap, burst)
            eq_oos, _ = _run(oos_bars, rc, swap, burst)
            es_in = annualized_sharpe_from_levels(eq_in, ppy)
            es_oos = annualized_sharpe_from_levels(eq_oos, ppy)
            es_list = []
            for i in range(k):
                a, b = bounds[i], bounds[i + 1]
                eq, _ = _run(bars[a:b], rc, swap, burst)
                es_list.append(annualized_sharpe_from_levels(eq, ppy))
            wins = sum(1 for e in es_list if e > 0)
            folds = " ".join(f"{e:+.2f}" for e in es_list)
            mark = " <-- shipped" if rc == 48 else ""
            print(
                f"    {rc:>7} | {es_in:+8.3f} {es_oos:+8.3f} | {wins}/{k} "
                f"[{folds}]  {np.mean(es_list):+.2f}{mark}"
            )


if __name__ == "__main__":
    from src.config import get_settings
    from src.logging_setup import configure_logging

    configure_logging(get_settings().log_level)
    run_sweep()
