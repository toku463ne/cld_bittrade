"""Shared-book probe: density_pullback + vol_expansion_ride on 12 common slots.

density_pullback rarely fills its 12-slot book (observed peak 10, typically far
less) and vol_expansion_ride is low-turnover (~236 lockbox trades) with low
correlation to it (cDP +0.10) — so a SHARED 12-slot book should raise slot
utilisation (more trades on the same peak capital) and smooth the equity path
(diversification), unless slot contention at overlap moments costs more than the
diversification pays.

Both strategies use the *identical* inherited ride-exit machinery
(``RandomHedgeStrategy.dynamic_exit`` ratchet with ``recalc_bars=48``; the trail
band derives from each position's own ``sl_price``, set per-signal via
``exit_config``), so one merged book reproduces each strategy's exits exactly.
Known pre-existing caveat: the ratchet keys state by ``(entry_idx, side)``, so two
same-bar same-side fills share trail state — already true within shipped
density_pullback (multiple limit fills on one bar); the merge only adds rare
cross-strategy occurrences.

Arms:
    dp alone (12 slots) | ver alone (uncapped 50) | combo (shared 12)
    + "sum of separate books" control (dp curve + ver curve, NO slot sharing —
      the upper bound that uses MORE peak capital).

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.combo_dp_ver_probe

Env knobs: ``DP_TF`` (1h), ``DP_PRODUCT`` (GMO_BTC_JPY), ``DP_FOLDS`` (6),
``COMBO_SLOTS`` (12).
"""

from __future__ import annotations

import os
from datetime import datetime

import numpy as np

from src.backtest.cycle import _quarter_consistency
from src.backtest.metrics import annualized_sharpe_from_levels
from src.backtest.sign_benchmark import split_in_out_sample
from src.core.types import Bar, Signal, Timeframe, Trade
from src.data.cache import load_cache
from src.simulator import MultiSimulator
from src.simulator.simulator import DEFAULT_FEE_RATE
from src.strategy.density_pullback import DensityPullbackStrategy
from src.strategy.random_hedge import RandomHedgeStrategy
from src.strategy.vol_expansion_ride import VolExpansionRideStrategy


class ComboDpVerStrategy(RandomHedgeStrategy):
    """Merged signal stream of density_pullback + vol_expansion_ride, one book.

    Exits are the shared inherited ratchet (``recalc_bars=48``) — identical to
    what each sub-strategy runs on its own, since the trail band is per-position
    (from the signal's ``exit_config``), not per-strategy.
    """

    name = "combo_dp_ver"

    def __init__(self, *, max_slots: int = 12) -> None:
        super().__init__(recalc_bars=48)
        self.max_slots = max_slots
        self._dp = DensityPullbackStrategy()
        self._ver = VolExpansionRideStrategy()

    def precompute_multi(self, bars: list[Bar]) -> dict[datetime, list[Signal]] | None:  # noqa: D102
        out: dict[datetime, list[Signal]] = {}
        for sub in (self._dp, self._ver):
            sub.reset()
            for ts, sigs in (sub.precompute_multi(bars) or {}).items():
                out.setdefault(ts, []).extend(sigs)
        return out


def _fold_bounds(n: int, k: int) -> list[int]:
    """``k+1`` evenly spaced indices splitting ``n`` bars into ``k`` folds."""
    return [round(i * n / k) for i in range(k + 1)]


def _occupancy(trades: list[Trade]) -> tuple[int, float, float]:
    """(max, p95, mean) concurrent open positions over the trades' event path."""
    if not trades:
        return 0, 0.0, 0.0
    events = sorted(
        [(t.entry_time, 1) for t in trades] + [(t.exit_time, -1) for t in trades]
    )
    cur, path = 0, []
    for _, d in events:
        cur += d
        path.append(cur)
    arr = np.array(path)
    return int(arr.max()), float(np.percentile(arr, 95)), float(arr.mean())


def _max_dd(eq: list[float], size: float, bars: list[Bar]) -> float:
    """Max drawdown of the mark-to-market equity path, fraction of one-slot notional."""
    if not eq or not bars:
        return 0.0
    notional = size * bars[0].close
    arr = np.array(eq, dtype=float) / notional
    peak = np.maximum.accumulate(arr)
    return float(np.max(peak - arr))


def _strat(arm: str, combo_slots: int) -> RandomHedgeStrategy:
    if arm == "dp":
        return DensityPullbackStrategy()
    if arm == "ver":
        return VolExpansionRideStrategy()
    return ComboDpVerStrategy(max_slots=combo_slots)


def _run(bars: list[Bar], arm: str, combo_slots: int) -> tuple[list[float], list[Trade]]:
    res = MultiSimulator(_strat(arm, combo_slots), size=0.001, fee_rate=DEFAULT_FEE_RATE).run(bars)
    return res.equity_curve, res.trades


