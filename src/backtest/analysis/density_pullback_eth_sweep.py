"""ETH-tuned density_pullback: max_band_pct sweep on ETH in-sample WF ONLY.

Strategy C′ (see ``docs/research/study_plan_new_strategies.md`` for the full
pre-registration). The fixed ``max_band_pct=0.03`` tightness gate is BTC-scaled:
it passes 31% of BTC bars but only 17% of ETH bars (ETH vol ~76% vs 56% ann.), so
on ETH it selects a deeper-tail regime and fires 40% less. This sweep re-scales
that single knob FOR ETH, selecting strictly inside the ETH lockbox IS window
(pre-2025-04-01) on a fixed-config 6-fold walk-forward — the lockbox OOS is not
touched here (one separate look is allowed for the adopted config only).

Adoption bar (pre-registered): a smooth >=2-adjacent-cell improvement region,
IS-WF folds >= baseline's and mean eqSharpe up, fires rising toward a BTC-like
rate.

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.density_pullback_eth_sweep

Env knobs: ``DP_PRODUCT`` (GMO_ETH_JPY), ``DP_FOLDS`` (6),
``DP_BANDPCT`` (comma list, default ``0.03,0.035,0.04,0.045,0.05,0.06``).
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
from src.strategy.density_pullback import DensityPullbackStrategy


def _fold_bounds(n: int, k: int) -> list[int]:
    """``k+1`` evenly spaced indices splitting ``n`` bars into ``k`` folds."""
    return [round(i * n / k) for i in range(k + 1)]


def _run(bars: list[Bar], band_pct: float) -> tuple[list[float], list[Trade]]:
    """Run one arm on a bar segment. Returns ``(equity_curve, trades)``."""
    strat = DensityPullbackStrategy(max_band_pct=band_pct)
    res = MultiSimulator(strat, size=0.001, fee_rate=DEFAULT_FEE_RATE).run(bars)
    return res.equity_curve, res.trades


def run_sweep() -> None:
    """max_band_pct grid on the ETH lockbox IS window, 6-fold WF + IS summary."""
    tf = Timeframe("1h")
    product = os.environ.get("DP_PRODUCT", "GMO_ETH_JPY")
    k = int(os.environ.get("DP_FOLDS", 6))
    grid = [float(x) for x in os.environ.get("DP_BANDPCT", "0.03,0.035,0.04,0.045,0.05,0.06").split(",")]
    ppy = 365.0 * 24

    bars = load_cache(tf, product=product).bars
    if not bars:
        raise RuntimeError(f"No bars for {product}.")
    is_bars, _oos = split_lockbox(bars)  # selection uses the IS window ONLY
    n = len(is_bars)
    bounds = _fold_bounds(n, k)
    bh_is = annualized_sharpe_from_levels([b.close for b in is_bars], ppy, pct=True)

    print(f"\n=== density_pullback max_band_pct sweep on {product} lockbox-IS ONLY ===")
    print(f"    IS window: {is_bars[0].timestamp:%Y-%m-%d} -> {is_bars[-1].timestamp:%Y-%m-%d}"
          f"  ({n} bars; ETH B&H IS eqSh {bh_is:+.2f}); lockbox OOS NOT touched here.")
    print(f"    {'band%':>6} | {'IS eqSh':>8} {'n IS':>5} | WF-IS folds  mean")
    for bp in grid:
        eq_is, tr_is = _run(is_bars, bp)
        es_is = annualized_sharpe_from_levels(eq_is, ppy)
        es_list = []
        for i in range(k):
            eq, _ = _run(is_bars[bounds[i]:bounds[i + 1]], bp)
            es_list.append(annualized_sharpe_from_levels(eq, ppy))
        wins = sum(1 for e in es_list if e > 0)
        folds = " ".join(f"{e:+.2f}" for e in es_list)
        mark = " <-- BTC default" if abs(bp - 0.03) < 1e-9 else ""
        print(
            f"    {bp:>6.3f} | {es_is:+8.3f} {len(tr_is):>5} | {wins}/{k} [{folds}]"
            f"  mean={np.mean(es_list):+.2f}{mark}"
        )


if __name__ == "__main__":
    from src.config import get_settings
    from src.logging_setup import configure_logging

    configure_logging(get_settings().log_level)
    run_sweep()
