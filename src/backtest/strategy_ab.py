"""Strategy-level A/B test (the binding ship gate; guide §5).

Runs two strategy variants over the SAME bars with the SAME size and compares
the portfolio metrics. The pre-registered ship gate is committed in code here
BEFORE results are seen (guide §5.3): SHIP iff
``(a) avg Sharpe >= baseline`` AND ``(b) >= 4/5 months non-negative``.
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from src.backtest.metrics import PortfolioMetrics, portfolio_metrics
from src.core.types import Bar, Trade
from src.simulator import Simulator
from src.strategy.base import Strategy


@dataclass(frozen=True, slots=True)
class ABResult:
    """Result of an A/B comparison.

    Attributes:
        arm_a: Baseline portfolio metrics.
        arm_b: Variant portfolio metrics.
        months_non_negative: Count of non-negative months for the variant.
        n_months: Total months in the test.
        ship: Whether the pre-registered gate passed.
    """

    arm_a: PortfolioMetrics
    arm_b: PortfolioMetrics
    months_non_negative: int
    n_months: int
    ship: bool


def _monthly_returns(trades: list[Trade]) -> dict[str, float]:
    by_month: dict[str, float] = {}
    for t in trades:
        key = t.exit_time.strftime("%Y-%m")
        by_month[key] = by_month.get(key, 0.0) + t.return_pct
    return by_month


def run_ab(baseline: Strategy, variant: Strategy, bars: list[Bar], *, size: float = 0.001) -> ABResult:
    """Run an A/B test between two strategies.

    Args:
        baseline: Arm A.
        variant: Arm B.
        bars: Shared bar series.
        size: Shared position size.

    Returns:
        An :class:`ABResult` including the pre-registered ship decision.
    """
    res_a = Simulator(baseline, size=size).run(bars)
    res_b = Simulator(variant, size=size).run(bars)
    m_a = portfolio_metrics(res_a.trades)
    m_b = portfolio_metrics(res_b.trades)

    monthly_b = _monthly_returns(res_b.trades)
    n_months = len(monthly_b)
    non_neg = sum(1 for v in monthly_b.values() if v >= 0.0)

    # Pre-registered gate (committed BEFORE seeing results).
    gate_a = m_b.sharpe >= m_a.sharpe
    gate_b = (non_neg / n_months) >= 0.8 if n_months else False
    ship = gate_a and gate_b

    logger.info(
        "A/B {} vs {}: Sharpe {:.3f} -> {:.3f}; {}/{} months non-neg; SHIP={}",
        baseline.name,
        variant.name,
        m_a.sharpe,
        m_b.sharpe,
        non_neg,
        n_months,
        ship,
    )
    return ABResult(m_a, m_b, non_neg, n_months, ship)
