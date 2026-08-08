"""Price the take-profit fidelity gap: intrabar target vs the venue's real exit.

GMO permits exactly **one resting settle order per 建玉** — the first reserves the whole
position. Confirmed live 2026-08-06 07:05 (BTC pos 289850034): the protective STOP was
accepted and the take-profit that followed returned ``ERR-200 "There are open positions
that the settlement quantity exceeds the settable quantity"``.

So the OCO pair the backtest assumes does not exist here. Protection takes the slot, and
a target touch is therefore **not** filled intrabar: the simulator drops the position at
the bar close and the hourly reconcile market-closes it ~5 minutes into the next bar. The
realistic fill is that bar's **open** (the project's standing two-bar fill convention),
not the target.

This A/B re-runs the shipped books with ``MultiSimulator(tp_at_next_open=True)`` and
reports what the deviation costs. The deferred bar also keeps the slot occupied, exactly
as live — so a blocked entry shows up too, not just the worse fill.

Read the **eqSharpe** columns for the ship gate and **PnL** for the size of the bleed.
``n TP`` is the exposure: books whose targets rarely fire cannot be hurt much.

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.tp_next_open_ab

Env knobs: ``DP_TF`` (1h), ``DP_FOLDS`` (6), ``TP_BOOKS``
(``name:product`` comma list, default the two live books).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from src.backtest.metrics import annualized_sharpe_from_levels
from src.backtest.sign_benchmark import split_in_out_sample
from src.core.types import Bar, ExitReason, Timeframe, Trade
from src.data.cache import load_cache
from src.execution.gmo_client import LEVERAGE_MIN_SIZE
from src.simulator import MultiSimulator
from src.simulator.simulator import DEFAULT_FEE_RATE
from src.strategy.registry import get_strategy

DEFAULT_BOOKS = "density_pullback:GMO_BTC_JPY,density_pullback_xrp:GMO_XRP_JPY"


def _fold_bounds(n: int, k: int) -> list[int]:
    """``k+1`` evenly spaced indices splitting ``n`` bars into ``k`` folds."""
    return [round(i * n / k) for i in range(k + 1)]


def _max_dd(equity: list[float]) -> float:
    """Max peak-to-trough drop of an equity path, in JPY."""
    peak = -float("inf")
    dd = 0.0
    for v in equity:
        peak = max(peak, v)
        dd = max(dd, peak - v)
    return dd


def _lot(product: str) -> float:
    """The venue's real minimum lot for a product (XRP is 10, not 0.001)."""
    return LEVERAGE_MIN_SIZE.get(product.replace("GMO_", ""), 0.001)


def _run(name: str, bars: list[Bar], *, venue: bool,
         size: float = 0.001) -> tuple[list[float], list[Trade]]:
    """Run one book. ``venue=True`` applies the one-settle-order-per-position reality."""
    res = MultiSimulator(get_strategy(name), size=size, fee_rate=DEFAULT_FEE_RATE,
                         tp_at_next_open=venue).run(bars)
    return res.equity_curve, res.trades


@dataclass(slots=True)
class _Row:
    """One arm of the A/B (baseline or venue-real) over one book."""

    es_in: float
    es_oos: float
    dd_in: float
    pnl_in: float
    pnl_oos: float
    n_in: int
    folds: list[float]
    tr_in: list[Trade]


def _tp_stats(base: list[Trade], venue: list[Trade]) -> tuple[int, float, float]:
    """(n TP exits in the baseline, baseline TP PnL, venue TP PnL) — the affected slice."""
    b = [t for t in base if t.exit_reason is ExitReason.TAKE_PROFIT]
    v = [t for t in venue if t.exit_reason is ExitReason.TAKE_PROFIT]
    return len(b), sum(t.pnl for t in b), sum(t.pnl for t in v)


