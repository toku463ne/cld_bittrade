"""Probe: at a prior zigzag level, does price FADE or BREAK OUT? (1h, DR/EV only)

Settles whether a STOP (breakout/continuation) entry on zigzag_bounce levels has an
edge on 1h, vs the FADE (bounce) entry. Two distinct, causal event sets at a recent
confirmed same-type wall (known only from its idx+size bar):

- **FADE**: the bar's high/low *touches* the wall within ``tol`` on a fresh approach
  -> reversion trade (short at resistance / long at support).
- **BREAKOUT (stop)**: the *close* crosses through the wall by ``tol`` for the first
  time -> continuation trade (long through resistance / short through support). This
  is what a stop-entry actually captures.

Outcome = signed return over the next ``K`` bars, ``side·(close[t+K]−close[t])/
close[t]``. DR = fraction > 0; mean_r = EV/event; compared to the unconditional
K-bar drift. MATERIAL only if DR ≥ ~0.56 at n ≥ 100, clearly above base. Signal
only — does NOT model fills (a real stop fills slightly *beyond* the level, so the
breakout's realised EV is a touch worse than shown). Env: LEVEL_TF (default 1h).
Run: uv run --env-file .env.bt python -m src.backtest.analysis.level_reaction_probe
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
_TF = {"1m": Timeframe.M1, "5m": Timeframe.M5, "15m": Timeframe.M15, "1h": Timeframe.H1}


def main() -> None:
    tf = _TF[os.getenv("LEVEL_TF", "1h")]
    d = load_cache(tf, product="GMO_BTC_JPY").to_frame()
    highs, lows = d["high"].tolist(), d["low"].tolist()
    closes = d["close"].to_numpy(dtype=float)
    n = len(closes)
    cp = confirmed_peaks(highs, lows, size=SIZE)
    hi = [p for p in cp if p.is_high]
    lo = [p for p in cp if not p.is_high]
    hi_idx = [p.idx for p in hi]
    lo_idx = [p.idx for p in lo]
    print(f"GMO {tf.value}: {n} bars  {d.index[0]:%Y-%m-%d}..{d.index[-1]:%Y-%m-%d}  "
          f"confirmed peaks={len(cp)} (size={SIZE})\n")

    def walls(idxs: list[int], peaks: list[CPeak], t: int) -> list[CPeak]:
        a = bisect.bisect_left(idxs, t - WIN)
        b = bisect.bisect_right(idxs, t - SIZE)  # causal: known_at = idx+SIZE <= t
        return peaks[a:b]

    print(f"{'mode':>8} {'tol':>5} {'K':>3} {'n':>5} {'DR':>6} {'mean_r':>8} {'base':>6}")
    print("-" * 48)
    for tol in (0.003, 0.005, 0.01):
        for K in (6, 12, 24):
            fade: list[float] = []
            brk: list[float] = []
            for t in range(SIZE + 1, n - K):
                ch = walls(hi_idx, hi, t)
                cl = walls(lo_idx, lo, t)
                rr = (closes[t + K] - closes[t]) / closes[t]
                if ch:
                    w = min(ch, key=lambda p: abs(p.price - highs[t])).price
                    band = tol * w
                    if abs(highs[t] - w) <= band and highs[t - 1] < w - band:
                        fade.append(-rr)                 # fade resistance -> short
                    if closes[t] > w + band and closes[t - 1] <= w + band:
                        brk.append(rr)                   # break up -> long
                if cl:
                    w = min(cl, key=lambda p: abs(p.price - lows[t])).price
                    band = tol * w
                    if abs(lows[t] - w) <= band and lows[t - 1] > w + band:
                        fade.append(rr)                  # fade support -> long
                    if closes[t] < w - band and closes[t - 1] >= w - band:
                        brk.append(-rr)                  # break down -> short
            base = 0.5  # coin-flip reference for the level reaction
            for label, rows in (("fade", fade), ("breakout", brk)):
                if not rows:
                    continue
                a = np.array(rows)
                print(f"{label:>8} {tol*100:>4.1f}% {K:>3} {a.size:>5} "
                      f"{float((a>0).mean()):>6.3f} {a.mean()*100:>7.3f}% {base:>6.2f}")
            print()
    print("Material only if DR ≥ ~0.56 at n ≥ 100 AND above base (~0.50). "
          "Breakout EV shown is optimistic (stop fills beyond the level).")


if __name__ == "__main__":
    main()
