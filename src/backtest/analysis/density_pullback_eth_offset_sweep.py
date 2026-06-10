"""Limit-offset sweep for density_pullback_eth on ETH, lockbox-IS WF only.

The last untested placement dimension: the pullback limit rests exactly at the
broken edge (``limit_offset=0``). Positive offset = INSIDE the box (deeper
concession, better price, fewer fills); negative = OUTSIDE (shallower, more
fills, worse price). Low prior — the edge is the natural level — and a 3-cell
sweep cannot establish smoothness, so the pre-registered bar is deliberately
high: adopt only on a LARGE improvement (WF mean +0.2 or more over baseline AND
folds not worse), which would then trigger a finer plateau grid before any
default change. Anything less = record and keep 0.0.

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.density_pullback_eth_offset_sweep

Env knobs: ``DP_PRODUCT`` (GMO_ETH_JPY), ``DP_FOLDS`` (6),
``DP_OFFSETS`` (comma list, default ``-0.1,0.0,0.1``).
"""

from __future__ import annotations

import os

import numpy as np

from src.backtest.metrics import annualized_sharpe_from_levels
from src.backtest.sign_benchmark import split_lockbox
from src.core.types import Bar, Timeframe, Trade
from src.data.cache import load_cache
from src.simulator import MultiSimulator
from src.simulator.simulator import DEFAULT_FEE_RATE
from src.strategy.density_pullback import DensityPullbackEthStrategy


def _fold_bounds(n: int, k: int) -> list[int]:
    """``k+1`` evenly spaced indices splitting ``n`` bars into ``k`` folds."""
    return [round(i * n / k) for i in range(k + 1)]


def _run(bars: list[Bar], off: float) -> tuple[list[float], list[Trade]]:
    """Run one arm on a bar segment. Returns ``(equity_curve, trades)``."""
    strat = DensityPullbackEthStrategy(limit_offset=off)
    res = MultiSimulator(strat, size=0.001, fee_rate=DEFAULT_FEE_RATE).run(bars)
    return res.equity_curve, res.trades


def run_sweep() -> None:
    """limit_offset grid on the ETH lockbox-IS window, 6-fold WF."""
    tf = Timeframe("1h")
    product = os.environ.get("DP_PRODUCT", "GMO_ETH_JPY")
    k = int(os.environ.get("DP_FOLDS", 6))
    offsets = [float(x) for x in os.environ.get("DP_OFFSETS", "-0.1,0.0,0.1").split(",")]
    ppy = 365.0 * 24

    bars = load_cache(tf, product=product).bars
    if not bars:
        raise RuntimeError(f"No bars for {product}.")
    is_bars, _oos = split_lockbox(bars)  # selection uses the IS window ONLY
    n = len(is_bars)
    bounds = _fold_bounds(n, k)

    print(f"\n=== density_pullback_eth limit_offset sweep on {product} lockbox-IS ONLY ===")
    print("    +inside box (deeper/better price, fewer fills) | -outside (more fills, worse price)")
    for off in offsets:
        eq_is, tr_is = _run(is_bars, off)
        es_is = annualized_sharpe_from_levels(eq_is, ppy)
        es_list = []
        for i in range(k):
            eq, _ = _run(is_bars[bounds[i]:bounds[i + 1]], off)
            es_list.append(annualized_sharpe_from_levels(eq, ppy))
        wins = sum(1 for e in es_list if e > 0)
        folds = " ".join(f"{e:+.2f}" for e in es_list)
        mark = " <-- shipped (edge)" if off == 0.0 else ""
        print(
            f"    off={off:+.2f} | IS eqSh={es_is:+.3f} n={len(tr_is):<3} | "
            f"WF {wins}/{k} [{folds}] mean={np.mean(es_list):+.2f}{mark}"
        )


if __name__ == "__main__":
    from src.config import get_settings
    from src.logging_setup import configure_logging

    configure_logging(get_settings().log_level)
    run_sweep()
