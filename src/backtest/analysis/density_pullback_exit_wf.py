"""Walk-forward for the `density_pullback` exit tuning — is the sweet spot real?

The exit grid sweep showed a broad plateau (low ``sl_mult`` + slow ``recalc_bars``
lift both IS and OOS; ``time_stop_bars`` barely matters). A single IS/OOS split
plus eyeballing the plateau can still overfit, so this confirms the tune the way
``density_multi_walkforward`` does:

A. **Fixed-config across folds** — run the candidate sweet spot in each of ``K``
   consecutive folds beside buy-and-hold's own annualised equity Sharpe. Shows a
   *fixed* exit config earns across regimes, not just on the last slice.
B. **Anchored re-selection** — for each fold ``k>=1`` pick the best exit cell by
   equity Sharpe on *all data before* the fold, then evaluate that
   (out-of-sample-chosen) cell on the fold. If the chosen sequence is positive,
   the grid selection is not overfit.

Causal: bands/peaks/ATR depend only on past bars within each slice (a small
warm-up loss at each slice start, same as the project's OOS handling). No
look-ahead — the fold-k config in (B) is chosen strictly from pre-fold data.

Usage::

    uv run --env-file .env.bt python -m src.backtest.analysis.density_pullback_exit_wf \
        --timeframe 1h --product GMO_BTC_JPY --folds 6
"""

from __future__ import annotations

import argparse

from loguru import logger

from src.backtest.metrics import annualized_sharpe_from_levels, portfolio_metrics
from src.backtest.sign_benchmark import split_in_out_sample
from src.core.types import Bar, Timeframe
from src.data.cache import load_cache
from src.logging_setup import configure_logging
from src.simulator.multi_simulator import MultiSimulator
from src.strategy.density_pullback import DensityPullbackStrategy

# Exit grid (the swept knobs). sl_mult x recalc_bars x time_stop_bars.
SL_MULTS = (1.0, 1.5, 2.0)
RECALCS = (12, 24, 48)
TSTOPS = (120, 240)
SWEET = {"sl_mult": 1.0, "recalc_bars": 48, "time_stop_bars": 120}  # plateau pick

# One-knob sl_mult tune: recalc/ts fixed at the confirmed sweet spot, finer sl grid.
SL_MULTS_FINE = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
SL_FIXED = {"recalc_bars": 48, "time_stop_bars": 120}


def _eq_sharpe(bars: list[Bar], ppy: float, **kw: float) -> float:
    res = MultiSimulator(DensityPullbackStrategy(**kw)).run(bars)  # type: ignore[arg-type]
    return annualized_sharpe_from_levels(res.equity_curve, ppy)


def _bh_sharpe(bars: list[Bar], ppy: float) -> float:
    return annualized_sharpe_from_levels([b.close for b in bars], ppy, pct=True)


def run(tf: Timeframe, *, product: str | None, folds: int) -> None:
    """Run analyses A and B for the density_pullback exit tuning."""
    cache = load_cache(tf, product=product)
    bars = cache.bars
    ppy = (365 * 24 * 3600) / tf.seconds
    n = len(bars)
    size = n // folds
    edges = [i * size for i in range(folds)] + [n]
    logger.info("{} {} — {} bars, {} folds (~{} bars each)", tf.value, product or "cfg", n, folds, size)

    # A. Fixed sweet-spot config across folds.
    logger.info("== A. fixed sweet spot {} across folds ==", SWEET)
    logger.info("  fold |  eqSharpe |  B&H   | n_trades")
    pos = 0
    for k in range(folds):
        seg = bars[edges[k] : edges[k + 1]]
        es = _eq_sharpe(seg, ppy, **SWEET)
        bh = _bh_sharpe(seg, ppy)
        res = MultiSimulator(DensityPullbackStrategy(**SWEET)).run(seg)  # type: ignore[arg-type]
        pos += es > 0
        logger.info("   {:>2}  | {:+.3f}    | {:+.3f} | {}", k, es, bh, len(res.trades))
    logger.info("  -> sweet spot positive in {}/{} folds", pos, folds)

    # B. Anchored re-selection: choose on pre-fold data, test on the fold.
    logger.info("== B. anchored walk-forward (re-select on past, test on fold) ==")
    logger.info("  fold | chosen (sl/rc/ts)     | train eqSh | TEST eqSh | B&H")
    test_pos = 0
    test_vals = []
    for k in range(1, folds):
        train = bars[: edges[k]]
        test = bars[edges[k] : edges[k + 1]]
        best = None
        for sl in SL_MULTS:
            for rc in RECALCS:
                for ts in TSTOPS:
                    es = _eq_sharpe(train, ppy, sl_mult=sl, recalc_bars=rc, time_stop_bars=ts)
                    if best is None or es > best[0]:
                        best = (es, sl, rc, ts)
        assert best is not None
        _tr, sl, rc, ts = best
        te = _eq_sharpe(test, ppy, sl_mult=sl, recalc_bars=rc, time_stop_bars=ts)
        bh = _bh_sharpe(test, ppy)
        test_pos += te > 0
        test_vals.append(te)
        logger.info(
            "   {:>2}  | sl{} rc{} ts{}{}| {:+.3f}     | {:+.3f}    | {:+.3f}",
            k, sl, rc, ts, " " * (10 - len(f"sl{sl} rc{rc} ts{ts}")), best[0], te, bh,
        )
    mean_te = sum(test_vals) / len(test_vals) if test_vals else 0.0
    logger.info(
        "  -> anchored test eqSharpe positive in {}/{} folds, mean {:+.3f}",
        test_pos, folds - 1, mean_te,
    )


