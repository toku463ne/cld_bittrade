"""max_slots sweep for the combo_dp_ver shared book — find the capital sweet spot.

With 12 slots the combined book never contends (peak occupancy 11, 0 drops), so
slots > 12 change nothing. The open question is DOWNWARD capital efficiency: peak
exposure = ``max_slots × per-slot lot``, so a lower cap frees capital — worth it
only if the dropped (contended) entries were marginal. Occupancy is heavy-tailed
(IS mean 1.53, p95 4.0, max 11): most of the time few slots are used, but the
deep-book moments may be exactly the clustered-edge moments (density_pullback's
knob history: overlapping entries are *additive* edge; a single-position cap
halves OOS).

Per slot cap: 80/20 IS/OOS equity Sharpe + DD, trades kept vs uncapped (drops =
slot contention), occupancy, IS net PnL and **PnL per slot** (capital
efficiency), and the fixed-config 6-fold WF. Sweet spot = the smallest cap whose
eqSharpe and folds match the uncapped book.

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.combo_slots_sweep

Env knobs: ``DP_TF`` (1h), ``DP_PRODUCT`` (GMO_BTC_JPY), ``DP_FOLDS`` (6),
``COMBO_SLOT_GRID`` (comma list, default ``2,3,4,6,8,10,12``).
"""

from __future__ import annotations

import os

import numpy as np

from src.backtest.analysis.combo_dp_ver_probe import _max_dd, _occupancy
from src.backtest.metrics import annualized_sharpe_from_levels
from src.backtest.sign_benchmark import split_in_out_sample
from src.core.types import Bar, Timeframe, Trade
from src.data.cache import load_cache
from src.simulator import MultiSimulator
from src.simulator.simulator import DEFAULT_FEE_RATE
from src.strategy.combo_dp_ver import ComboDpVerStrategy


def _fold_bounds(n: int, k: int) -> list[int]:
    """``k+1`` evenly spaced indices splitting ``n`` bars into ``k`` folds."""
    return [round(i * n / k) for i in range(k + 1)]


def _run(bars: list[Bar], slots: int) -> tuple[list[float], list[Trade]]:
    """Run the combo at one slot cap. Returns ``(equity_curve, trades)``."""
    strat = ComboDpVerStrategy(max_slots=slots)
    res = MultiSimulator(strat, size=0.001, fee_rate=DEFAULT_FEE_RATE).run(bars)
    return res.equity_curve, res.trades


def run_sweep() -> None:
    """Slot-cap grid: gate Sharpes, contention, capital efficiency, 6-fold WF."""
    tf = Timeframe(os.environ.get("DP_TF", "1h"))
    product = os.environ.get("DP_PRODUCT", "GMO_BTC_JPY")
    k = int(os.environ.get("DP_FOLDS", 6))
    grid = [int(s) for s in os.environ.get("COMBO_SLOT_GRID", "2,3,4,6,8,10,12").split(",")]
    size = 0.001
    ppy = (365 * 24 * 3600) / tf.seconds

    bars = load_cache(tf, product=product).bars
    if not bars:
        raise RuntimeError(f"No {tf.value} bars for {product}.")
    n = len(bars)
    in_bars, oos_bars = split_in_out_sample(bars)
    bounds = _fold_bounds(n, k)

    print(f"\n=== combo_dp_ver max_slots sweep ({product} {tf.value}, 80/20 + {k}-fold WF) ===")
    print("    peak exposure = max_slots x per-slot lot; uncapped book peaks at 11 concurrent.")
    header = (
        f"    {'slots':>5} | {'IS eqSh':>8} {'OOS eqSh':>8} | {'IS DD':>6} | "
        f"{'n IS':>5} {'drop':>5} | {'occ max/p95':>11} | {'IS PnL':>8} {'PnL/slot':>8} | WF"
    )
    print(header)
    # Largest cap first = the contention-free reference for the "drop" column.
    n_ref: int | None = None
    for slots in sorted(grid, reverse=True):
        eq_in, tr_in = _run(in_bars, slots)
        eq_oos, tr_oos = _run(oos_bars, slots)
        es_in = annualized_sharpe_from_levels(eq_in, ppy)
        es_oos = annualized_sharpe_from_levels(eq_oos, ppy)
        dd_in = _max_dd(eq_in, size, in_bars)
        mx, p95, _ = _occupancy(tr_in)
        pnl_in = sum(t.pnl for t in tr_in)
        if n_ref is None:
            n_ref = len(tr_in)
        es_list = []
        for i in range(k):
            eq, _ = _run(bars[bounds[i]:bounds[i + 1]], slots)
            es_list.append(annualized_sharpe_from_levels(eq, ppy))
        wins = sum(1 for e in es_list if e > 0)
        folds = " ".join(f"{e:+.2f}" for e in es_list)
        print(
            f"    {slots:>5} | {es_in:+8.3f} {es_oos:+8.3f} | {dd_in:6.3f} | "
            f"{len(tr_in):>5} {n_ref - len(tr_in):>5} | {mx:>4}/{p95:5.1f} | {pnl_in:8.0f} "
            f"{pnl_in / slots:8.0f} | {wins}/{k} [{folds}] mean={np.mean(es_list):+.2f}"
        )


if __name__ == "__main__":
    from src.config import get_settings
    from src.logging_setup import configure_logging

    configure_logging(get_settings().log_level)
    run_sweep()
