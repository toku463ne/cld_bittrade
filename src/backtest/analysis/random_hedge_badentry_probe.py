"""Bad-entry probe for ``random_hedge`` — which entry contexts LOSE money?

Premise (user's intuition): *finding bad entries is easier than finding good
ones*. ``random_hedge`` opens a market-neutral long+short pair on random bars and
lets the asymmetric exit machinery shape the payoff. A pair's realised P&L is the
honest label here — in a trend one leg rides to a dense target while the other
takes a small zs stop (net positive); in chop BOTH legs whipsaw out at the stop
(net negative + double cost). So the question is: **what does the entry bar look
like when the pair loses?** If a context bucket is net-negative in BOTH the
in-sample and OOS splits (§6 degradation-over-absolute), it is an avoidable bad
entry — a quality gate to subtract from the random funnel.

Tagged features (all causal, computed at the entry bar):

- **volatility** — ATR(14) trailing percentile rank. Tests the
  ``density_multi_breakout`` finding "entering when there is no volatility makes
  more losses" on the random baseline.
- **bb_width** — Bollinger band width ``(upper-lower)/mid`` trailing rank (a
  coil / "no volatility" measure, signal-agnostic).
- **bb_pos** — Bollinger %B ``(close-lower)/(upper-lower)``: is price mid-band
  (ranging) or at an edge?
- **near_peak** — distance from the entry close to the nearest *confirmed*
  zigzag peak (size 12), as a fraction of price — proximity to trapped-trader
  structure.
- **long_candle** — the entry bar's own range ``(high-low)/close`` trailing rank
  — an outsized (exhaustion) candle.

Label = realised **pair** return in r-units (long leg + short leg, net of cost),
from an actual ``MultiSimulator`` run of ``random_hedge`` — not a forward return.

Usage::

    uv run --env-file .env.bt python -m src.backtest.analysis.random_hedge_badentry_probe \
        --timeframe 1h --product GMO_BTC_JPY
"""

from __future__ import annotations

import argparse
from collections import defaultdict

import numpy as np
import pandas as pd
from loguru import logger

from src.backtest.sign_benchmark import split_in_out_sample
from src.core.types import Side, Timeframe
from src.data.cache import load_cache
from src.indicators import atr
from src.indicators.bollinger import bollinger_bands
from src.indicators.zigzag import detect_peaks
from src.logging_setup import configure_logging
from src.simulator.multi_simulator import MultiSimulator
from src.strategy.random_hedge import RandomHedgeStrategy

RANK_WINDOW = 500
BB_PERIOD = 20
ZIGZAG_SIZE = 12
SIZE = 0.001  # MultiSimulator default per-leg size (for r-normalisation)


def _trailing_rank(series: np.ndarray, idx: int) -> float:
    window = series[max(0, idx - RANK_WINDOW) : idx + 1]
    return float((window <= series[idx]).mean())


def _quartile(rank: float) -> str:
    if rank < 0.25:
        return "Q1(low)"
    if rank < 0.50:
        return "Q2"
    if rank < 0.75:
        return "Q3"
    return "Q4(high)"


def _bb_pos_bucket(pos: float) -> str:
    if pos < 0.2:
        return "lower(<.2)"
    if pos < 0.4:
        return "mid-lo(.2-.4)"
    if pos < 0.6:
        return "middle(.4-.6)"
    if pos < 0.8:
        return "mid-hi(.6-.8)"
    return "upper(>.8)"


def _nearest_peak_frac(
    peak_idx: list[int], peak_price: list[float], t: int, entry: float
) -> float | None:
    """Fraction-of-price distance to the nearest peak confirmable by bar ``t``."""
    dists = [
        abs(peak_price[k] - entry) / entry
        for k in range(len(peak_idx))
        if peak_idx[k] + ZIGZAG_SIZE <= t
    ]
    return min(dists) if dists else None


def _stat(label: str, rows: list[float]) -> None:
    arr = np.array(rows, dtype=float)
    if arr.size == 0:
        logger.info("    {:<16} |    0 |   --  |     --     |    --", label)
        return
    win = float((arr > 0).mean())
    mr = float(arr.mean())
    logger.info(
        "    {:<16} | {:>4} | {:.3f} | {:+.6f} | {:+.4f}",
        label, arr.size, win, mr, float(arr.sum()),
    )


def _report(
    name: str, buckets: list[str], bucket_of: dict[int, str],
    is_mask: dict[int, bool], pair_r: dict[int, float],
) -> None:
    logger.info("  == {} ==", name)
    for sample, want_is in (("IN-SAMPLE", True), ("OOS", False)):
        logger.info("  [{}]  bucket           |  n_pr | win%  |   mean_r   |  sum_r", sample)
        for b in buckets:
            rows = [pair_r[k] for k, bk in bucket_of.items() if bk == b and is_mask[k] == want_is]
            _stat(b, rows)


