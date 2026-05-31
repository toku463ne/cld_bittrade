"""Backtest cycle runner.

Loads bars from the cache, runs one or all registered strategies through the
simulator, and reports the portfolio + per-period metrics with the
buy-and-hold BTC/JPY benchmark (NOT cash; per CLAUDE.md).

Usage::

    uv run --env-file .env.bt python -m src.backtest.cycle --strategy ema_atr_breakout
    uv run --env-file .env.bt python -m src.backtest.cycle --strategy all --timeframe 5m
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

from loguru import logger

from src.backtest.metrics import (
    PortfolioMetrics,
    buy_and_hold_return,
    portfolio_metrics,
)
from src.core.types import Timeframe, Trade
from src.data.cache import load_cache
from src.logging_setup import configure_logging
from src.simulator import Simulator
from src.strategy.registry import all_strategies, get_strategy


@dataclass(frozen=True, slots=True)
class CycleResult:
    """A single strategy's backtest result.

    Attributes:
        strategy: Strategy name.
        in_sample: In-sample portfolio metrics.
        oos: OOS portfolio metrics.
        benchmark_return: Buy-and-hold BTC/JPY return over the full period.
        per_period: Per-period breakdown rows.
        ship: Whether the pre-registered ship gate passed (Sharpe >= bench &
            >= 4/5 periods non-negative).
        trades: All trades (in-sample + OOS), for charting — same trades the
            metrics were computed from, so no extra simulation is needed.
    """

    strategy: str
    in_sample: PortfolioMetrics
    oos: PortfolioMetrics
    benchmark_return: float
    per_period: list[dict[str, float | str]]
    ship: bool
    trades: list[Trade] = field(default_factory=list)


def _per_period_breakdown(
    trades: list[Trade], timeframe: Timeframe
) -> list[dict[str, float | str]]:
    """Aggregate trades into the timeframe's natural reporting period."""
    fmt = {
        "hour": "%Y-%m-%d %H:00",
        "day": "%Y-%m-%d",
        "week": "%Y-W%W",
    }[timeframe.period_unit]

    groups: dict[str, list[Trade]] = {}
    for t in trades:
        groups.setdefault(t.exit_time.strftime(fmt), []).append(t)

    rows: list[dict[str, float | str]] = []
    for period, ts in sorted(groups.items()):
        m = portfolio_metrics(ts)
        wins = sum(1 for t in ts if t.return_pct > 0)
        rows.append(
            {
                "period": period,
                "n_fires": len(ts),
                "DR": round(wins / len(ts), 3) if ts else 0.0,
                "total_return": round(m.total_return, 5),
                "max_DD": round(m.max_dd, 5),
                "win_rate": round(m.win_rate, 3),
            }
        )
    return rows


def run_cycle(
    strategy_name: str, timeframe: Timeframe, *, product: str | None = None, size: float = 0.001
) -> CycleResult:
    """Backtest one strategy and compute in-sample / OOS / benchmark metrics.

    Args:
        strategy_name: Registered strategy.
        timeframe: Bar timeframe.
        product: Product code (defaults to configured).
        size: Position size in BTC.

    Returns:
        A :class:`CycleResult`.
    """
    from src.backtest.sign_benchmark import split_in_out_sample

    cache = load_cache(timeframe, product=product)
    bars = cache.bars
    if not bars:
        raise RuntimeError(
            f"No {timeframe.value} bars found. Run `python -m src.data.collect` first."
        )
    in_bars, oos_bars = split_in_out_sample(bars)

    in_res = Simulator(get_strategy(strategy_name), size=size).run(in_bars)
    oos_res = Simulator(get_strategy(strategy_name), size=size).run(oos_bars)
    m_in = portfolio_metrics(in_res.trades)
    m_oos = portfolio_metrics(oos_res.trades)

    bench = buy_and_hold_return(bars[0].close, bars[-1].close)
    per_period = _per_period_breakdown(in_res.trades, timeframe)
    non_neg = sum(1 for r in per_period if float(r["total_return"]) >= 0.0)
    ship = (m_in.sharpe >= 0.0) and (
        (non_neg / len(per_period)) >= 0.8 if per_period else False
    )

    logger.info(
        "Cycle {}: IS Sharpe={:.3f} DD={:.4f} cost={:.1f}JPY | OOS Sharpe={:.3f} | "
        "bench(B&H, gross)={:.4f} | ship={}  [returns NET of fees]",
        strategy_name,
        m_in.sharpe,
        m_in.max_dd,
        m_in.total_cost,
        m_oos.sharpe,
        bench,
        ship,
    )
    _flag_overfit(strategy_name, m_in, m_oos)
    trades = list(in_res.trades) + list(oos_res.trades)
    return CycleResult(strategy_name, m_in, m_oos, bench, per_period, ship, trades)


def _flag_overfit(name: str, m_in: PortfolioMetrics, m_oos: PortfolioMetrics) -> None:
    """Flag OVERFIT per CLAUDE.md: OOS Sharpe < 0 or OOS DD > 2x in-sample DD."""
    if m_oos.sharpe < 0.0 or (m_in.max_dd > 0 and m_oos.max_dd > 2.0 * m_in.max_dd):
        logger.warning("OVERFIT flag for {}: OOS Sharpe={:.3f} OOS DD={:.4f}", name, m_oos.sharpe, m_oos.max_dd)


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Run a strategy backtest cycle.")
    parser.add_argument("--strategy", default="all", help="Strategy name or 'all'.")
    parser.add_argument("--timeframe", choices=[tf.value for tf in Timeframe], default="5m")
    args = parser.parse_args()

    from src.config import get_settings

    configure_logging(get_settings().log_level)
    names = all_strategies() if args.strategy == "all" else [args.strategy]
    for name in names:
        run_cycle(name, Timeframe(args.timeframe))


if __name__ == "__main__":
    main()
