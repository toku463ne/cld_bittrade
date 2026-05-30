"""Marginal contribution analysis (guide §5.4).

Reports per-trade marginal metrics between two A/B arms: turnover delta, max-DD
delta, per-period return correlation (duplication check) and tail-hedge lift.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.backtest.metrics import portfolio_metrics
from src.core.types import Trade


@dataclass(frozen=True, slots=True)
class MarginalResult:
    """Marginal contribution of arm B over arm A.

    Attributes:
        d_trade_count: ``n(B) - n(A)`` (turnover impact).
        d_max_dd: ``dd(B) - dd(A)`` (worst-case change).
        daily_corr: Pearson corr of per-period returns (>0.7 = duplication).
        tail_hedge_lift: B minus A mean return over A's worst-quintile periods.
    """

    d_trade_count: int
    d_max_dd: float
    daily_corr: float
    tail_hedge_lift: float


def _period_returns(trades: list[Trade]) -> dict[str, float]:
    out: dict[str, float] = {}
    for t in trades:
        key = t.exit_time.strftime("%Y-%m-%d")
        out[key] = out.get(key, 0.0) + t.return_pct
    return out


def marginal_contribution(arm_a: list[Trade], arm_b: list[Trade]) -> MarginalResult:
    """Compute marginal metrics of arm B relative to arm A.

    Args:
        arm_a: Baseline trades.
        arm_b: Variant trades.

    Returns:
        A :class:`MarginalResult`.
    """
    m_a = portfolio_metrics(arm_a)
    m_b = portfolio_metrics(arm_b)

    ra = _period_returns(arm_a)
    rb = _period_returns(arm_b)
    keys = sorted(set(ra) | set(rb))
    va = np.array([ra.get(k, 0.0) for k in keys], dtype=float)
    vb = np.array([rb.get(k, 0.0) for k in keys], dtype=float)

    if va.size > 1 and va.std() > 0 and vb.std() > 0:
        corr = float(np.corrcoef(va, vb)[0, 1])
    else:
        corr = 0.0

    # Tail-hedge: A's worst quintile of periods.
    tail_lift = 0.0
    if va.size >= 5:
        cutoff = np.quantile(va, 0.2)
        mask = va <= cutoff
        if mask.any():
            tail_lift = float(vb[mask].mean() - va[mask].mean())

    return MarginalResult(
        d_trade_count=m_b.n_trades - m_a.n_trades,
        d_max_dd=m_b.max_dd - m_a.max_dd,
        daily_corr=corr,
        tail_hedge_lift=tail_lift,
    )
