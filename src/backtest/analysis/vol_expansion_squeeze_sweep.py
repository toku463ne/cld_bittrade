"""2D sweep of vol_expansion_ride's squeeze depth × expansion magnitude.

The shipped strategy triggers on squeeze (prior-ATR trailing rank <= ``squeeze_rank_max=0.25``)
→ expansion (TR >= ``expand_mult=2.0`` × prior ATR). The open problem is regime-robustness
(only 4/6 WF folds). Two structural axes that might separate directional bursts from reversal
bursts WITHOUT a new knob:
  * **squeeze depth** — a deeper squeeze (lower rank) has more pent-up energy → cleaner break.
  * **expansion magnitude** — a bigger burst (higher mult) may be more committed.

Unlike a single-value test, a sweep guards against the ``confirm_bars`` knife-edge: we accept
a cell only if a **smooth neighbourhood** of cells improves on the shipped (0.25, 2.0) cell,
not one lucky cell aligned with the fold boundaries. All cells keep the shipped
``skip_contra_extreme=1``. Selection is on the WF folds; the IS/OOS gate is one-shot confirmation.

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.vol_expansion_squeeze_sweep

Env knobs: ``VE_TF`` (1h), ``VE_PRODUCT`` (GMO_BTC_JPY), ``VE_FOLDS`` (6).
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

SQUEEZE = [0.10, 0.15, 0.20, 0.25, 0.30]  # 0.25 = shipped
EXPAND = [2.0, 2.5, 3.0]                   # 2.0 = shipped
SHIPPED = (0.25, 2.0)


def _bh_sharpe(bars: list[Bar], ppy: float) -> float:
    if len(bars) < 3:
        return 0.0
    c = np.array([b.close for b in bars], dtype=float)
    r = np.diff(c) / c[:-1]
    sd = float(r.std(ddof=1))
    return float(r.mean() / sd * np.sqrt(ppy)) if sd > 0 else 0.0


def _fold_bounds(n: int, k: int) -> list[int]:
    return [round(i * n / k) for i in range(k + 1)]


def _run(bars: list[Bar], sq: float, ex: float, size: float, rate: float) -> tuple[list[float], list[Trade]]:
    strat = VolExpansionRideStrategy(squeeze_rank_max=sq, expand_mult=ex)
    res = MultiSimulator(strat, size=size, fee_rate=rate).run(bars)
    return res.equity_curve, res.trades


def run_sweep() -> None:
    """Sweep (squeeze_rank_max × expand_mult); print WF + IS/OOS grids."""
    tf = Timeframe(os.environ.get("VE_TF", "1h"))
    product = os.environ.get("VE_PRODUCT", "GMO_BTC_JPY")
    k = int(os.environ.get("VE_FOLDS", 6))
    size, rate = 0.001, DEFAULT_FEE_RATE
    ppy = (365 * 24 * 3600) / tf.seconds

    bars = load_cache(tf, product=product).bars
    if not bars:
        raise RuntimeError(f"No {tf.value} bars for {product}.")
    n = len(bars)
    in_bars, oos_bars = split_in_out_sample(bars)
    bench_in = annualized_sharpe_from_levels([b.close for b in in_bars], ppy, pct=True)
    bench_oos = annualized_sharpe_from_levels([b.close for b in oos_bars], ppy, pct=True)
    bounds = _fold_bounds(n, k)
    bh_by_fold = [_bh_sharpe(bars[bounds[i]:bounds[i + 1]], ppy) for i in range(k)]

    def cell(sq: float, ex: float) -> dict[str, float]:
        eq_in, tr_in = _run(in_bars, sq, ex, size, rate)
        eq_oos, tr_oos = _run(oos_bars, sq, ex, size, rate)
        es_in = annualized_sharpe_from_levels(eq_in, ppy)
        es_oos = annualized_sharpe_from_levels(eq_oos, ppy)
        cons, bcons = _quarter_consistency(tr_in, in_bars)
        ship = float((es_in >= bench_in) and (es_oos >= bench_oos) and (cons >= bcons))
        wins = 0
        es_list = []
        for i in range(k):
            a, b = bounds[i], bounds[i + 1]
            eq, _tr = _run(bars[a:b], sq, ex, size, rate)
            es = annualized_sharpe_from_levels(eq, ppy)
            es_list.append(es)
            if es > 0:
                wins += 1
        return {
            "n_in": len(tr_in), "n_oos": len(tr_oos), "es_in": es_in, "es_oos": es_oos,
            "wins": wins, "wf_mean": float(np.mean(es_list)), "ship": ship,
        }

    print(f"\n=== SQUEEZE × EXPAND sweep ({product} {tf.value}); shipped cell = {SHIPPED} ===")
    print(f"    B&H eqSharpe: IS={bench_in:+.3f}  OOS={bench_oos:+.3f}; WF B&H folds+ = "
          f"{sum(1 for x in bh_by_fold if x > 0)}/{k}")
    grid: dict[tuple[float, float], dict[str, float]] = {}
    for ex in EXPAND:
        for sq in SQUEEZE:
            grid[(sq, ex)] = cell(sq, ex)

    # WF folds-positive grid (the robustness view) + WF mean.
    for metric, label, fmt in (("wins", "WF folds-positive (/%d)" % k, "{:.0f}"),
                               ("wf_mean", "WF mean eqSharpe", "{:+.2f}"),
                               ("es_oos", "OOS eqSharpe (one-shot)", "{:+.2f}"),
                               ("es_in", "IS eqSharpe", "{:+.2f}")):
        print(f"\n    {label}:   (rows=expand_mult, cols=squeeze_rank_max)")
        print("      ex\\sq  " + "  ".join(f"{sq:>6.2f}" for sq in SQUEEZE))
        for ex in EXPAND:
            cells = []
            for sq in SQUEEZE:
                v = fmt.format(grid[(sq, ex)][metric])
                mark = "*" if (sq, ex) == SHIPPED else " "
                cells.append(f"{v:>6}{mark}")
            print(f"      {ex:>4.1f}   " + " ".join(cells))

    # ship-gate + sample-size grid
    print("\n    ship-gate (1=pass) / IS n:   (rows=expand_mult, cols=squeeze_rank_max)")
    print("      ex\\sq  " + "  ".join(f"{sq:>7.2f}" for sq in SQUEEZE))
    for ex in EXPAND:
        cells = []
        for sq in SQUEEZE:
            g = grid[(sq, ex)]
            mark = "*" if (sq, ex) == SHIPPED else ""
            cells.append(f"{int(g['ship'])}/{g['n_in']:>3.0f}{mark}")
        print(f"      {ex:>4.1f}   " + " ".join(f"{c:>8}" for c in cells))


if __name__ == "__main__":
    from src.config import get_settings
    from src.logging_setup import configure_logging

    configure_logging(get_settings().log_level)
    run_sweep()
