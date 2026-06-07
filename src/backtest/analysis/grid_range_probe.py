"""Stage-1 economics probe for Strategy B — Dynamic Range-Detected Grid.

Tests the grid's core economics *before* building the strategy: within density tight-box
range episodes, simulate a symmetric capped grid (buy levels below mid / sell levels
above, each closing at the adjacent line) and flatten on breakout. Reports per-episode
**net** P&L (captures + breakout flatten), NET of cost = 0.04%/day funding/position +
10 bp round-trip/fill spread — split early/late — plus the **breakout-loss tail**.

Pre-registered pass (study_plan §B-kill-1): net P&L/episode > 0 in BOTH halves AND ≥50%
of episodes net-profitable. B-kill-2 (tail): worst episode loss ≤ ~3× median winner; net
positive across 2022 (crash) and 2024 (bull). Short-gamma payoffs flatter the Sharpe
gate, so this looks at the distribution, not an average.

Usage::

    uv run --env-file .env.bt python -m src.backtest.analysis.grid_range_probe --timeframe 1h
"""

from __future__ import annotations

import argparse

import numpy as np
from loguru import logger

from src.core.types import Timeframe
from src.data.cache import load_cache
from src.logging_setup import configure_logging
from src.strategy.density_multi_breakout import _rolling_bands

WINDOW, N_BINS, COVERAGE, MAX_BAND_PCT = 168, 48, 0.70, 0.03
FUNDING_PER_DAY = 0.0004
SPREAD_RT = 0.0010  # 10 bp round-trip per grid fill
BREAKOUT_BUF = 0.10  # × band height
MAX_EP = 240  # episode cap (bars)
# B' hold-prone detector (Choppiness Index): high = sideways/ranging.
CHOP_N = 14
RANGE_LB = 48  # rolling window for the grid bounds (recent oscillation range)
CHOP_THRESH = 61.8  # Fibonacci "sideways" level


