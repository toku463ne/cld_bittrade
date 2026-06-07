"""Do the no-TP "ride" trades carry the edge, or the with-TP trades?

Most ``density_pullback`` / ``random_hedge`` entries find **no** pre-existing dense
node beyond the next-dense floor (``_next_dense`` -> ``None``): they have no
take-profit and ride to the SL / trail / time stop. A minority do get a dense TP.
This probe splits the trades both ways and asks which set actually carries the
portfolio edge:

1. **Per-trade** (descriptive) — classify the realised trades of a full run by
   ``tp_price is None`` and report n / win% / mean_r / sum_r / median hold / exit
   mix, IS and OOS.
2. **Portfolio** (the real test) — re-run the strategy restricted to *only* the
   with-TP entries, then *only* the no-TP entries, and compare the annualised
   equity Sharpe against the full strategy. The with/no-TP label is known at signal
   time (causal), so this is a legitimate subset, modulo a small slot-contention
   caveat (subsets compete for fewer slots; sparse breakouts make this minor).

Usage::

    uv run --env-file .env.bt python -m src.backtest.analysis.density_pullback_notp_probe \
        --timeframe 1h --product GMO_BTC_JPY
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable
from datetime import datetime

import numpy as np
from loguru import logger

from src.backtest.metrics import annualized_sharpe_from_levels
from src.backtest.sign_benchmark import split_in_out_sample
from src.core.types import Bar, Signal, Timeframe, Trade
from src.strategy.base import Strategy
from src.data.cache import load_cache
from src.logging_setup import configure_logging
from src.simulator.multi_simulator import MultiSimulator
from src.strategy.density_pullback import DensityPullbackStrategy
from src.strategy.random_hedge import RandomHedgeStrategy

SIZE = 0.001


class _SubsetPullback(DensityPullbackStrategy):
    """density_pullback restricted to with-TP or no-TP entries (probe only)."""

    def __init__(self, mode: str, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._mode = mode  # "with_tp" | "no_tp" | "all"

    def precompute_multi(self, bars: list[Bar]) -> dict[datetime, list[Signal]] | None:
        out = super().precompute_multi(bars)
        if out is None or self._mode == "all":
            return out
        want = self._mode == "with_tp"
        filt: dict[datetime, list[Signal]] = {}
        for ts, sigs in out.items():
            keep = [
                s for s in sigs
                if s.exit_config is not None and (s.exit_config.tp_abs is not None) == want
            ]
            if keep:
                filt[ts] = keep
        return filt


class _SubsetHedge(RandomHedgeStrategy):
    """random_hedge restricted to with-TP or no-TP legs (probe only)."""

    def __init__(self, mode: str, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._mode = mode

    def precompute_multi(self, bars: list[Bar]) -> dict[datetime, list[Signal]] | None:
        out = super().precompute_multi(bars)
        if out is None or self._mode == "all":
            return out
        want = self._mode == "with_tp"
        filt: dict[datetime, list[Signal]] = {}
        for ts, sigs in out.items():
            keep = [
                s for s in sigs
                if s.exit_config is not None and (s.exit_config.tp_abs is not None) == want
            ]
            if keep:
                filt[ts] = keep
        return filt


def _per_trade(label: str, trades: list[Trade]) -> None:
    if not trades:
        logger.info("    {:<10} | n=0", label)
        return
    r = np.array([t.pnl / (t.entry_price * t.size) for t in trades])
    bh = np.array([t.bars_held for t in trades])
    mix = Counter(t.exit_reason.name for t in trades)
    logger.info(
        "    {:<10} | n {:>4} | win {:.3f} | mean_r {:+.5f} | sum_r {:+.3f} | med_hold {:.0f} | {}",
        label, len(trades), float((r > 0).mean()), float(r.mean()), float(r.sum()),
        float(np.median(bh)), dict(mix),
    )


def _portfolio(
    name: str, make: Callable[[str], Strategy], ib: list[Bar], ob: list[Bar], ppy: float
) -> None:
    for mode in ("all", "with_tp", "no_tp"):
        si = MultiSimulator(make(mode), size=SIZE).run(ib)
        so = MultiSimulator(make(mode), size=SIZE).run(ob)
        logger.info(
            "    {:<10} {:<8} | IS eqSh {:+.3f} ({:>4} tr) | OOS eqSh {:+.3f} ({:>4} tr)",
            name, mode,
            annualized_sharpe_from_levels(si.equity_curve, ppy), len(si.trades),
            annualized_sharpe_from_levels(so.equity_curve, ppy), len(so.trades),
        )


def run(tf: Timeframe, *, product: str | None) -> None:
    """Split trades by with-TP / no-TP and compare per-trade and portfolio edge."""
    cache = load_cache(tf, product=product)
    ib, ob = split_in_out_sample(cache.bars)
    ppy = (365 * 24 * 3600) / tf.seconds

    for name, strat in (("density_pullback", DensityPullbackStrategy()),
                        ("random_hedge", RandomHedgeStrategy(seed=0))):
        res_is = MultiSimulator(strat, size=SIZE).run(ib)
        res_oos = MultiSimulator(strat, size=SIZE).run(ob)
        logger.info("================ {} — per-trade split ================", name)
        for sample, trades in (("IN-SAMPLE", res_is.trades), ("OOS", res_oos.trades)):
            logger.info("  [{}]", sample)
            with_tp = [t for t in trades if t.tp_price is not None]
            no_tp = [t for t in trades if t.tp_price is None]
            _per_trade("ALL", trades)
            _per_trade("with-TP", with_tp)
            _per_trade("no-TP/ride", no_tp)

    logger.info("================ portfolio equity Sharpe by subset ================")
    _portfolio("pullback", lambda m: _SubsetPullback(m), ib, ob, ppy)
    _portfolio("hedge", lambda m: _SubsetHedge(m, seed=0), ib, ob, ppy)
    logger.warning(
        "  NOTE: 'hedge' rows are seed=0 only and SEED-FRAGILE — over 8 seeds the "
        "with-TP subset is IS -0.02 / OOS +0.19 (not robust). The TP/no-TP split "
        "does NOT cleanly separate edge; subsets flip across the IS/OOS split (and "
        "seeds), and the full strategy is more robust than either subset."
    )


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="no-TP ride vs with-TP edge probe.")
    parser.add_argument("--timeframe", choices=[tf.value for tf in Timeframe], default="1h")
    parser.add_argument("--product", default=None)
    args = parser.parse_args()
    configure_logging()
    run(Timeframe(args.timeframe), product=args.product)


if __name__ == "__main__":
    main()
