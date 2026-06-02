"""Multi-month (walk-forward) sign benchmark.

Runs the per-fire benchmark broken down by monthly period (the walk-forward unit
for this project; guide §4.3) and persists one ``sign_benchmark_run`` row per
period. Phases mirror ``scripts/rebenchmark_sign.sh``:

- ``benchmark`` — compute per-month in-sample metrics.
- ``validate``  — recompute and check per-month consistency (>= 4/5 non-negative).
- ``report``    — render the benchmark.md tables.
- ``backtest``  — OOS (most recent 20%).

Usage::

    uv run --env-file .env.bt python -m src.backtest.sign_benchmark_multiyear \
        --sign ema_atr_breakout --timeframe 5m --phase benchmark validate report
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass

from loguru import logger

from src.backtest.metrics import SignMetrics, sign_metrics
from src.backtest.sign_benchmark import (
    MeasuredFire,
    measure_fires,
    split_in_out_sample,
)
from src.core.types import Timeframe
from src.data.cache import load_cache
from src.db import get_session
from src.logging_setup import configure_logging
from src.models import SignBenchmarkRun


@dataclass(frozen=True, slots=True)
class PeriodResult:
    """Per-period metrics."""

    period: str
    metrics: SignMetrics


def _group_by_month(measured: list[MeasuredFire]) -> dict[str, list[MeasuredFire]]:
    groups: dict[str, list[MeasuredFire]] = defaultdict(list)
    for m in measured:
        key = m.fire.fired_at.strftime("%Y-%m")
        groups[key].append(m)
    return dict(sorted(groups.items()))


def run_multiyear(
    sign_name: str,
    timeframe: Timeframe,
    *,
    phases: list[str],
    product: str | None = None,
) -> list[PeriodResult]:
    """Run monthly walk-forward benchmark across the requested phases.

    Args:
        sign_name: Registered sign.
        timeframe: Bar timeframe.
        phases: Subset of ``benchmark`` / ``validate`` / ``report`` / ``backtest``.
        product: Product code (defaults to configured).

    Returns:
        Per-period results for the last phase that produces them.
    """
    cache = load_cache(timeframe, product=product)
    in_sample, oos = split_in_out_sample(cache.bars)

    results: list[PeriodResult] = []
    for phase in phases:
        bars = oos if phase == "backtest" else in_sample
        measured = measure_fires(bars, sign_name)
        groups = _group_by_month(measured)
        results = [
            PeriodResult(period, sign_metrics([m.signed_return for m in fires]))
            for period, fires in groups.items()
        ]

        if phase in {"benchmark", "backtest"}:
            _persist_periods(sign_name, timeframe, phase, results)
        elif phase == "validate":
            _validate(sign_name, results)
        elif phase == "report":
            _report(sign_name, timeframe, results)
        else:
            logger.warning("Unknown phase '{}' — skipping.", phase)
    return results


def _persist_periods(
    sign_name: str, timeframe: Timeframe, phase: str, results: list[PeriodResult]
) -> None:
    with get_session() as session:
        for r in results:
            m = r.metrics
            session.add(
                SignBenchmarkRun(
                    sign_type=sign_name,
                    strategy=sign_name,
                    phase=phase,
                    period=r.period,
                    n_events=m.n,
                    dr=m.dr,
                    mean_r=m.mean_r,
                    ev=m.ev,
                    perm_p=m.perm_p,
                )
            )
    logger.info("Persisted {} {} period rows for {}.", len(results), phase, sign_name)


def _validate(sign_name: str, results: list[PeriodResult]) -> None:
    if not results:
        logger.warning("No periods to validate for {}.", sign_name)
        return
    non_neg = sum(1 for r in results if r.metrics.mean_r >= 0.0)
    frac = non_neg / len(results)
    ok = frac >= 0.8  # >= 4/5 non-negative (CLAUDE.md ship criterion)
    logger.info(
        "Validate {}: {}/{} months non-negative ({:.0%}) -> {}",
        sign_name,
        non_neg,
        len(results),
        frac,
        "PASS" if ok else "FAIL",
    )


def _report(sign_name: str, timeframe: Timeframe, results: list[PeriodResult]) -> None:
    logger.info("Per-month report for {} ({}):", sign_name, timeframe.value)
    for r in results:
        m = r.metrics
        logger.info(
            "  {} | n={:<4} DR={:.3f} mean_r={:.4f} perm_p={:.3f}",
            r.period,
            m.n,
            m.dr,
            m.mean_r,
            m.perm_p,
        )


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Multi-month walk-forward sign benchmark.")
    parser.add_argument("--sign", required=True)
    parser.add_argument("--timeframe", choices=[tf.value for tf in Timeframe], default="5m")
    parser.add_argument(
        "--phase",
        nargs="+",
        choices=["benchmark", "validate", "report", "backtest"],
        default=["benchmark"],
        help="One or more phases to run in order.",
    )
    parser.add_argument(
        "--product", default=None, help="Product code (default: configured)."
    )
    args = parser.parse_args()

    from src.config import get_settings

    configure_logging(get_settings().log_level)
    run_multiyear(
        args.sign, Timeframe(args.timeframe), phases=args.phase, product=args.product
    )


if __name__ == "__main__":
    main()
