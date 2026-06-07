"""Per-fire sign benchmark (canonical pipeline).

Runs a registered sign over a bar series, measures each fire's outcome via the
windowed zigzag (``src/backtest/zigzag.py``), persists per-fire rows to
``sign_fire`` and a pooled aggregate to ``sign_benchmark_run``.

Phases:

- ``benchmark`` — in-sample (all bars except the most recent 20%).
- ``backtest``  — OOS (the most recent 20% of bars).

Usage::

    uv run --env-file .env.bt python -m src.backtest.sign_benchmark \
        --sign ema_atr_breakout --timeframe 5m --phase benchmark
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import pandas as pd
from loguru import logger
from sqlalchemy import delete

from src.backtest.metrics import SignMetrics, sign_metrics
from src.backtest.zigzag import first_zigzag_peak
from src.core.types import Bar, Side, Timeframe
from src.data.cache import load_cache
from src.db import get_session
from src.indicators import atr, atr_average
from src.logging_setup import configure_logging
from src.models import SignBenchmarkRun, SignFire
from src.signs.base import FireEvent
from src.signs.registry import get_sign

OOS_FRACTION = 0.2


@dataclass(frozen=True, slots=True)
class MeasuredFire:
    """A fire with its measured outcome and regime label."""

    fire: FireEvent
    trend_dir: int
    magnitude: float
    signed_return: float
    atr_regime: str


def split_in_out_sample(bars: list[Bar]) -> tuple[list[Bar], list[Bar]]:
    """Split bars into in-sample / OOS by the most-recent-20% rule.

    The canonical split for the *already-shipped* strategies (do not change it for
    them — that would be goalpost-moving). For evaluating **new** ideas in the
    idea/exploration stage, prefer :func:`split_lockbox` (a fixed pre-registered
    holdout) so the OOS is honest without waiting weeks for live paper-forward.

    Args:
        bars: Time-ordered bars.

    Returns:
        ``(in_sample, oos)`` where OOS is the most recent ``OOS_FRACTION``.
    """
    if not bars:
        return [], []
    cut = int(len(bars) * (1.0 - OOS_FRACTION))
    return bars[:cut], bars[cut:]


# Fixed idea-stage lockbox OOS (pre-registered 2026-06-07). Tune NEW ideas only on
# bars before LOCKBOX_OOS_START; evaluate once on [start, end). A historical holdout
# gives an honest OOS instantly — far faster than waiting for live paper-forward — at
# the cost that reusing it across many ideas erodes it (so the eventual *finalist*
# still earns a fresh live-forward check before real capital). See eval_criteria §6.5.
LOCKBOX_OOS_START = pd.Timestamp("2025-04-01", tz="Asia/Tokyo")
LOCKBOX_OOS_END = pd.Timestamp("2026-04-01", tz="Asia/Tokyo")


def split_lockbox(
    bars: list[Bar],
    start: pd.Timestamp = LOCKBOX_OOS_START,
    end: pd.Timestamp = LOCKBOX_OOS_END,
) -> tuple[list[Bar], list[Bar]]:
    """Date-windowed split: IS = bars before ``start``; OOS = ``[start, end)``.

    The idea-stage holdout (default 2025-04-01 → 2026-04-01). Bars at/after ``end``
    are excluded from both (a thin live-forward buffer).

    Args:
        bars: Time-ordered bars.
        start: OOS window start (inclusive).
        end: OOS window end (exclusive).

    Returns:
        ``(in_sample, oos)``.
    """
    in_s = [b for b in bars if pd.Timestamp(b.timestamp) < start]
    oos = [b for b in bars if start <= pd.Timestamp(b.timestamp) < end]
    return in_s, oos


def _regime_labels(df: pd.DataFrame, atr_period: int = 14, avg_period: int = 50) -> pd.Series:
    """Label each bar bear/bull by the ATR regime defined in the guide §2.5.

    bear = ATR(14) > 1.5 × 50-bar ATR average (high volatility); else bull.
    """
    atr_s = atr(df, atr_period)
    avg = atr_average(atr_s, avg_period)
    bear = (avg > 0.0) & (atr_s > 1.5 * avg)
    return bear.map({True: "bear", False: "bull"})


def measure_fires(bars: list[Bar], sign_name: str, *, window: int = 30) -> list[MeasuredFire]:
    """Detect and measure all fires of ``sign_name`` over ``bars``.

    Args:
        bars: Time-ordered bars.
        sign_name: Registered sign name.
        window: Zigzag look-ahead window in bars.

    Returns:
        Measured fires (those with ``trend_dir == 0`` are kept but flagged).
    """
    if not bars:
        return []
    df = pd.DataFrame(
        {
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
        },
        index=pd.DatetimeIndex([b.timestamp for b in bars], name="timestamp"),
    )
    closes = df["close"].tolist()
    ts_to_idx = {ts: i for i, ts in enumerate(df.index)}
    regimes = _regime_labels(df)

    sign = get_sign(sign_name)
    fires = sign.detect(df)

    measured: list[MeasuredFire] = []
    for fire in fires:
        idx = ts_to_idx[pd.Timestamp(fire.fired_at)]
        outcome = first_zigzag_peak(closes, idx, window=window)
        # Express outcome from the fire's directional perspective:
        # a SHORT fire "wins" when price goes down (trend_dir == -1).
        if fire.side is Side.SHORT:
            signed = -outcome.signed_return
            trend = -outcome.trend_dir
        else:
            signed = outcome.signed_return
            trend = outcome.trend_dir
        measured.append(
            MeasuredFire(
                fire=fire,
                trend_dir=trend,
                magnitude=outcome.magnitude,
                signed_return=signed,
                atr_regime=str(regimes.iloc[idx]),
            )
        )
    return measured


def run_benchmark(
    sign_name: str,
    timeframe: Timeframe,
    *,
    phase: str = "benchmark",
    product: str | None = None,
    persist: bool = True,
) -> SignMetrics:
    """Run the per-fire benchmark for one sign and one phase.

    Args:
        sign_name: Registered sign.
        timeframe: Bar timeframe.
        phase: ``benchmark`` (in-sample) or ``backtest`` (OOS).
        product: Product code (defaults to configured).
        persist: Whether to write rows to the DB.

    Returns:
        Pooled :class:`SignMetrics` for the phase.
    """
    cache = load_cache(timeframe, product=product)
    in_sample, oos = split_in_out_sample(cache.bars)
    bars = oos if phase == "backtest" else in_sample
    logger.info(
        "Benchmark sign={} phase={} timeframe={}: {} bars",
        sign_name,
        phase,
        timeframe.value,
        len(bars),
    )

    measured = measure_fires(bars, sign_name)
    signed = [m.signed_return for m in measured]
    metrics = sign_metrics(signed, with_perm=True)
    logger.info(
        "  -> n={} DR={:.3f} mean_r={:.4f} perm_p={:.3f}",
        metrics.n,
        metrics.dr,
        metrics.mean_r,
        metrics.perm_p,
    )

    if persist:
        _persist(sign_name, timeframe, phase, product, measured, metrics)
    return metrics


def _persist(
    sign_name: str,
    timeframe: Timeframe,
    phase: str,
    product: str | None,
    measured: list[MeasuredFire],
    metrics: SignMetrics,
) -> None:
    from src.config import get_settings

    prod = product or get_settings().product_code
    with get_session() as session:
        # Replace prior fires for this (sign, timeframe, phase-agnostic product).
        session.execute(
            delete(SignFire).where(
                SignFire.sign_type == sign_name,
                SignFire.product == prod,
                SignFire.timeframe == timeframe.value,
            )
            if phase == "benchmark"
            else delete(SignFire).where(SignFire.id == -1)  # no-op for OOS
        )
        for m in measured:
            session.add(
                SignFire(
                    sign_type=sign_name,
                    product=prod,
                    timeframe=timeframe.value,
                    fired_at=m.fire.fired_at,
                    side=m.fire.side.value,
                    score=m.fire.score,
                    trend_dir=m.trend_dir,
                    magnitude=m.magnitude,
                    signed_return=m.signed_return,
                    atr_regime=m.atr_regime,
                )
            )
        session.add(
            SignBenchmarkRun(
                sign_type=sign_name,
                strategy=sign_name,
                phase=phase,
                period="pooled",
                n_events=metrics.n,
                dr=metrics.dr,
                mean_r=metrics.mean_r,
                ev=metrics.ev,
                perm_p=metrics.perm_p,
            )
        )
    logger.info("Persisted {} fires + pooled run for {} ({}).", len(measured), sign_name, phase)


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Run the per-fire sign benchmark.")
    parser.add_argument("--sign", required=True, help="Registered sign name.")
    parser.add_argument(
        "--timeframe", choices=[tf.value for tf in Timeframe], default="5m"
    )
    parser.add_argument("--phase", choices=["benchmark", "backtest"], default="benchmark")
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()

    from src.config import get_settings

    configure_logging(get_settings().log_level)
    run_benchmark(
        args.sign,
        Timeframe(args.timeframe),
        phase=args.phase,
        persist=not args.no_persist,
    )


if __name__ == "__main__":
    main()
