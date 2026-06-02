"""Score calibration: does the score rank fires? (guide §3).

Computes the Spearman rank correlation between ``sign_score`` and signed return,
plus a quartile EV table (Q1..Q4 with the Q4-Q1 spread).

Usage::

    uv run --env-file .env.bt python -m src.backtest.sign_score_calibration \
        --sign ema_atr_breakout --timeframe 5m
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
from loguru import logger

from src.backtest.sign_benchmark import measure_fires, split_in_out_sample
from src.core.types import Timeframe
from src.data.cache import load_cache
from src.logging_setup import configure_logging


@dataclass(frozen=True, slots=True)
class Calibration:
    """Score-calibration result.

    Attributes:
        n: Number of fires.
        spearman_rho: Rank correlation of score vs signed return.
        quartile_mean_r: Mean signed return per score quartile (Q1..Q4).
        q4_minus_q1: Q4 mean_r minus Q1 mean_r (the calibration spread).
    """

    n: int
    spearman_rho: float
    quartile_mean_r: list[float]
    q4_minus_q1: float


def calibrate(
    sign_name: str, timeframe: Timeframe, *, product: str | None = None
) -> Calibration:
    """Compute score calibration for a sign over in-sample bars.

    Args:
        sign_name: Registered sign.
        timeframe: Bar timeframe.
        product: Product code (defaults to configured).

    Returns:
        A :class:`Calibration`. ``spearman_rho`` is ``0.0`` for n < 10
        (insufficient data; see guide §7.4).
    """
    cache = load_cache(timeframe, product=product)
    in_sample, _ = split_in_out_sample(cache.bars)
    measured = [m for m in measure_fires(in_sample, sign_name) if m.signed_return != 0.0]

    scores = np.array([m.fire.score for m in measured], dtype=float)
    rets = np.array([m.signed_return for m in measured], dtype=float)
    n = int(scores.size)
    if n < 10:
        return Calibration(n, 0.0, [0.0, 0.0, 0.0, 0.0], 0.0)

    rho = _spearman(scores, rets)
    quartiles = _quartile_mean_r(scores, rets)
    return Calibration(n, rho, quartiles, quartiles[3] - quartiles[0])


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    try:
        from scipy.stats import spearmanr

        rho, _ = spearmanr(x, y)
        return float(rho) if rho == rho else 0.0  # NaN guard
    except Exception:
        # Rank-Pearson fallback.
        rx = np.argsort(np.argsort(x)).astype(float)
        ry = np.argsort(np.argsort(y)).astype(float)
        if rx.std() == 0 or ry.std() == 0:
            return 0.0
        return float(np.corrcoef(rx, ry)[0, 1])


def _quartile_mean_r(scores: np.ndarray, rets: np.ndarray) -> list[float]:
    order = np.argsort(scores)
    rets_sorted = rets[order]
    chunks = np.array_split(rets_sorted, 4)
    return [float(c.mean()) if c.size else 0.0 for c in chunks]


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Score calibration (Spearman + quartile EV).")
    parser.add_argument("--sign", required=True)
    parser.add_argument("--timeframe", choices=[tf.value for tf in Timeframe], default="5m")
    parser.add_argument(
        "--product", default=None, help="Product code (default: configured)."
    )
    args = parser.parse_args()

    from src.config import get_settings

    configure_logging(get_settings().log_level)
    cal = calibrate(args.sign, Timeframe(args.timeframe), product=args.product)
    logger.info(
        "n={} spearman_rho={:.4f} quartile_mean_r={} Q4-Q1={:.4f}",
        cal.n,
        cal.spearman_rho,
        [round(q, 4) for q in cal.quartile_mean_r],
        cal.q4_minus_q1,
    )


if __name__ == "__main__":
    main()
