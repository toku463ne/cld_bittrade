"""Probe: confirmed-bounce STOP entry at zigzag levels (1h, DR/EV, faithful fills).

The user's mechanic (distinct from fade-at-touch and breakout-through): price
reaches a prior level, you arm a stop just *beyond* it, and you enter ONLY if price
reverses back through the trigger within a validity window — entering the
*confirmed* bounce and skipping the cases where the level just breaks.

- support touch (low reaches wall from above) -> arm BUY-stop at wall·(1+trig);
  fill long if high crosses it within M bars; else skip (breakdown filtered out).
- resistance touch (high reaches wall from below) -> arm SELL-stop at wall·(1−trig);
  fill short if low crosses it within M bars; else skip.

A stop is a TAKER order with a deterministic fill when price crosses the trigger —
so this is faithfully backtestable from OHLC (no limit-queue / adverse-selection
problem), modulo a little slippage beyond the trigger in fast bars.

Reports, per (trig, M, K): bounce-confirmation rate (fills/touches), and the
confirmed entry's DR / mean_r over the next K bars from the trigger. Baseline =
the PLAIN FADE DR over the *same* touches (enter at close[t], no confirmation) — so
we see directly whether the confirmation filter lifts the edge. Material only if
confirmed DR ≥ ~0.56 at n ≥ 100 and clearly above the fade baseline.
Run: uv run --env-file .env.bt python -m src.backtest.analysis.confirmed_bounce_stop_probe
"""

from __future__ import annotations

import bisect
import os

import numpy as np

from src.core.types import Timeframe
from src.data.cache import load_cache
from src.backtest.analysis.trendline_fan_probe import CPeak, confirmed_peaks

SIZE = 10
WIN = 120
TOL = 0.005
_TF = {"1m": Timeframe.M1, "5m": Timeframe.M5, "15m": Timeframe.M15, "1h": Timeframe.H1}


def main() -> None:
    tf = _TF[os.getenv("LEVEL_TF", "1h")]
    d = load_cache(tf, product="GMO_BTC_JPY").to_frame()
    highs, lows = d["high"].tolist(), d["low"].tolist()
    opens = d["open"].to_numpy(dtype=float)
    closes = d["close"].to_numpy(dtype=float)
    n = len(closes)
    cp = confirmed_peaks(highs, lows, size=SIZE)
    hi = [p for p in cp if p.is_high]
    lo = [p for p in cp if not p.is_high]
    hi_idx, lo_idx = [p.idx for p in hi], [p.idx for p in lo]

    def walls(idxs: list[int], peaks: list[CPeak], t: int) -> list[CPeak]:
        return peaks[bisect.bisect_left(idxs, t - WIN) : bisect.bisect_right(idxs, t - SIZE)]

    # Detect fresh touches once (tol fixed). touch = (side_of_bounce, wall_price, t).
    touches: list[tuple[int, float, int]] = []
    for t in range(SIZE + 1, n - 1):
        cl = walls(lo_idx, lo, t)
        if cl:
            w = min(cl, key=lambda p: abs(p.price - lows[t])).price
            if abs(lows[t] - w) <= TOL * w and lows[t - 1] > w + TOL * w:
                touches.append((1, w, t))      # support touch -> long bounce
        ch = walls(hi_idx, hi, t)
        if ch:
            w = min(ch, key=lambda p: abs(p.price - highs[t])).price
            if abs(highs[t] - w) <= TOL * w and highs[t - 1] < w - TOL * w:
                touches.append((-1, w, t))     # resistance touch -> short bounce

    print(f"GMO {tf.value}: {n} bars  peaks={len(cp)}  fresh touches={len(touches)} "
          f"(tol={TOL*100:.1f}%, win={WIN})\n")

    print(f"{'trig':>5} {'M':>3} {'K':>3} {'fills':>6} {'conf%':>6} {'DR':>6} {'mean_r':>8} "
          f"{'fadeDR':>7} {'fade_r':>8}")
    print("-" * 64)
    for trig in (0.005, 0.01, 0.02, 0.03):
        for M in (24,):
            for K in (12, 24):
                conf_r: list[float] = []
                fade_r: list[float] = []
                for side, w, t in touches:
                    if t + 1 + K >= n:
                        continue
                    fade_r.append(side * (closes[t + K] - closes[t]) / closes[t])
                    trigger = w * (1 + trig) if side == 1 else w * (1 - trig)
                    hit, fill = -1, 0.0
                    for s in range(t + 1, min(n - K, t + 1 + M)):
                        if side == 1 and highs[s] >= trigger:
                            # buy-stop: fill at trigger if crossed intrabar, else the
                            # (higher) open if price gapped above it. NOT the stop price.
                            fill = trigger if opens[s] <= trigger else opens[s]
                            hit = s
                            break
                        if side == -1 and lows[s] <= trigger:
                            fill = trigger if opens[s] >= trigger else opens[s]
                            hit = s
                            break
                    if hit >= 0:
                        conf_r.append(side * (closes[hit + K] - fill) / fill)
                if not conf_r:
                    continue
                c = np.array(conf_r)
                f = np.array(fade_r)
                print(f"{trig*100:>4.1f}% {M:>3} {K:>3} {c.size:>6} "
                      f"{c.size/len(fade_r)*100:>5.0f}% {float((c>0).mean()):>6.3f} "
                      f"{c.mean()*100:>7.3f}% {float((f>0).mean()):>7.3f} {f.mean()*100:>7.3f}%")
    print("\nconf% = fills/touches (how often a touched level bounces through the trigger). "
          "Material only if DR ≥ ~0.56 at n ≥ 100 AND above fadeDR.")


if __name__ == "__main__":
    main()
