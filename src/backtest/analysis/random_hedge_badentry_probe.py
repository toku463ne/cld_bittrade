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
from src.indicators.density import time_at_price_profile, value_area
from src.indicators.zigzag import detect_peaks
from src.logging_setup import configure_logging
from src.simulator.multi_simulator import MultiSimulator
from src.strategy.random_hedge import RandomHedgeStrategy

RANK_WINDOW = 500
BB_PERIOD = 20
ZIGZAG_SIZE = 12
CHOP_WIN = 14  # Choppiness Index lookback
AC_WIN = 48  # return autocorrelation window
VA_WIN = 168  # trailing window for the value-area position feature
VA_BINS = 48
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
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
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

    # --- batch 2: chop / trend-persistence / indecision / congestion / conviction ---
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    rng = df["high"].rolling(CHOP_WIN).max() - df["low"].rolling(CHOP_WIN).min()
    chop_s = (
        100.0 * np.log10((tr.rolling(CHOP_WIN).sum() / rng.replace(0.0, np.nan))) / np.log10(CHOP_WIN)
    ).to_numpy(dtype=float)  # high = sideways/choppy, low = trending
    ret = df["close"].pct_change()
    x, y = ret, ret.shift(1)
    cov = (x * y).rolling(AC_WIN).mean() - x.rolling(AC_WIN).mean() * y.rolling(AC_WIN).mean()
    den = x.rolling(AC_WIN).std(ddof=0) * y.rolling(AC_WIN).std(ddof=0)
    ac_s = (cov / den.replace(0.0, np.nan)).to_numpy(dtype=float)  # <0 mean-revert, >0 trend
    body_s = ((df["close"] - df["open"]).abs() / (df["high"] - df["low"]).replace(0.0, np.nan)).to_numpy(dtype=float)
    vol_arr = df["volume"].to_numpy(dtype=float)
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
    chop_b: dict[int, str] = {}
    ac_b: dict[int, str] = {}
    body_b: dict[int, str] = {}
    va_b: dict[int, str] = {}
    volm_b: dict[int, str] = {}
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
        vap = _va_position(highs, lows, t, closes[t])
        if npf is None or vap is None or np.isnan(chop_s[t]) or np.isnan(ac_s[t]):
            skipped += 1
            continue
        pair_r[key] = pr
        is_mask[key] = pd.Timestamp(entry_time) < pd.Timestamp(split_ts)
        vol_b[key] = _quartile(_trailing_rank(atr_s, t))
        width_b[key] = _quartile(_trailing_rank(width, t))
        pos_b[key] = _bb_pos_bucket(bb_pos[t])
        peak_b[key] = _peak_bucket(npf)
        candle_b[key] = _quartile(_trailing_rank(crange, t))
        chop_b[key] = _quartile(_trailing_rank(chop_s, t))
        ac_b[key] = _ac_bucket(ac_s[t])
        body_b[key] = _body_bucket(body_s[t]) if not np.isnan(body_s[t]) else "doji(<.25)"
        va_b[key] = _va_pos_bucket(vap)
        volm_b[key] = _quartile(_trailing_rank(vol_arr, t))
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
    # --- batch 2 ---
    _report("CHOPPINESS (high=sideways) pct", q, chop_b, is_mask, pair_r)
    _report(
        "RETURN AUTOCORR (lag-1)",
        ["mean-revert(<-.05)", "none(-.05..+.05)", "trend(>+.05)"],
        ac_b, is_mask, pair_r,
    )
    _report(
        "CANDLE BODY (indecision)",
        ["doji(<.25)", ".25-.5", ".5-.75", "marubozu(>.75)"],
        body_b, is_mask, pair_r,
    )
    _report(
        "VALUE-AREA POSITION",
        ["below-VA", "VA-lower", "VA-mid", "VA-upper", "above-VA"],
        va_b, is_mask, pair_r,
    )
    _report("VOLUME pct", q, volm_b, is_mask, pair_r)

    # --- independence: do the survivors still bite AFTER the ATR-Q4 cut? ---
    kept = {k for k in pair_r if vol_b[k] != "Q4(high)"}
    logger.info("  ############ CONDITIONAL on ATR not-Q4 (the shipped cut) ############")
    logger.info("  kept {}/{} entries after dropping ATR-Q4", len(kept), len(pair_r))
    sub_chop = {k: chop_b[k] for k in kept}
    sub_ac = {k: ac_b[k] for k in kept}
    sub_mask = {k: is_mask[k] for k in kept}
    sub_r = {k: pair_r[k] for k in kept}
    _report("  CHOPPINESS | ATR not-Q4", q, sub_chop, sub_mask, sub_r)
    _report(
        "  AUTOCORR | ATR not-Q4",
        ["mean-revert(<-.05)", "none(-.05..+.05)", "trend(>+.05)"],
        sub_ac, sub_mask, sub_r,
    )


def _peak_bucket(frac: float) -> str:
    if frac < 0.005:
        return "near(<.5%)"
    if frac < 0.01:
        return "<1%"
    if frac < 0.02:
        return "<2%"
    return "far(>2%)"


def _ac_bucket(ac: float) -> str:
    if ac < -0.05:
        return "mean-revert(<-.05)"
    if ac <= 0.05:
        return "none(-.05..+.05)"
    return "trend(>+.05)"


def _body_bucket(body: float) -> str:
    if body < 0.25:
        return "doji(<.25)"
    if body < 0.50:
        return ".25-.5"
    if body < 0.75:
        return ".5-.75"
    return "marubozu(>.75)"


def _va_pos_bucket(pos: float) -> str:
    if pos < 0.0:
        return "below-VA"
    if pos < 0.33:
        return "VA-lower"
    if pos < 0.67:
        return "VA-mid"
    if pos <= 1.0:
        return "VA-upper"
    return "above-VA"


def _va_position(highs: list[float], lows: list[float], t: int, close: float) -> float | None:
    """Where the entry close sits within the trailing value-area box (0=lo, 1=hi)."""
    if t - VA_WIN < 0:
        return None
    centers, weights = time_at_price_profile(highs[t - VA_WIN : t], lows[t - VA_WIN : t], VA_BINS)
    _poc, lo, hi = value_area(centers, weights)
    if hi <= lo:
        return None
    return (close - lo) / (hi - lo)


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
