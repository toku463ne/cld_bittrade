"""Maker pivot step 2: does reversion beat adverse selection, by quote distance?

Step 1 (maker_spread_probe) showed the touch spread is ~1.3bp with ~0 adverse
selection — but the touch is owned by latency-advantaged HFT. The retail-viable
angle is to quote *wider* (rest limits d bp from mid) where trade-through fills are
queue-robust and the captured spread is larger. This measures whether that works.

Model (faithful to a resting LIMIT — fills at the limit price or better, so no
stop-style gap bug):
- A SELL-aggressor trade at price p hits a resting BID -> maker fills LONG at p.
  A BUY-aggressor trade hits a resting ASK -> maker fills SHORT at p.
- From the fill, resolve a symmetric ±d barrier on subsequent trade prices:
  WIN = price reverts by +d to the maker (back toward/through mid) BEFORE going −d
  adverse; LOSE = −d hit first. Per-fill P&L = +d on win, −d on lose (commission=0,
  so this IS the realised maker P&L). Net = (2·winrate − 1)·d bp/fill.
- Sweep d. WIN RATE > 0.5 means short-horizon reversion beats adverse selection at
  that distance -> a maker edge exists there.

Events are sub-sampled (stride) for speed; the barrier is resolved over the next
``MAXF`` trades (unresolved = neither barrier hit -> excluded, reported as unres%).

CAVEAT: queue priority is NOT modelled. For tight d the trade-through fill is
optimistic (you'd be back-of-queue); for wide d (a spike reaching a lonely quote)
it is far more realistic. Read the WIDE-d rows as the trustworthy ones.
Run: uv run --env-file .env.bt python -m src.backtest.analysis.maker_quote_distance_probe
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.db import get_engine

PRODUCT = "FX_BTC_JPY"
STRIDE = 30      # sub-sample every Nth trade as a candidate fill (~45k events)
MAXF = 4000      # max forward trades to resolve the barrier (~2.4h at 28 trades/min)


def main() -> None:
    df = pd.read_sql(
        f"SELECT price, side FROM execution WHERE product = '{PRODUCT}' "
        f"AND side IS NOT NULL ORDER BY id",
        get_engine(),
    )
    p = df["price"].to_numpy(dtype=float)
    side = df["side"].to_numpy()
    n = len(p)
    print(f"{PRODUCT} tape: {n:,} trades  (stride={STRIDE} -> ~{n//STRIDE:,} events, "
          f"barrier over next {MAXF} trades)\n")

    ev = np.arange(0, n - MAXF - 1, STRIDE)
    is_sell = side[ev] == "SELL"  # SELL-aggr -> maker long; BUY-aggr -> maker short

    print(f"{'d(bp)':>6} {'n':>7} {'unres%':>7} {'win_rate':>9} "
          f"{'net(bp/fill)':>13} {'med_hold':>9}")
    print("-" * 56)
    for d in (1, 2, 5, 10, 20, 30, 50):
        frac = d / 1e4
        wins = 0
        losses = 0
        holds: list[int] = []
        for i, sell in zip(ev, is_sell):
            entry = p[i]
            up, dn = entry * (1 + frac), entry * (1 - frac)
            win_lvl, lose_lvl = (up, dn) if sell else (dn, up)
            w = p[i + 1 : i + 1 + MAXF]
            hit_win = w >= win_lvl if sell else w <= win_lvl
            hit_lose = w <= lose_lvl if sell else w >= lose_lvl
            jw = int(hit_win.argmax()) if hit_win.any() else MAXF + 1
            jl = int(hit_lose.argmax()) if hit_lose.any() else MAXF + 1
            if jw == MAXF + 1 and jl == MAXF + 1:
                continue  # unresolved
            if jw <= jl:
                wins += 1
                holds.append(jw)
            else:
                losses += 1
                holds.append(jl)
        tot = wins + losses
        if not tot:
            continue
        wr = wins / tot
        net = (2 * wr - 1) * d
        unres = 1 - tot / len(ev)
        print(f"{d:>6} {tot:>7} {unres*100:>6.0f}% {wr:>9.3f} {net:>13.2f} "
              f"{int(np.median(holds)):>9}")
    print("\nWIN RATE > 0.5 => reversion beats adverse selection (maker edge) at that d. "
          "Trust the WIDE-d rows (tight-d fills are queue-optimistic). net is gross of "
          "no commission; ignores inventory risk while holding.")


if __name__ == "__main__":
    main()
