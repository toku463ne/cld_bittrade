"""Regenerate a `docs/strategy/benchmark_table.md` row on the **lockbox** basis.

One reproducible source for the table's per-candidate metrics (the table had been
generated ad-hoc). Everything is on the fixed lockbox split (``split_lockbox`` —
IS = pre-2025-04-01, OOS = 2025-04-01 → 2026-04-01) so rows are comparable.

Columns (matching the table):
  n        IS trade count (lockbox IS).
  IS_sh    annualised mark-to-market **equity** Sharpe, IS, at 4 bp round-trip
           (= ``DEFAULT_FEE_RATE`` 0.0002/side).
  DR       IS win rate (signal-level diagnostic, not a gate).
  IS_DD    max drawdown of the IS per-trade-return curve.
  mean_r   mean net per-trade return, IS.
  OOS_sh   equity Sharpe, OOS, at 4 bp.
  OOS_DD   OOS per-trade-curve max drawdown.
  OOS@10bp OOS equity Sharpe at a realistic 10 bp round-trip (0.0005/side).
  WF       fixed-config 6-fold walk-forward over the FULL series (4 bp); folds
           with positive equity Sharpe.
  cBTC     bar-return correlation of the equity path to BTC, over the lockbox
           period (IS+OOS, pre-``LOCKBOX_OOS_END``).
  cDP      same, vs the density_pullback equity path (the shipping diversifier).

Validated 2026-06-08: reproduces the committed OLD density_pullback row
(n=428, IS_sh +1.39, DR 0.36, IS_DD 0.34, mean_r +0.0048, OOS_sh +1.11,
OOS_DD 0.15, OOS@10bp +0.90) exactly when run with ``recency=0.0``.

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.benchmark_table_row \
        --strategy density_pullback [--timeframe 1h] [--product GMO_BTC_JPY]
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from loguru import logger

from src.backtest.metrics import annualized_sharpe_from_levels, portfolio_metrics
from src.backtest.sign_benchmark import LOCKBOX_OOS_END, split_lockbox
from src.core.types import Bar, Timeframe
from src.data.cache import load_cache
from src.logging_setup import configure_logging
from src.simulator.multi_simulator import MultiSimulator
from src.strategy.registry import get_strategy

FEE_4BP = 0.0002  # per side -> 4 bp round-trip (the simulator default)
FEE_10BP = 0.0005  # per side -> 10 bp round-trip (cost-robustness check)


def _eq(name: str, bars: list[Bar], fee: float) -> list[float]:
    """Equity path of a fresh ``name`` instance over ``bars`` at ``fee``/side."""
    return MultiSimulator(get_strategy(name), fee_rate=fee).run(bars).equity_curve


def _wf_positive(name: str, bars: list[Bar], ppy: float, folds: int = 6) -> int:
    """Fixed-config K-fold walk-forward: count folds with positive equity Sharpe."""
    n = len(bars)
    size = n // folds
    edges = [i * size for i in range(folds)] + [n]
    return sum(
        annualized_sharpe_from_levels(_eq(name, bars[edges[k] : edges[k + 1]], FEE_4BP), ppy) > 0
        for k in range(folds)
    )


def compute_row(name: str, tf: Timeframe, product: str | None) -> dict[str, float]:
    """Compute the full lockbox row for ``name``."""
    bars = load_cache(tf, product=product).bars
    ppy = (365 * 24 * 3600) / tf.seconds
    is_b, oos_b = split_lockbox(bars)
    full = [b for b in bars if pd.Timestamp(b.timestamp) < LOCKBOX_OOS_END]

    in_res = MultiSimulator(get_strategy(name), fee_rate=FEE_4BP).run(is_b)
    oo_res = MultiSimulator(get_strategy(name), fee_rate=FEE_4BP).run(oos_b)
    p_in, p_oo = portfolio_metrics(in_res.trades), portfolio_metrics(oo_res.trades)

    btc = np.diff([b.close for b in full])
    eq = np.diff(_eq(name, full, FEE_4BP))
    dp = np.diff(_eq("density_pullback", full, FEE_4BP))
    return {
        "n": p_in.n_trades,
        "IS_sh": annualized_sharpe_from_levels(in_res.equity_curve, ppy),
        "DR": p_in.win_rate,
        "IS_DD": float(p_in.max_dd),
        "mean_r": p_in.total_return / max(p_in.n_trades, 1),
        "OOS_sh": annualized_sharpe_from_levels(oo_res.equity_curve, ppy),
        "OOS_DD": float(p_oo.max_dd),
        "OOS_10bp": annualized_sharpe_from_levels(_eq(name, oos_b, FEE_10BP), ppy),
        "WF": _wf_positive(name, bars, ppy),
        "cBTC": float(np.corrcoef(eq, btc)[0, 1]),
        "cDP": float(np.corrcoef(eq, dp)[0, 1]),
    }


def main() -> None:
    """CLI entrypoint."""
    configure_logging()
    ap = argparse.ArgumentParser(description="Regenerate a benchmark_table.md row (lockbox).")
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--timeframe", choices=[t.value for t in Timeframe], default="1h")
    ap.add_argument("--product", default="GMO_BTC_JPY")
    args = ap.parse_args()
    row = compute_row(args.strategy, Timeframe(args.timeframe), args.product)
    logger.info("== {} (lockbox, {} {}) ==", args.strategy, args.timeframe, args.product)
    logger.info(
        "| {} | {} | {:+.2f} | {:.2f} | {:.2f} | {:+.4f} | {:+.2f} | {:.2f} | {:+.2f} | {}/6 | {:+.2f} | {:+.2f} |",
        args.strategy, row["n"], row["IS_sh"], row["DR"], row["IS_DD"], row["mean_r"],
        row["OOS_sh"], row["OOS_DD"], row["OOS_10bp"], row["WF"], row["cBTC"], row["cDP"],
    )


if __name__ == "__main__":
    main()