def run_slmult(tf: Timeframe, *, product: str | None, folds: int) -> None:
    """One-knob sl_mult tune: recalc/ts fixed at the sweet spot, walk-forward sl_mult."""
    cache = load_cache(tf, product=product)
    bars = cache.bars
    ppy = (365 * 24 * 3600) / tf.seconds
    n = len(bars)
    size = n // folds
    edges = [i * size for i in range(folds)] + [n]
    logger.info("ONE-KNOB sl_mult (fixed {}) — {} bars, {} folds", SL_FIXED, n, folds)

    # A. Each sl_mult candidate across folds (fixed config): row = sl, cols = folds.
    logger.info("== A. each sl_mult across folds (eqSharpe; +ve folds; full-split IS/OOS, DD) ==")
    in_bars, oos_bars = split_in_out_sample(bars)
    for sl in SL_MULTS_FINE:
        per = [_eq_sharpe(bars[edges[k] : edges[k + 1]], ppy, sl_mult=sl, **SL_FIXED) for k in range(folds)]
        npos = sum(v > 0 for v in per)
        is_es = _eq_sharpe(in_bars, ppy, sl_mult=sl, **SL_FIXED)
        oos_es = _eq_sharpe(oos_bars, ppy, sl_mult=sl, **SL_FIXED)
        dd = portfolio_metrics(
            MultiSimulator(DensityPullbackStrategy(sl_mult=sl, **SL_FIXED)).run(in_bars).trades  # type: ignore[arg-type]
        ).max_dd
        folds_str = " ".join(f"{v:+.2f}" for v in per)
        logger.info(
            "  sl{:<4} | folds [{}] {}/{}+ | IS {:+.3f} OOS {:+.3f} ISdd {:.2f}",
            sl, folds_str, npos, folds, is_es, oos_es, dd,
        )

    # B. Anchored re-selection over sl_mult only.
    logger.info("== B. anchored walk-forward over sl_mult (choose on past, test on fold) ==")
    logger.info("  fold | chosen sl | train | TEST  | B&H")
    test_pos = 0
    test_vals = []
    for k in range(1, folds):
        train = bars[: edges[k]]
        test = bars[edges[k] : edges[k + 1]]
        best = max(((_eq_sharpe(train, ppy, sl_mult=sl, **SL_FIXED), sl) for sl in SL_MULTS_FINE))
        sl = best[1]
        te = _eq_sharpe(test, ppy, sl_mult=sl, **SL_FIXED)
        test_pos += te > 0
        test_vals.append(te)
        logger.info("   {:>2}  | sl{:<5}  | {:+.3f}| {:+.3f}| {:+.3f}", k, sl, best[0], te, _bh_sharpe(test, ppy))
    mean_te = sum(test_vals) / len(test_vals) if test_vals else 0.0
    logger.info("  -> anchored sl_mult positive in {}/{} folds, mean test {:+.3f}", test_pos, folds - 1, mean_te)


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="density_pullback exit-tuning walk-forward.")
    parser.add_argument("--timeframe", choices=[tf.value for tf in Timeframe], default="1h")
    parser.add_argument("--product", default=None)
    parser.add_argument("--folds", type=int, default=6)
    parser.add_argument("--axis", choices=["grid", "sl"], default="grid",
                        help="'grid' = full sl/rc/ts WF; 'sl' = one-knob sl_mult tune.")
    args = parser.parse_args()
    configure_logging()
    if args.axis == "sl":
        run_slmult(Timeframe(args.timeframe), product=args.product, folds=args.folds)
    else:
        run(Timeframe(args.timeframe), product=args.product, folds=args.folds)


if __name__ == "__main__":
    main()
