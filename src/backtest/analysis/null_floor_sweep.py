"""Random-hedge **null floor** over N seeds (lockbox, honest fills).

The lockbox OOS window is directional (down), and a hedged random-entry pair with
a ride exit beats a falling B&H by letting the trend-aligned leg run — so B&H is
the wrong floor for *entry* edge. The honest floor is the random hedge's own
multi-seed mean lockbox equity Sharpe. This is the reproducible source for the
``benchmark_table.md`` ⚠ lift-over-null section (the original sweep was ad-hoc).

Same basis as ``benchmark_table_row``: fixed lockbox split, annualised
mark-to-market **equity** Sharpe at 4 bp round-trip. Reports the per-control
20-seed mean / sd / min / max for IS and OOS.

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.null_floor_sweep \
        [--seeds 20] [--timeframe 1h] [--product GMO_BTC_JPY]
"""

from __future__ import annotations

import argparse

import numpy as np
from loguru import logger

from src.backtest.metrics import annualized_sharpe_from_levels
from src.backtest.sign_benchmark import split_lockbox
from src.core.types import Timeframe
from src.data.cache import load_cache
from src.logging_setup import configure_logging
from src.simulator.multi_simulator import MultiSimulator
from src.strategy.random_hedge import RandomHedgeStrategy, RandomHedgeVolfilterStrategy

FEE_4BP = 0.0002  # per side -> 4 bp round-trip (the table basis)


def main() -> None:
    """Print the N-seed null-floor lockbox equity Sharpe for the random controls."""
    configure_logging()
    ap = argparse.ArgumentParser(description="Random-hedge null floor over N seeds (lockbox).")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--timeframe", choices=[t.value for t in Timeframe], default="1h")
    ap.add_argument("--product", default="GMO_BTC_JPY")
    args = ap.parse_args()

    tf = Timeframe(args.timeframe)
    ppy = (365 * 24 * 3600) / tf.seconds
    bars = load_cache(tf, product=args.product).bars
    is_b, oos_b = split_lockbox(bars)

    for name, cls in (
        ("random_hedge_volfilter", RandomHedgeVolfilterStrategy),
        ("random_hedge", RandomHedgeStrategy),
    ):
        iss, ooss = [], []
        for k in range(args.seeds):
            iss.append(annualized_sharpe_from_levels(
                MultiSimulator(cls(seed=k), fee_rate=FEE_4BP).run(is_b).equity_curve, ppy))
            ooss.append(annualized_sharpe_from_levels(
                MultiSimulator(cls(seed=k), fee_rate=FEE_4BP).run(oos_b).equity_curve, ppy))
        a_is, a_oos = np.array(iss), np.array(ooss)
        logger.info(
            "{:24} {}-seed: IS {:+.2f} (sd {:.2f}, [{:+.2f}, {:+.2f}]) | "
            "OOS {:+.2f} (sd {:.2f}, [{:+.2f}, {:+.2f}])",
            name, args.seeds, a_is.mean(), a_is.std(), a_is.min(), a_is.max(),
            a_oos.mean(), a_oos.std(), a_oos.min(), a_oos.max(),
        )


if __name__ == "__main__":
    main()
