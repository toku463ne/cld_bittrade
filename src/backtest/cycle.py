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
from datetime import datetime

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
        ship: Whether the pre-registered ship gate passed — (a) annualised equity
            Sharpe >= buy-and-hold's own in BOTH the IS and OOS splits, AND (b) the
            relative quarterly-consistency gate (>= B&H's non-negative fraction; see
            ``_quarter_consistency``).
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


def _quarter_consistency(
    trades: list[Trade], bars: list[Bar]
) -> tuple[float, float]:
    """Fraction of calendar quarters that are non-negative: strategy vs buy-and-hold.

    The consistency gate is **relative** (vs B&H, the displaced-capital benchmark) and
    bucketed by **calendar quarter** — frequency-adaptive per ``evaluation_criteria.md``
    §6.4 (a quarter holds several trades for these strategies; the old per-``timeframe``
    "week" unit was a period-length artifact that manufactured false failures). The
    strategy's quarter is non-negative if its summed net trade return is >= 0; B&H's if
    its quarter-close-to-close return is >= 0. An absolute 80% gate would demand more
    consistency than B&H itself (only ~62% of IS quarters are non-negative), so we
    require **>= B&H's own non-negative fraction** instead.

    Returns:
        ``(strategy_fraction, benchmark_fraction)``.
    """
    import pandas as pd

    def _q(ts: datetime) -> tuple[int, int]:
        return (ts.year, (ts.month - 1) // 3)

    q_trades: dict[tuple[int, int], list[Trade]] = {}
    for t in trades:
        q_trades.setdefault(_q(t.exit_time), []).append(t)
    strat = (
        sum(1 for ts in q_trades.values() if portfolio_metrics(ts).total_return >= 0.0)
        / len(q_trades)
        if q_trades
        else 0.0
    )

    closes = pd.Series(
        [b.close for b in bars], index=pd.DatetimeIndex([b.timestamp for b in bars])
    )
    q_ret = closes.resample("QE").last().pct_change().dropna()
    bench = float((q_ret >= 0.0).mean()) if len(q_ret) else 0.0
    return strat, bench


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
    # Relative consistency gate (vs B&H, by calendar quarter; see _quarter_consistency
    # and evaluation_criteria.md §6.4): the strategy must be non-negative in >= as many
    # quarters as buy-and-hold over the same in-sample window — not an absolute 80%.
    strat_cons, bench_cons = _quarter_consistency(in_res.trades, in_bars)
    consistent = strat_cons >= bench_cons

    # Gate A: the time-based annualised equity Sharpe must clear buy-and-hold's own
    # in BOTH the in-sample AND the OOS split. The equity-path Sharpe is scale-
    # invariant (annualized_sharpe_from_levels on JPY levels), so the SAME metric is
    # used for single- and multi-position strategies — no per-trade-Sharpe-vs-0 branch
    # (per-trade Sharpe ignores overlap and is not comparable to B&H's annualised
    # close-to-close Sharpe). OOS is now part of the gate, not just the overfit veto.
    ppy = (365 * 24 * 3600) / timeframe.seconds
    es_in = annualized_sharpe_from_levels(in_res.equity_curve, ppy)
    es_oos = annualized_sharpe_from_levels(oos_res.equity_curve, ppy)
    bench_in = annualized_sharpe_from_levels([b.close for b in in_bars], ppy, pct=True)
    bench_oos = annualized_sharpe_from_levels([b.close for b in oos_bars], ppy, pct=True)
    bench_sharpe = bench_in  # CycleResult.bench_sharpe keeps its IS meaning
    ship = (es_in >= bench_in) and (es_oos >= bench_oos) and consistent

    logger.info(
        "Cycle {}: IS Sharpe={:.3f} DD={:.4f} cost={:.1f}JPY | OOS Sharpe={:.3f} | "
        "bench(B&H, gross)={:.4f} | ship={} | eqSharpe IS={:.3f} (B&H {:.3f}) / "
        "OOS={:.3f} (B&H {:.3f})  [returns NET of fees]",
        strategy_name,
        m_in.sharpe,
        m_in.max_dd,
        m_in.total_cost,
        m_oos.sharpe,
        bench,
        ship,
        es_in, bench_in, es_oos, bench_oos,
    )
    logger.info(
        "  consistency (quarterly non-neg, relative gate): strategy={:.0%} vs B&H={:.0%} -> {}",
        strat_cons, bench_cons, "pass" if consistent else "FAIL",
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
