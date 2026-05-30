"""Regime-split analysis: bear_DR vs bull_DR (guide §2.5).

Splits a sign's fires by the ATR regime at fire time and reports DR / mean_r /
n per regime, so a regime-specific edge can be detected and gated.

Usage::

    uv run --env-file .env.bt python -m src.backtest.sign_regime_analysis \
        --sign ema_atr_breakout --timeframe 5m
"""

from __future__ import annotations

import argparse

from loguru import logger

from src.backtest.metrics import SignMetrics, sign_metrics
from src.backtest.sign_benchmark import measure_fires, split_in_out_sample
from src.core.types import Timeframe
from src.data.cache import load_cache
from src.logging_setup import configure_logging


def regime_split(
    sign_name: str, timeframe: Timeframe, *, product: str | None = None
) -> dict[str, SignMetrics]:
    """Compute per-regime metrics for a sign over the in-sample bars.

    Args:
        sign_name: Registered sign.
        timeframe: Bar timeframe.
        product: Product code (defaults to configured).

    Returns:
        Mapping of regime label (``"bear"`` / ``"bull"`` / ``"all"``) to metrics.
    """
    cache = load_cache(timeframe, product=product)
    in_sample, _ = split_in_out_sample(cache.bars)
    measured = measure_fires(in_sample, sign_name)

    out: dict[str, SignMetrics] = {
        "all": sign_metrics([m.signed_return for m in measured]),
    }
    for regime in ("bear", "bull"):
        rs = [m.signed_return for m in measured if m.atr_regime == regime]
        out[regime] = sign_metrics(rs)
    return out


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Regime-split (ATR bear/bull) analysis.")
    parser.add_argument("--sign", required=True)
    parser.add_argument("--timeframe", choices=[tf.value for tf in Timeframe], default="5m")
    args = parser.parse_args()

    from src.config import get_settings

    configure_logging(get_settings().log_level)
    result = regime_split(args.sign, Timeframe(args.timeframe))
    for regime, m in result.items():
        logger.info(
            "{:>5} | n={:<5} DR={:.3f} mean_r={:.4f}", regime, m.n, m.dr, m.mean_r
        )


if __name__ == "__main__":
    main()
