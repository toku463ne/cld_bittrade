"""Probe: is there a DAILY trend/momentum edge, and does bitFlyer SWAP kill it?

Motivation: intraday BTC/JPY mean-reverts — every directional intraday signal was
gross-zero (see docs/findings.md). Higher-timeframe momentum is a different, far
better-evidenced phenomenon (CTA/managed-futures trend-following lives at the
daily–weekly horizon). The user asked whether daily bars "clear the spread issue".
Answer this empirically:

- On daily bars the bid/ask SPREAD is negligible vs a 2-4% daily move.
- BUT a daily strategy HOLDS for days, so it pays the bitFlyer FX/CFD **SWAP point**
  (~0.04%/day = 4 bp/day, charged to open positions at the daily clearing — flat,
  not directional). So daily doesn't remove cost; it relocates spread -> carry.
  A position held N days pays ~4·N bp; always-in-market pays ~14.6%/yr.

So the real questions are (1) is there a GROSS daily trend edge at all, and (2) does
the ~4 bp/day swap carry kill it. We report both columns.

Two classic signals, deep GMO_BTC_JPY 1h aggregated to daily:
- **Donchian breakout** (Turtle): enter on an N-day high/low breakout, exit on the
  opposite (N/2)-day channel. Discrete, multi-day holds; swap = 4 bp × days_held.
- **Time-series momentum** (TSMOM): hold long/short by the sign of the trailing
  L-day return, rebalanced daily; always in market, so swap every day.

Benchmark: buy-and-hold over the same window (per CLAUDE.md, not cash). SWAP_BP is
an estimate — verify the current CFD swap before trusting the net column.
Run: uv run --env-file .env.bt python -m src.backtest.analysis.daily_momentum_probe
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.core.types import Timeframe
from src.data.cache import load_cache

SWAP_BP_PER_DAY = 4.0   # ~0.04%/day bitFlyer FX/CFD swap (estimate)
SPREAD_BP_RT = 1.0      # round-trip spread/slippage on daily (negligible)


def to_daily(product: str = "GMO_BTC_JPY") -> pd.DataFrame:
    """Aggregate the deep 1h series to daily OHLC (calendar day in the stored tz)."""
    h = load_cache(Timeframe.H1, product=product).to_frame()
    d = h.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    return d.dropna()


def _sharpe(x: np.ndarray) -> float:
    s = float(x.std(ddof=1)) if x.size > 1 else 0.0
    return float(x.mean() / s) if s > 0 else 0.0


def donchian(o: np.ndarray, h: np.ndarray, low: np.ndarray, c: np.ndarray, n: int, m: int
             ) -> list[tuple[int, float, int]]:
    """Turtle breakout: enter N-day channel break, exit opposite M-day channel.

    Returns per-trade (side, gross_return, days_held). Causal: the channel at bar t
    uses bars [t-N, t-1]; fills at the next day's open (two-bar rule).
    """
    N = len(c)
    out: list[tuple[int, float, int]] = []
    side = 0
    entry = 0.0
    entry_i = 0
    for t in range(n, N - 1):
        if side == 0:
            hh, ll = float(h[t - n:t].max()), float(low[t - n:t].min())
            if c[t] > hh:
                side, entry, entry_i = 1, o[t + 1], t + 1
            elif c[t] < ll:
                side, entry, entry_i = -1, o[t + 1], t + 1
        else:
            ex_hh, ex_ll = float(h[t - m:t].max()), float(low[t - m:t].min())
            if (side == 1 and c[t] < ex_ll) or (side == -1 and c[t] > ex_hh):
                ex = o[t + 1]
                out.append((side, side * (ex - entry) / entry, t + 1 - entry_i))
                side = 0
    if side != 0:  # close at last close
        out.append((side, side * (c[-1] - entry) / entry, N - 1 - entry_i))
    return out


def main() -> None:
    d = to_daily()
    o, h, low, c = (d[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    bh = (c[-1] - c[0]) / c[0]
    yrs = (d.index[-1] - d.index[0]).days / 365.25
    print(f"GMO daily: {len(d)} bars  {d.index[0]:%Y-%m-%d} -> {d.index[-1]:%Y-%m-%d}  "
          f"({yrs:.1f}y)  buy&hold gross = {bh*100:+.1f}%\n")

    print("DONCHIAN breakout (Turtle) — per-trade returns")
    print(f"{'N/M':>7} {'n':>4} {'hold_d':>7} {'gross_Σ':>9} {'gross_Sh':>9} "
          f"{'net_Σ':>9} {'net_Sh':>8} {'win':>5} {'long%':>6}")
    print("-" * 74)
    for n_, m_ in ((20, 10), (55, 20)):
        trades = donchian(o, h, low, c, n_, m_)
        if not trades:
            continue
        gross = np.array([g for _, g, _ in trades])
        days = np.array([dd for _, _, dd in trades])
        net = gross - (SWAP_BP_PER_DAY * days + SPREAD_BP_RT) / 1e4
        longp = float(np.mean([s == 1 for s, _, _ in trades]))
        print(f"{n_:>3}/{m_:<3} {len(trades):>4} {days.mean():>7.1f} "
              f"{gross.sum()*100:>8.1f}% {_sharpe(gross):>9.3f} "
              f"{net.sum()*100:>8.1f}% {_sharpe(net):>8.3f} {(gross>0).mean():>5.2f} {longp:>6.2f}")

    print("\nTIME-SERIES MOMENTUM (always in market) — daily returns, Sharpe annualised")
    print(f"{'lookback':>8} {'gross_Σ':>9} {'gross_Sh':>9} {'net_Σ':>9} {'net_Sh':>8} {'long%':>6}")
    print("-" * 56)
    dr = np.diff(c) / c[:-1]  # next-day return aligned to position at t
    for L in (30, 60, 120):
        pos = np.sign(c[L:-1] / c[: -1 - L] - 1.0)   # sign of trailing L-day return at t
        r = pos * dr[L:]                              # position at t earns t->t+1 return
        net = r - SWAP_BP_PER_DAY / 1e4              # swap every day (always in market)
        ann = np.sqrt(365.0)
        print(f"{L:>8} {r.sum()*100:>8.1f}% {_sharpe(r)*ann:>9.3f} "
              f"{net.sum()*100:>8.1f}% {_sharpe(net)*ann:>8.3f} {(pos>0).mean():>6.2f}")

    print(f"\nSWAP modelled at {SWAP_BP_PER_DAY:.0f} bp/day (estimate). gross = no cost; "
          "net = with swap (+1bp spread for Donchian). Compare net_Sh to buy&hold.")


if __name__ == "__main__":
    main()
