"""Metric mathematics for sign- and strategy-level evaluation.

Implements the formulas in ``docs/evaluation_guide.md``:

- Signal-level (diagnostic only): DR, mean_r, binomial p, permutation perm_p,
  EV decomposition.
- Portfolio-level (ship criteria): Sharpe, Sortino, win rate, profit factor,
  max drawdown, total return.

Per CLAUDE.md: signal-level metrics are diagnostic only and are NEVER used as
ship criteria.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from src.core.types import Trade


# --------------------------------------------------------------------------- #
# Signal-level (per-fire) metrics
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class SignMetrics:
    """Per-fire diagnostic metrics for a set of fires.

    Attributes:
        n: Number of fires.
        dr: Direction rate (fraction with trend_dir > 0).
        mean_r: Mean signed return per fire.
        ev: Expected value (== mean_r; reported for parity with the rubric).
        binom_p: Two-sided binomial p-value vs DR = 0.5.
        perm_p: Permutation p-value (placeholder 1.0 unless computed separately).
        avg_win: Mean signed return among up-fires.
        avg_loss: Mean signed return among down-fires (negative).
        win_rate: Same as DR (kept for table parity).
    """

    n: int
    dr: float
    mean_r: float
    ev: float
    binom_p: float
    perm_p: float
    avg_win: float
    avg_loss: float
    win_rate: float


def binomial_p(wins: int, n: int) -> float:
    """Two-sided binomial p-value testing DR against 0.5.

    Args:
        wins: Number of up-direction fires.
        n: Total fires.

    Returns:
        The two-sided p-value (1.0 when ``n == 0``).
    """
    if n == 0:
        return 1.0
    try:
        from scipy.stats import binomtest

        return float(binomtest(wins, n, 0.5, alternative="two-sided").pvalue)
    except Exception:
        # Normal approximation fallback.
        mean = 0.5 * n
        sd = math.sqrt(0.25 * n)
        if sd == 0.0:
            return 1.0
        z = abs(wins - mean) / sd
        return float(math.erfc(z / math.sqrt(2.0)))


def permutation_p(
    trend_dirs: list[int], n_shuffles: int = 1000, seed: int = 0
) -> float:
    """Permutation p-value: real DR vs DR over shuffled outcomes.

    Shuffling the outcome labels preserves the base rate while destroying any
    timing information, answering "is the timing informative?" (guide §2.4).

    Args:
        trend_dirs: Per-fire ``trend_dir`` values (+1 / -1 / 0).
        n_shuffles: Number of shuffles.
        seed: RNG seed.

    Returns:
        Fraction of shuffles whose DR >= the real DR.
    """
    dirs = np.array([1 if d > 0 else 0 for d in trend_dirs], dtype=float)
    n = len(dirs)
    if n == 0:
        return 1.0
    real_dr = dirs.mean()
    rng = np.random.default_rng(seed)
    ge = 0
    for _ in range(n_shuffles):
        if rng.permutation(dirs).mean() >= real_dr:
            ge += 1
    return ge / n_shuffles


def sign_metrics(signed_returns: list[float], *, with_perm: bool = False) -> SignMetrics:
    """Compute per-fire diagnostic metrics from signed returns.

    Args:
        signed_returns: ``trend_dir * magnitude`` per fire.
        with_perm: Whether to compute the (expensive) permutation p-value.

    Returns:
        A :class:`SignMetrics`.
    """
    arr = np.array([r for r in signed_returns if r != 0.0], dtype=float)
    n = int(arr.size)
    if n == 0:
        return SignMetrics(0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0)

    wins_mask = arr > 0.0
    wins = int(wins_mask.sum())
    dr = wins / n
    mean_r = float(arr.mean())
    avg_win = float(arr[wins_mask].mean()) if wins else 0.0
    losses = arr[~wins_mask]
    avg_loss = float(losses.mean()) if losses.size else 0.0
    binom = binomial_p(wins, n)
    perm = permutation_p([1 if r > 0 else -1 for r in arr]) if with_perm else 1.0
    return SignMetrics(
        n=n,
        dr=dr,
        mean_r=mean_r,
        ev=mean_r,
        binom_p=binom,
        perm_p=perm,
        avg_win=avg_win,
        avg_loss=avg_loss,
        win_rate=dr,
    )


# --------------------------------------------------------------------------- #
# Portfolio-level (strategy) metrics
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class PortfolioMetrics:
    """Strategy-level metrics (the GO/ship criteria inputs).

    Attributes:
        n_trades: Number of trades.
        total_return: Sum of per-trade fractional returns.
        sharpe: Per-trade Sharpe (mean/std of trade returns).
        sortino: Per-trade Sortino (mean/std of downside returns).
        win_rate: Fraction of profitable trades.
        profit_factor: Gross profit / gross loss.
        max_dd: Maximum drawdown of the cumulative-return curve (fractional).
    """

    n_trades: int
    total_return: float
    sharpe: float
    sortino: float
    win_rate: float
    profit_factor: float
    max_dd: float


def max_drawdown(equity_curve: list[float]) -> float:
    """Compute the maximum peak-to-trough drawdown of a cumulative curve.

    Args:
        equity_curve: Cumulative PnL or return values.

    Returns:
        The largest peak-to-trough decline (non-negative).
    """
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        peak = max(peak, v)
        max_dd = max(max_dd, peak - v)
    return max_dd


def portfolio_metrics(trades: list[Trade]) -> PortfolioMetrics:
    """Compute strategy-level metrics from a list of trades.

    Args:
        trades: Completed trades.

    Returns:
        A :class:`PortfolioMetrics`.
    """
    if not trades:
        return PortfolioMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    rets = np.array([t.return_pct for t in trades], dtype=float)
    n = int(rets.size)
    total = float(rets.sum())
    std = float(rets.std(ddof=1)) if n > 1 else 0.0
    sharpe = float(rets.mean() / std) if std > 0.0 else 0.0
    downside = rets[rets < 0.0]
    dstd = float(downside.std(ddof=1)) if downside.size > 1 else 0.0
    sortino = float(rets.mean() / dstd) if dstd > 0.0 else 0.0
    win_rate = float((rets > 0.0).mean())
    gross_profit = float(rets[rets > 0.0].sum())
    gross_loss = float(-rets[rets < 0.0].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0.0 else math.inf

    cum: list[float] = []
    running = 0.0
    for r in rets:
        running += r
        cum.append(running)
    dd = max_drawdown(cum)

    return PortfolioMetrics(
        n_trades=n,
        total_return=total,
        sharpe=sharpe,
        sortino=sortino,
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_dd=dd,
    )


def buy_and_hold_return(first_close: float, last_close: float) -> float:
    """Benchmark return for buy-and-hold BTC/JPY (NOT cash; per CLAUDE.md).

    Args:
        first_close: Close of the first bar in the period.
        last_close: Close of the last bar in the period.

    Returns:
        Fractional buy-and-hold return.
    """
    if first_close <= 0.0:
        return 0.0
    return (last_close - first_close) / first_close