def run(tf: Timeframe, *, product: str | None) -> None:
    """Run random_hedge, label each entry pair by realised r, tag by context."""
    cache = load_cache(tf, product=product)
    in_bars, oos_bars = split_in_out_sample(cache.bars)
    split_ts = oos_bars[0].timestamp
    bars = list(in_bars) + list(oos_bars)

    # 1. Realised pair outcomes from an actual random_hedge run.
    result = MultiSimulator(RandomHedgeStrategy(), size=SIZE).run(bars)
    legs_by_entry: dict[object, dict[Side, float]] = defaultdict(dict)
    for tr in result.trades:
        r = tr.pnl / (tr.entry_price * tr.size)  # net return in r-units
        legs_by_entry[tr.entry_time][tr.side] = legs_by_entry[tr.entry_time].get(tr.side, 0.0) + r
    pairs = {
        et: legs[Side.LONG] + legs[Side.SHORT]
        for et, legs in legs_by_entry.items()
        if Side.LONG in legs and Side.SHORT in legs
    }
    logger.info(
        "{} {} — {} trades, {} complete hedged pairs (split@{})",
        tf.value, product or "configured", len(result.trades), len(pairs), split_ts,
    )

    # 2. Causal feature series.
    df = pd.DataFrame(
        {
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
        },
        index=pd.DatetimeIndex([b.timestamp for b in bars]),
    )
    closes = df["close"].to_numpy(dtype=float)
    atr_s = atr(df, 14).to_numpy(dtype=float)
    bb = bollinger_bands(df["close"], BB_PERIOD)
    width = ((bb["bb_upper"] - bb["bb_lower"]) / bb["bb_mid"].replace(0.0, np.nan)).to_numpy(dtype=float)
    span = (bb["bb_upper"] - bb["bb_lower"]).replace(0.0, np.nan)
    bb_pos = ((df["close"] - bb["bb_lower"]) / span).to_numpy(dtype=float)
    crange = ((df["high"] - df["low"]) / df["close"]).to_numpy(dtype=float)
    ts_to_idx = {ts: i for i, ts in enumerate(df.index)}

    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    peaks = detect_peaks(highs, lows, size=ZIGZAG_SIZE)
    peak_idx = [p.bar_index for p in peaks]
    peak_price = [p.price for p in peaks]

    # 3. Tag each pair (the entry bar is the bar BEFORE the fill — two-bar rule;
    #    features must be read at the signal bar, t = fill_idx - 1).
    is_mask: dict[int, bool] = {}
    pair_r: dict[int, float] = {}
    vol_b: dict[int, str] = {}
    width_b: dict[int, str] = {}
    pos_b: dict[int, str] = {}
    peak_b: dict[int, str] = {}
    candle_b: dict[int, str] = {}
    key = 0
    skipped = 0
    for entry_time, pr in pairs.items():
        fill_idx = ts_to_idx.get(pd.Timestamp(entry_time))
        if fill_idx is None or fill_idx == 0:
            skipped += 1
            continue
        t = fill_idx - 1  # signal bar
        if np.isnan(atr_s[t]) or np.isnan(width[t]) or np.isnan(bb_pos[t]):
            skipped += 1
            continue
        npf = _nearest_peak_frac(peak_idx, peak_price, t, closes[t])
        if npf is None:
            skipped += 1
            continue
        pair_r[key] = pr
        is_mask[key] = pd.Timestamp(entry_time) < pd.Timestamp(split_ts)
        vol_b[key] = _quartile(_trailing_rank(atr_s, t))
        width_b[key] = _quartile(_trailing_rank(width, t))
        pos_b[key] = _bb_pos_bucket(bb_pos[t])
        peak_b[key] = _peak_bucket(npf)
        candle_b[key] = _quartile(_trailing_rank(crange, t))
        key += 1
    logger.info("  tagged {} pairs ({} skipped for warmup/NaN)", key, skipped)

    logger.info("  == ALL (baseline) ==")
    logger.info("  [IN-SAMPLE]  bucket           |  n_pr | win%  |   mean_r   |  sum_r")
    _stat("ALL", [pair_r[k] for k in pair_r if is_mask[k]])
    logger.info("  [OOS]        bucket           |  n_pr | win%  |   mean_r   |  sum_r")
    _stat("ALL", [pair_r[k] for k in pair_r if not is_mask[k]])

    q = ["Q1(low)", "Q2", "Q3", "Q4(high)"]
    _report("VOLATILITY (ATR pct)", q, vol_b, is_mask, pair_r)
    _report("BB WIDTH (coil) pct", q, width_b, is_mask, pair_r)
    _report(
        "BB POSITION (%B)",
        ["lower(<.2)", "mid-lo(.2-.4)", "middle(.4-.6)", "mid-hi(.6-.8)", "upper(>.8)"],
        pos_b, is_mask, pair_r,
    )
    _report(
        "NEAR ZIGZAG PEAK (dist frac)",
        ["near(<.5%)", "<1%", "<2%", "far(>2%)"],
        peak_b, is_mask, pair_r,
    )
    _report("LONG CANDLE (range pct)", q, candle_b, is_mask, pair_r)


def _peak_bucket(frac: float) -> str:
    if frac < 0.005:
        return "near(<.5%)"
    if frac < 0.01:
        return "<1%"
    if frac < 0.02:
        return "<2%"
    return "far(>2%)"


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="random_hedge bad-entry context probe.")
    parser.add_argument("--timeframe", choices=[tf.value for tf in Timeframe], default="1h")
    parser.add_argument("--product", default=None)
    args = parser.parse_args()
    configure_logging()
    run(Timeframe(args.timeframe), product=args.product)


if __name__ == "__main__":
    main()