def _chop(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, n: int) -> np.ndarray:
    """Choppiness Index: 100·log10(ΣTR_n / range_n) / log10(n). High = ranging."""
    import pandas as pd

    h, low, c = pd.Series(highs), pd.Series(lows), pd.Series(closes)
    prev = c.shift(1)
    tr = pd.concat([h - low, (h - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    rng = (h.rolling(n).max() - low.rolling(n).min()).replace(0.0, np.nan)
    ci = (100.0 * np.log10(tr.rolling(n).sum() / rng) / np.log10(n)).to_numpy()
    return np.asarray(ci, dtype=float)


def _episode(
    highs: list[float], lows: list[float], closes: np.ndarray,
    s: int, lo: float, hi: float, n: int,
) -> tuple[float, int, int]:
    """Simulate one grid episode from bar ``s``; return (net_frac, n_fills, end_idx)."""
    spacing = (hi - lo) / (n + 1)
    mid = 0.5 * (lo + hi)
    buf = BREAKOUT_BUF * (hi - lo)
    levels = [lo + (k + 1) * spacing for k in range(n)]
    open_pos: dict[int, tuple[int, float, float, int]] = {}  # idx -> side, entry, target, entry_bar
    realized: list[float] = []
    fills = 0
    j = s + 1
    end = j
    while j < len(closes):
        end = j
        c = closes[j]
        if c > hi + buf or c < lo - buf or (j - s) >= MAX_EP:  # breakout / cap -> flatten
            for _idx, (side, entry, _t, eb) in open_pos.items():
                raw = side * (c - entry) / entry
                realized.append(raw - (SPREAD_RT + FUNDING_PER_DAY * (j - eb) / 24))
            open_pos = {}
            break
        for idx in list(open_pos):  # exits at the adjacent grid line (capture)
            side, entry, tgt, eb = open_pos[idx]
            if (side == 1 and highs[j] >= tgt) or (side == -1 and lows[j] <= tgt):
                realized.append(spacing / entry - (SPREAD_RT + FUNDING_PER_DAY * (j - eb) / 24))
                del open_pos[idx]
        for idx, lv in enumerate(levels):  # entries (re-armed once closed)
            if idx in open_pos or len(open_pos) >= n:
                continue
            side = 1 if lv < mid else -1
            if (side == 1 and lows[j] <= lv) or (side == -1 and highs[j] >= lv):
                open_pos[idx] = (side, lv, lv + spacing if side == 1 else lv - spacing, j)
                fills += 1
        j += 1
    if open_pos:  # data end -> flatten at last close
        c = closes[end]
        for _idx, (side, entry, _t, eb) in open_pos.items():
            realized.append(side * (c - entry) / entry - (SPREAD_RT + FUNDING_PER_DAY * (end - eb) / 24))
    return float(sum(realized)), fills, end


def run(tf: Timeframe, *, n: int = 6, detector: str = "density", chop_thresh: float = CHOP_THRESH) -> None:
    """Detect range episodes (density box or hold-prone chop), grid-sim each, report economics."""
    bars = load_cache(tf, product="GMO_BTC_JPY").bars
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = np.array([b.close for b in bars], dtype=float)
    nbars = len(bars)
    split_idx = nbars // 2
    h_arr, l_arr = np.array(highs, dtype=float), np.array(lows, dtype=float)
    bl, bh = _rolling_bands(highs, lows, WINDOW, N_BINS, COVERAGE) if detector == "density" else (None, None)
    ci = _chop(h_arr, l_arr, closes, CHOP_N) if detector == "chop" else None
    start_i = WINDOW

    episodes: list[tuple[int, float, int]] = []  # start_idx, net_frac, n_fills
    i = start_i
    while i < nbars:
        if detector == "density":
            lo, hi = float(bl[i]), float(bh[i])  # type: ignore[index]
            if not (hi > lo) or (hi - lo) > MAX_BAND_PCT * closes[i] or not (lo <= closes[i] <= hi):
                i += 1
                continue
        else:  # chop: hold-prone regime; bounds = recent oscillation range
            if i < RANGE_LB or np.isnan(ci[i]) or ci[i] < chop_thresh:  # type: ignore[index]
                i += 1
                continue
            lo, hi = float(l_arr[i - RANGE_LB : i].min()), float(h_arr[i - RANGE_LB : i].max())
            bw = (hi - lo) / closes[i]
            if not (0.005 <= bw <= 0.06) or not (lo <= closes[i] <= hi):
                i += 1
                continue
        net, fills, end = _episode(highs, lows, closes, i, lo, hi, n)
        episodes.append((i, net, fills))
        i = end + 1

    if not episodes:
        logger.warning("no range episodes detected")
        return
    nets = np.array([e[1] for e in episodes])
    early = np.array([e[1] for e in episodes if e[0] < split_idx])
    late = np.array([e[1] for e in episodes if e[0] >= split_idx])
    wins = nets[nets > 0]
    logger.info("Grid range probe [detector={}{}] (n={} levels), BTC {} — {} episodes",
                detector, f" chop>={chop_thresh}" if detector == "chop" else "", n, tf.value, len(episodes))
    logger.info("  net/episode: mean {:+.5f} | total {:+.3f} | %profitable {:.0%} | avg fills {:.1f}",
                nets.mean(), nets.sum(), float((nets > 0).mean()), np.mean([e[2] for e in episodes]))
    logger.info("  (B-kill-1) early mean {:+.5f} ({} ep) | late mean {:+.5f} ({} ep) -> {}",
                early.mean() if early.size else float("nan"), early.size,
                late.mean() if late.size else float("nan"), late.size,
                "PASS" if (early.size and late.size and early.mean() > 0 and late.mean() > 0
                           and (nets > 0).mean() >= 0.5) else "FAIL")
    worst = nets.min()
    medwin = float(np.median(wins)) if wins.size else float("nan")
    logger.info("  (B-kill-2 tail) worst episode {:+.5f} | median winner {:+.5f} | ratio {:.1f}x [pass <=3x]",
                worst, medwin, abs(worst) / medwin if medwin else float("inf"))
    # sub-year net (crash 2022 / bull 2024)
    for yr in (2022, 2024):
        m = [e[1] for e in episodes if bars[e[0]].timestamp.year == yr]
        if m:
            logger.info("  {} sub-period: {} episodes, net {:+.4f}", yr, len(m), sum(m))


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Stage-1 grid range-fade economics probe.")
    parser.add_argument("--timeframe", choices=[tf.value for tf in Timeframe], default="1h")
    parser.add_argument("--levels", type=int, default=6)
    parser.add_argument("--detector", choices=["density", "chop"], default="density")
    parser.add_argument("--chop-thresh", type=float, default=CHOP_THRESH)
    args = parser.parse_args()
    configure_logging()
    run(Timeframe(args.timeframe), n=args.levels, detector=args.detector, chop_thresh=args.chop_thresh)


if __name__ == "__main__":
    main()
