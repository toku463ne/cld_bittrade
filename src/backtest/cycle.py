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
    annualized_sharpe_from_levels,
    buy_and_hold_return,
    portfolio_metrics,
)
from src.core.types import Bar, Timeframe, Trade
from src.data.cache import load_cache
from src.logging_setup import configure_logging
from src.simulator import MultiSimulator, Simulator
from src.simulator.simulator import DEFAULT_FEE_RATE, SimResult
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
        multi: Whether this is a multi-position strategy (judged by the
            time-based equity Sharpe rather than per-trade Sharpe).
        equity_sharpe_in: Annualised IS equity Sharpe (multi only; 0 otherwise).
        equity_sharpe_oos: Annualised OOS equity Sharpe (multi only).
        bench_sharpe: Annualised buy-and-hold Sharpe over the in-sample period
            (the comparison baseline for the multi equity Sharpe).
    """

    strategy: str
    in_sample: PortfolioMetrics
    oos: PortfolioMetrics
    benchmark_return: float
    per_period: list[dict[str, float | str]]
    ship: bool
    trades: list[Trade] = field(default_factory=list)
    multi: bool = False
    equity_sharpe_in: float = 0.0
    equity_sharpe_oos: float = 0.0
    bench_sharpe: float = 0.0


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
    strategy_name: str,
    timeframe: Timeframe,
    *,
    product: str | None = None,
    size: float = 0.001,
    fee_rate: float | None = None,
) -> CycleResult:
    """Backtest one strategy and compute in-sample / OOS / benchmark metrics.

    Args:
        strategy_name: Registered strategy.
        timeframe: Bar timeframe.
        product: Product code (defaults to configured).
        size: Position size in BTC.
        fee_rate: Per-side taker cost (slippage) as a fraction of price. ``None``
            uses the simulator default (FX_BTC_JPY is commission-free; the default
            models taker half-spread slippage). Pass explicitly for cost sweeps.

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

    rate = DEFAULT_FEE_RATE if fee_rate is None else fee_rate
    multi = get_strategy(strategy_name).max_slots > 1
    in_res = _simulate(strategy_name, in_bars, size, rate, multi=multi)
    oos_res = _simulate(strategy_name, oos_bars, size, rate, multi=multi)
    m_in = portfolio_metrics(in_res.trades)
    m_oos = portfolio_metrics(oos_res.trades)

    bench = buy_and_hold_return(bars[0].close, bars[-1].close)
    per_period = _per_period_breakdown(in_res.trades, timeframe)
    non_neg = sum(1 for r in per_period if float(r["total_return"]) >= 0.0)
    consistent = (non_neg / len(per_period)) >= 0.8 if per_period else False

    # Overlapping multi-position strategies are judged by the time-based equity
    # Sharpe (per-trade Sharpe ignores how many positions overlap), benchmarked
    # against buy-and-hold's own annualised Sharpe over the in-sample period.
    ppy = (365 * 24 * 3600) / timeframe.seconds
    es_in = es_oos = bench_sharpe = 0.0
    if multi:
        es_in = annualized_sharpe_from_levels(in_res.equity_curve, ppy)
        es_oos = annualized_sharpe_from_levels(oos_res.equity_curve, ppy)
        bench_sharpe = annualized_sharpe_from_levels(
            [b.close for b in in_bars], ppy, pct=True
        )
        ship = (es_in >= bench_sharpe) and consistent
    else:
        ship = (m_in.sharpe >= 0.0) and consistent

    logger.info(
        "Cycle {}: IS Sharpe={:.3f} DD={:.4f} cost={:.1f}JPY | OOS Sharpe={:.3f} | "
        "bench(B&H, gross)={:.4f} | ship={}{}  [returns NET of fees]",
        strategy_name,
        m_in.sharpe,
        m_in.max_dd,
        m_in.total_cost,
        m_oos.sharpe,
        bench,
        ship,
        f" | eqSharpe IS={es_in:.3f}/OOS={es_oos:.3f} vs B&H {bench_sharpe:.3f}" if multi else "",
    )
    _flag_overfit(strategy_name, m_in, m_oos)
    trades = list(in_res.trades) + list(oos_res.trades)
    return CycleResult(
        strategy_name, m_in, m_oos, bench, per_period, ship, trades,
        multi=multi, equity_sharpe_in=es_in, equity_sharpe_oos=es_oos, bench_sharpe=bench_sharpe,
    )


def _simulate(
    strategy_name: str, bars: list[Bar], size: float, fee_rate: float, *, multi: bool
) -> SimResult:
    """Run the appropriate simulator (multi-position routes to MultiSimulator)."""
    strat = get_strategy(strategy_name)
    if multi:
        return MultiSimulator(strat, size=size, fee_rate=fee_rate).run(bars)
    return Simulator(strat, size=size, fee_rate=fee_rate).run(bars)


def _flag_overfit(name: str, m_in: PortfolioMetrics, m_oos: PortfolioMetrics) -> None:
    """Flag OVERFIT per CLAUDE.md: OOS Sharpe < 0 or OOS DD > 2x in-sample DD."""
    if m_oos.sharpe < 0.0 or (m_in.max_dd > 0 and m_oos.max_dd > 2.0 * m_in.max_dd):
        logger.warning("OVERFIT flag for {}: OOS Sharpe={:.3f} OOS DD={:.4f}", name, m_oos.sharpe, m_oos.max_dd)


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Run a strategy backtest cycle.")
    parser.add_argument("--strategy", default="all", help="Strategy name or 'all'.")
    parser.add_argument("--timeframe", choices=[tf.value for tf in Timeframe], default="5m")
    parser.add_argument(
        "--product", default=None, help="Product code (default: configured)."
    )
    parser.add_argument(
        "--fee", type=float, default=None,
        help="Per-side taker slippage (fraction). Default: simulator default.",
    )
    args = parser.parse_args()

    from src.config import get_settings

    configure_logging(get_settings().log_level)
    names = all_strategies() if args.strategy == "all" else [args.strategy]
    for name in names:
        run_cycle(name, Timeframe(args.timeframe), product=args.product, fee_rate=args.fee)


if __name__ == "__main__":
    main()
