"""A/B + walk-forward for the vol_expansion_ride follow-through confirmation knob.

The shipped ``vol_expansion_ride`` (squeeze→2×ATR burst + two-sided-burst filter) enters on
the burst bar itself. It is only 4/6 WF-fold-positive — the failing regimes (2023 raging bull,
early 2021) are where bursts mostly *reverse*. The ``confirm_bars=N`` knob delays entry until
the close N bars after the burst is beyond the burst-bar close in the ride direction (a
follow-through vote), aiming to drop the reversal-bursts that define those bad folds.

This compares the shipped default (``confirm_bars=None``) against ``confirm_bars=1`` and ``=2``
**on top of the current default config** (so skip_contra_extreme=1 is on in all arms). It uses
cycle.py's exact gate (IS/OOS equity Sharpe vs B&H + quarterly relative consistency) plus the
project's fixed-config 6-fold walk-forward — selection is on the WF folds, the lockbox OOS is
one-shot confirmation only (see docs/evaluation_criteria.md; do NOT pick on the OOS split).

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.vol_expansion_confirm_ab

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

# (label, extra kwargs over the shipped default). Baseline = shipped (confirm_bars=None).
ARMS: list[tuple[str, dict[str, object]]] = [
    ("baseline (shipped)", {}),
    ("confirm_bars=1", {"confirm_bars": 1}),
    ("confirm_bars=2", {"confirm_bars": 2}),
    ("confirm_bars=3", {"confirm_bars": 3}),
    ("confirm_bars=4", {"confirm_bars": 4}),
]


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


def _run(bars: list[Bar], kw: dict[str, object], size: float, rate: float) -> tuple[list[float], list[Trade]]:
    """Run one arm on a bar segment. Returns ``(equity_curve, trades)``."""
    strat = VolExpansionRideStrategy(**kw)  # type: ignore[arg-type]
    res = MultiSimulator(strat, size=size, fee_rate=rate).run(bars)
    return res.equity_curve, res.trades


def run_ab() -> None:
    """Run the IS/OOS gate A/B and the fixed-config walk-forward for every arm."""
    tf = Timeframe(os.environ.get("VE_TF", "1h"))
    product = os.environ.get("VE_PRODUCT", "GMO_BTC_JPY")
    k = int(os.environ.get("VE_FOLDS", 6))
    size = 0.001
    rate = DEFAULT_FEE_RATE
    ppy = (365 * 24 * 3600) / tf.seconds

    bars = load_cache(tf, product=product).bars
    if not bars:
        raise RuntimeError(f"No {tf.value} bars for {product}.")
    n = len(bars)
    in_bars, oos_bars = split_in_out_sample(bars)

    bench_in = annualized_sharpe_from_levels([b.close for b in in_bars], ppy, pct=True)
    bench_oos = annualized_sharpe_from_levels([b.close for b in oos_bars], ppy, pct=True)
    print(f"\n=== A/B GATE  ({product} {tf.value}, IS/OOS 80/20) ===")
    print(f"    B&H eqSharpe: IS={bench_in:+.3f}  OOS={bench_oos:+.3f}")
    for label, kw in ARMS:
        eq_in, tr_in = _run(in_bars, kw, size, rate)
        eq_oos, tr_oos = _run(oos_bars, kw, size, rate)
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
    for label, kw in ARMS:
        print(f"\n    {label}:")
        wins = beats = 0
        es_list = []
        for i in range(k):
            a, b = bounds[i], bounds[i + 1]
            eq, tr = _run(bars[a:b], kw, size, rate)
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