def run_ab() -> None:
    """Baseline vs venue-real take-profit, per book: gate metrics + the TP slice."""
    tf = Timeframe(os.environ.get("DP_TF", "1h"))
    k = int(os.environ.get("DP_FOLDS", 6))
    books = [b.split(":") for b in os.environ.get("TP_BOOKS", DEFAULT_BOOKS).split(",")]
    ppy = (365 * 24 * 3600) / tf.seconds

    print(f"\n=== take-profit fidelity A/B ({tf.value}, 80/20 + {k}-fold WF) ===")
    print("    base  = backtest assumption: target filled INTRABAR (resting TP limit)")
    print("    venue = GMO reality: STOP holds the only settle slot; target realised at")
    print("            the next reconcile -> next bar's OPEN (ERR-200, 2026-08-06)\n")

    for name, product in books:
        try:
            bars = load_cache(tf, product=product).bars
        except Exception as e:  # noqa: BLE001 - a missing product must not stop the rest
            print(f"  {name} [{product}]: SKIPPED ({e})")
            continue
        if not bars:
            print(f"  {name} [{product}]: SKIPPED (no bars)")
            continue

        size = _lot(product)
        in_bars, oos_bars = split_in_out_sample(bars)
        bounds = _fold_bounds(len(bars), k)
        rows: list[_Row] = []
        for venue in (False, True):
            eq_in, tr_in = _run(name, in_bars, venue=venue, size=size)
            eq_oos, tr_oos = _run(name, oos_bars, venue=venue, size=size)
            folds = [annualized_sharpe_from_levels(
                _run(name, bars[bounds[i]:bounds[i + 1]], venue=venue, size=size)[0], ppy)
                for i in range(k)]
            rows.append(_Row(
                es_in=annualized_sharpe_from_levels(eq_in, ppy),
                es_oos=annualized_sharpe_from_levels(eq_oos, ppy),
                dd_in=_max_dd(eq_in),
                pnl_in=sum(t.pnl for t in tr_in),
                pnl_oos=sum(t.pnl for t in tr_oos),
                n_in=len(tr_in),
                folds=folds,
                tr_in=tr_in,
            ))
        base, venue_row = rows
        # Same construction as cycle.py gate A, so the comparison is like-for-like.
        bh_in = annualized_sharpe_from_levels([b.close for b in in_bars], ppy, pct=True)
        bh_oos = annualized_sharpe_from_levels([b.close for b in oos_bars], ppy, pct=True)

        n_tp, tp_pnl_b, tp_pnl_v = _tp_stats(base.tr_in, venue_row.tr_in)
        share = n_tp / base.n_in * 100 if base.n_in else 0.0

        print(f"  --- {name} [{product}] — {len(bars)} bars, lot {size:g} ---")
        hdr = (f"    {'run':>6} | {'IS eqSh':>8} {'OOS eqSh':>8} | {'IS DD':>7} | "
               f"{'IS PnL':>8} {'OOS PnL':>8} | {'n':>5} | WF")
        print(hdr)
        for label, r in (("base", base), ("venue", venue_row)):
            wins = sum(1 for e in r.folds if e > 0)
            fs = " ".join(f"{e:+.2f}" for e in r.folds)
            print(f"    {label:>6} | {r.es_in:+8.3f} {r.es_oos:+8.3f} | "
                  f"{r.dd_in:7.0f} | {r.pnl_in:8.0f} {r.pnl_oos:8.0f} | "
                  f"{r.n_in:>5} | {wins}/{k} [{fs}] mean={np.mean(r.folds):+.2f}")
        d_pnl = venue_row.pnl_in - base.pnl_in
        keep = (venue_row.pnl_in / base.pnl_in * 100) if base.pnl_in else float("nan")
        print(f"    {'delta':>6} | {venue_row.es_in - base.es_in:+8.3f} "
              f"{venue_row.es_oos - base.es_oos:+8.3f} | {'':7} | {d_pnl:8.0f} "
              f"{venue_row.pnl_oos - base.pnl_oos:8.0f} | "
              f"{venue_row.n_in - base.n_in:+5} |")
        print(f"    TP exits in base (IS): {n_tp} of {base.n_in} trades ({share:.1f}%); "
              f"their PnL {tp_pnl_b:.0f} -> {tp_pnl_v:.0f} JPY")
        print(f"    IS PnL retained under the venue rule: {keep:.1f}%")
        gate_b = (base.es_in >= bh_in) and (base.es_oos >= bh_oos)
        gate_v = (venue_row.es_in >= bh_in) and (venue_row.es_oos >= bh_oos)
        print(f"    ship gate A (eqSharpe >= B&H in BOTH splits; B&H IS {bh_in:+.3f} / "
              f"OOS {bh_oos:+.3f}): base={gate_b}  venue={gate_v}\n")


if __name__ == "__main__":
    from src.config import get_settings
    from src.logging_setup import configure_logging

    configure_logging(get_settings().log_level)
    run_ab()
