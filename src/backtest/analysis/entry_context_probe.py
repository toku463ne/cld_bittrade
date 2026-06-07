"""Harness-level entry-context probe — does a signal-agnostic regime gate work?

This is deliberately NOT a sign-level study. It pools the entries of *every*
registered directional sign into one wide funnel (the union of all entry bars any
sign produces — the single-position simulator would have dropped most of these),
then asks a harness question: tagging each entry by **context** that is computable
for any signal, does some context bucket separate positive- from
negative-expectancy entries — with the *same sign in BOTH the in-sample and OOS
splits* (§6 degradation-over-absolute)?

Context is gated, not direction. The entry-horizon work established breakouts are
DR ~ 0.50 (no directional entry edge), so we do not re-pick direction; we ask
*when* (in what regime) the pooled entries pay off. Three features:

- **trend regime**  : close vs EMA-200 and the EMA-200 slope, expressed as
  alignment with the entry side (with-trend / against-trend).
- **volatility regime** : ATR(14) trailing percentile rank (low..high vol).
- **recent realized range** : trailing 24-bar (high-low)/close, trailing percentile
  rank (coil tightness, signal-agnostic).

Each entry is scored by the signed forward return at the ride horizon (48h, 96h),
same as ``entry_horizon_probe``. Per-bucket DR / mean_r / per-trade Sharpe are
reported for IS and OOS side by side, plus a per-sign contribution count so a
"pooled" verdict that is really one sign is visible.

Causality: features at bar ``t`` use only bars ``<= t`` (EMA/ATR are causal;
percentile ranks use a trailing window). The forward return is the label, not a
feature.

Usage::

    uv run --env-file .env.bt python -m src.backtest.analysis.entry_context_probe \
        --timeframe 1h --product GMO_BTC_JPY
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from loguru import logger

from src.backtest.sign_benchmark import split_in_out_sample
from src.core.types import Side, Timeframe
from src.data.cache import load_cache
from src.indicators import atr, ema
from src.logging_setup import configure_logging
from src.signs.registry import all_signs, get_sign

HORIZON_HOURS = [48, 96]
EMA_LEN = 200
SLOPE_LOOKBACK = 20
RR_LOOKBACK = 24
RANK_WINDOW = 500  # trailing bars for percentile ranks
MIN_IDX = RANK_WINDOW  # need a full trailing window for ranks (covers EMA/ATR too)


def _bph(tf: Timeframe) -> float:
    return 60.0 / {"1m": 1, "5m": 5, "15m": 15, "1h": 60}[tf.value]


def _trailing_rank(series: np.ndarray, idx: int) -> float:
    """Fraction of the trailing ``RANK_WINDOW`` values <= the value at ``idx``."""
    window = series[idx - RANK_WINDOW : idx + 1]
    return float((window <= series[idx]).mean())


def _quartile(rank: float) -> str:
    if rank < 0.25:
        return "Q1(low)"
    if rank < 0.50:
        return "Q2"
    if rank < 0.75:
        return "Q3"
    return "Q4(high)"


def _trend_bucket(close_t: float, ema_t: float, ema_prev: float, side_sign: int) -> str:
    """Alignment of the entry side with location vs EMA-200 and EMA-200 slope."""
    loc = 1 if close_t > ema_t else -1
    slope = 1 if ema_t > ema_prev else -1
    aligned_loc = loc == side_sign
    aligned_slope = slope == side_sign
    if aligned_loc and aligned_slope:
        return "with-trend"
    if (not aligned_loc) and (not aligned_slope):
        return "against-trend"
    return "mixed"


def _stat(label: str, signed: list[float]) -> None:
    arr = np.array([s for s in signed if not np.isnan(s)])
    if arr.size == 0:
        logger.info("    {:<16} |    0 |   --  |    --    |   --", label)
        return
    dr = float((arr > 0).mean())
    mr = float(arr.mean())
    sh = mr / float(arr.std()) if arr.std() > 0 else 0.0
    logger.info("    {:<16} | {:>4} | {:.3f} | {:+.5f} | {:+.4f}", label, arr.size, dr, mr, sh)


def _report_feature(
    name: str,
    buckets: list[str],
    bucket_of: dict[int, str],
    in_mask: dict[int, bool],
    signed: dict[int, float],
) -> None:
    """Print IS then OOS per-bucket expectancy for one context feature."""
    logger.info("  == {} ==", name)
    for sample, want_in in (("IN-SAMPLE", True), ("OOS", False)):
        logger.info("  [{}]  bucket           |    n |   DR  |  mean_r  | Sharpe", sample)
        for b in buckets:
            rows = [
                signed[i]
                for i, bk in bucket_of.items()
                if bk == b and in_mask[i] == want_in
            ]
            _stat(b, rows)


def run(tf: Timeframe, *, product: str | None) -> None:
    """Pool all signs' entries, tag by context regime, report IS/OOS expectancy."""
    cache = load_cache(tf, product=product)
    in_bars, oos_bars = split_in_out_sample(cache.bars)
    split_idx = len(in_bars)
    bars = list(in_bars) + list(oos_bars)
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
    closes = df["close"].to_numpy(dtype=float)
    n = closes.size
    ts_to_idx = {ts: i for i, ts in enumerate(df.index)}

    # Context series (all causal).
    ema_s = ema(df["close"], EMA_LEN).to_numpy(dtype=float)
    atr_s = atr(df, 14).to_numpy(dtype=float)
    rr_s = (
        (df["high"].rolling(RR_LOOKBACK).max() - df["low"].rolling(RR_LOOKBACK).min())
        / df["close"]
    ).to_numpy(dtype=float)

    # Pool the union of every sign's entry bars: key = (idx, side_sign).
    pool: dict[tuple[int, int], set[str]] = {}
    per_sign: dict[str, int] = {}
    for sign_name in all_signs():
        fires = get_sign(sign_name).detect(df)
        per_sign[sign_name] = len(fires)
        for f in fires:
            i = ts_to_idx[pd.Timestamp(f.fired_at)]
            if i < MIN_IDX:
                continue
            ss = 1 if f.side is Side.LONG else -1
            pool.setdefault((i, ss), set()).add(sign_name)

    logger.info(
        "{} {} — pooled {} unique entry-bars from {} signs ({} bars, split@{})",
        tf.value, product or "configured", len(pool), len(per_sign), n, split_idx,
    )
    logger.info("  per-sign fires: {}", ", ".join(f"{k}={v}" for k, v in sorted(per_sign.items())))

    bph = _bph(tf)
    for h in HORIZON_HOURS:
        hb = int(round(h * bph))
        # Per-entry: signed fwd return, IS/OOS flag, and the three bucket labels.
        signed: dict[int, float] = {}
        in_mask: dict[int, bool] = {}
        trend_b: dict[int, str] = {}
        vol_b: dict[int, str] = {}
        rr_b: dict[int, str] = {}
        key = 0
        for (i, ss), _signs in pool.items():
            if np.isnan(ema_s[i]) or np.isnan(atr_s[i]) or np.isnan(rr_s[i]):
                continue
            fwd = ss * (closes[i + hb] - closes[i]) / closes[i] if i + hb < n else np.nan
            signed[key] = fwd
            in_mask[key] = i < split_idx
            trend_b[key] = _trend_bucket(closes[i], ema_s[i], ema_s[i - SLOPE_LOOKBACK], ss)
            vol_b[key] = _quartile(_trailing_rank(atr_s, i))
            rr_b[key] = _quartile(_trailing_rank(rr_s, i))
            key += 1

        logger.info("================ horizon {}h ({}b) ================", h, hb)
        logger.info("  == ALL (baseline) ==")
        logger.info("  [IN-SAMPLE]  bucket           |    n |   DR  |  mean_r  | Sharpe")
        _stat("ALL", [v for k, v in signed.items() if in_mask[k]])
        logger.info("  [OOS]        bucket           |    n |   DR  |  mean_r  | Sharpe")
        _stat("ALL", [v for k, v in signed.items() if not in_mask[k]])
        _report_feature("TREND regime", ["with-trend", "mixed", "against-trend"], trend_b, in_mask, signed)
        _report_feature("VOLATILITY regime (ATR pct)", ["Q1(low)", "Q2", "Q3", "Q4(high)"], vol_b, in_mask, signed)
        _report_feature("RECENT RANGE (pct)", ["Q1(low)", "Q2", "Q3", "Q4(high)"], rr_b, in_mask, signed)


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Harness-level pooled entry-context probe.")
    parser.add_argument("--timeframe", choices=[tf.value for tf in Timeframe], default="1h")
    parser.add_argument("--product", default=None)
    args = parser.parse_args()
    configure_logging()
    run(Timeframe(args.timeframe), product=args.product)


if __name__ == "__main__":
    main()
