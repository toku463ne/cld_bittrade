"""Strategy C″: invalidation_depth sweep for density_pullback on ETH, IS-WF only.

The failed-breakout invalidation exit was REJECTED on BTC (2026-06-10): depth >= 1.0
was a literal no-op (the zs stop always fired first) and depth < 1.0 clipped the
dip-then-run trail winners without cutting the stop bleed. This sweep asks whether
ETH's different box/zs geometry changes that verdict — selection strictly inside the
ETH lockbox IS window (pre-2025-04-01) on a fixed-config 6-fold walk-forward, with
the mechanism columns (stop count/bleed, trail-winner count) that decided the BTC
case. Baseline = current registry defaults (incl. max_base_bars=64). See the C″
pre-registration in ``docs/research/study_plan_new_strategies.md``.

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.density_pullback_eth_invalidation_sweep

Env knobs: ``DP_PRODUCT`` (GMO_ETH_JPY), ``DP_FOLDS`` (6),
``DP_DEPTHS`` (comma list, default ``0.25,0.5,0.75,1.0,1.25``).
"""

from __future__ import annotations

import os

import numpy as np

from src.backtest.metrics import annualized_sharpe_from_levels
from src.backtest.sign_benchmark import split_lockbox
from src.core.types import Bar, ExitReason, Timeframe, Trade
from src.data.cache import load_cache
from src.simulator import MultiSimulator
from src.simulator.simulator import DEFAULT_FEE_RATE
from src.strategy.density_pullback import DensityPullbackStrategy


def _fold_bounds(n: int, k: int) -> list[int]:
    """``k+1`` evenly spaced indices splitting ``n`` bars into ``k`` folds."""
    return [round(i * n / k) for i in range(k + 1)]


def _run(bars: list[Bar], depth: float | None) -> tuple[list[float], list[Trade]]:
    """Run one arm on a bar segment. Returns ``(equity_curve, trades)``."""
    strat = DensityPullbackStrategy(invalidation_depth=depth)
    res = MultiSimulator(strat, size=0.001, fee_rate=DEFAULT_FEE_RATE).run(bars)
    return res.equity_curve, res.trades


def _mechanism(trades: list[Trade]) -> str:
    """Stop count + bleed and trail-winner count — the columns that decided BTC."""
    stops = [t.return_pct for t in trades if t.exit_reason is ExitReason.STOP_LOSS]
    trails = sum(1 for t in trades if t.exit_reason is ExitReason.TRAIL_STOP)
    bleed = float(np.sum(stops)) if stops else 0.0
    return f"stops={len(stops)} bleed={bleed:+.2f} trails={trails}"


def run_sweep() -> None:
    """invalidation_depth grid on the ETH lockbox-IS window, 6-fold WF + mechanism."""
    tf = Timeframe("1h")
    product = os.environ.get("DP_PRODUCT", "GMO_ETH_JPY")
    k = int(os.environ.get("DP_FOLDS", 6))
    depths = [float(x) for x in os.environ.get("DP_DEPTHS", "0.25,0.5,0.75,1.0,1.25").split(",")]
    ppy = 365.0 * 24

    bars = load_cache(tf, product=product).bars
    if not bars:
        raise RuntimeError(f"No bars for {product}.")
    is_bars, _oos = split_lockbox(bars)  # selection uses the IS window ONLY
    n = len(is_bars)
    bounds = _fold_bounds(n, k)

    print(f"\n=== density_pullback invalidation_depth sweep on {product} lockbox-IS ONLY ===")
    print(f"    IS window: {is_bars[0].timestamp:%Y-%m-%d} -> {is_bars[-1].timestamp:%Y-%m-%d}"
          f"  ({n} bars); baseline = registry defaults (incl. max_base_bars=64).")
    arms: list[tuple[str, float | None]] = [("baseline", None)] + [
        (f"depth={d}", d) for d in depths
    ]
    for label, arm in arms:
        eq_is, tr_is = _run(is_bars, arm)
        es_is = annualized_sharpe_from_levels(eq_is, ppy)
        es_list = []
        for i in range(k):
            eq, _ = _run(is_bars[bounds[i]:bounds[i + 1]], arm)
            es_list.append(annualized_sharpe_from_levels(eq, ppy))
        wins = sum(1 for e in es_list if e > 0)
        folds = " ".join(f"{e:+.2f}" for e in es_list)
        print(
            f"    {label:11} | IS eqSh={es_is:+.3f} n={len(tr_is):<3} | "
            f"{_mechanism(tr_is)} | WF {wins}/{k} [{folds}] mean={np.mean(es_list):+.2f}"
        )


if __name__ == "__main__":
    from src.config import get_settings
    from src.logging_setup import configure_logging

    configure_logging(get_settings().log_level)
    run_sweep()