def run_probe() -> None:
    """Gate-style IS/OOS comparison + occupancy + 6-fold WF for all arms."""
    tf = Timeframe(os.environ.get("DP_TF", "1h"))
    product = os.environ.get("DP_PRODUCT", "GMO_BTC_JPY")
    k = int(os.environ.get("DP_FOLDS", 6))
    combo_slots = int(os.environ.get("COMBO_SLOTS", 12))
    size = 0.001
    ppy = (365 * 24 * 3600) / tf.seconds

    bars = load_cache(tf, product=product).bars
    if not bars:
        raise RuntimeError(f"No {tf.value} bars for {product}.")
    n = len(bars)
    in_bars, oos_bars = split_in_out_sample(bars)
    bench_in = annualized_sharpe_from_levels([b.close for b in in_bars], ppy, pct=True)
    bench_oos = annualized_sharpe_from_levels([b.close for b in oos_bars], ppy, pct=True)

    print(f"\n=== SHARED-BOOK PROBE ({product} {tf.value}, combo slots={combo_slots}) ===")
    print(f"    B&H eqSharpe: IS={bench_in:+.3f}  OOS={bench_oos:+.3f}")

    # arm -> (eq_in, eq_oos, tr_in, tr_oos)
    results: dict[str, tuple[list[float], list[float], list[Trade], list[Trade]]] = {}
    for arm in ("dp", "ver", "combo"):
        eq_in, tr_in = _run(in_bars, arm, combo_slots)
        eq_oos, tr_oos = _run(oos_bars, arm, combo_slots)
        es_in = annualized_sharpe_from_levels(eq_in, ppy)
        es_oos = annualized_sharpe_from_levels(eq_oos, ppy)
        cons, bench_cons = _quarter_consistency(tr_in, in_bars)
        mx, p95, mean = _occupancy(tr_in)
        results[arm] = (eq_in, eq_oos, tr_in, tr_oos)
        print(
            f"\n    {arm}:"
            f"\n      n_trades: IS={len(tr_in)}  OOS={len(tr_oos)}"
            f"\n      eqSharpe IS={es_in:+.3f}  OOS={es_oos:+.3f}"
            f"\n      eqDD     IS={_max_dd(eq_in, size, in_bars):.3f}"
            f"  OOS={_max_dd(eq_oos, size, oos_bars):.3f}"
            f"\n      IS occupancy: max={mx} p95={p95:.1f} mean={mean:.2f}"
            f"\n      consistency: {cons:.0%} vs B&H {bench_cons:.0%}"
        )

    # Sum-of-separate-books control (no slot sharing; more peak capital).
    dp_eq_in, dp_eq_oos, dp_tr_in, _ = results["dp"]
    ver_eq_in, ver_eq_oos, ver_tr_in, _ = results["ver"]
    eq_in_sum = [a + b for a, b in zip(dp_eq_in, ver_eq_in)]
    eq_oos_sum = [a + b for a, b in zip(dp_eq_oos, ver_eq_oos)]
    tr_in_sum = list(dp_tr_in) + list(ver_tr_in)
    cons_sum, bench_cons = _quarter_consistency(tr_in_sum, in_bars)
    n_in_sep = len(dp_tr_in) + len(ver_tr_in)
    n_in_combo = len(results["combo"][2])
    print(
        f"\n    sum-of-books control (dp+ver, separate slots):"
        f"\n      eqSharpe IS={annualized_sharpe_from_levels(eq_in_sum, ppy):+.3f}"
        f"  OOS={annualized_sharpe_from_levels(eq_oos_sum, ppy):+.3f}"
        f"\n      eqDD     IS={_max_dd(eq_in_sum, size, in_bars):.3f}"
        f"  OOS={_max_dd(eq_oos_sum, size, oos_bars):.3f}"
        f"\n      consistency: {cons_sum:.0%} vs B&H {bench_cons:.0%}"
        f"\n      slot-contention drops (IS): {n_in_sep - n_in_combo} of {n_in_sep} trades"
    )

    # ---- Fixed-config walk-forward ------------------------------------------
    bounds = _fold_bounds(n, k)
    print(f"\n=== FIXED-CONFIG WALK-FORWARD across {k} folds ===")
    for arm in ("dp", "ver", "combo"):
        es_list = []
        ns = []
        for i in range(k):
            eq, tr = _run(bars[bounds[i]:bounds[i + 1]], arm, combo_slots)
            es_list.append(annualized_sharpe_from_levels(eq, ppy))
            ns.append(len(tr))
        wins = sum(1 for e in es_list if e > 0)
        folds = " ".join(f"{e:+.2f}" for e in es_list)
        print(f"    {arm:6}: {wins}/{k} +ve [{folds}]  mean={np.mean(es_list):+.2f}  n={ns}")


if __name__ == "__main__":
    from src.config import get_settings
    from src.logging_setup import configure_logging

    configure_logging(get_settings().log_level)
    run_probe()
