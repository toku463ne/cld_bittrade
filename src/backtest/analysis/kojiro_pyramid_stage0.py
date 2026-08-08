"""Stage-0 probe: Kojiro PYRAMIDING (増し玉, add-to-winners) on the daily 5/20/40
MA-stage cell — the book's best/native habitat — to close the one gap left by
kojiro_ma_stage_stage0.py (which tested entry+exit but not the book's claimed
P&L driver).

WHY (sign-debate 2026-06-28, 3rd probe, after the bias check):
  The MA-stage probe found the daily 5/20/40 cell is the book's best honest cell
  (mean_r +0.013, per-trade Sharpe +0.11) but it still fails B&H and its own null.
  The book's thesis, though, is that the ENTRY only locates the edge; the year's P&L
  is made by money management — above all PYRAMIDING into the few big trends. That
  was formally untested here. This probe tests whether adding to winners turns the
  daily cell into something that beats B&H.

BOOK PYRAMIDING RULES (Part 1, p.25-27/p.51-52/p.65-67/p.94 — faithful):
  - 1 Unit sized so a 1N (=1 ATR) adverse move = 1% of capital (p.17-21). So one
    unit's capital return over a price move dP = 1% * (dP / N). Sharpe is
    scale-invariant in the 1% so the stream is carried in "1%-units" (f=1).
  - After the 1-unit entry, ADD 1 unit each time price advances a fixed ATR
    increment in your favour, up to a 4-unit cap (max 3 adds):
       * 0.5N spacing (base):     add every 0.5 ATR  (max risk 5N at 4 units)
       * 1.0N spacing (low-risk): add every 1.0 ATR  (max risk 2N at 4 units)
  - On EACH add, move the single aggregate stop to 2N below the LATEST fill and
    apply it to ALL units (p.120). Adds fill via stop-order at last_fill+spacing.
  - Never add to a loser; the stop only ratchets up. Exit ALL units on the native
    stage-flip (leave Stage 1 / Stage 4) OR the aggregate 2N stop.
  N is the daily ATR at the ORIGINAL entry (risk anchored per trade).

COMPARISON: baseline = same entry/exit, 1 unit, ATR-normalised (no pyramiding) vs
  pyr-0.5N vs pyr-1.0N — all on the SAME fires, vs Buy-and-hold BTC/JPY equity Sharpe.
READ: pyramiding helps ONLY if some arm's annualised equity Sharpe >= B&H over the
  same IS window (the repo gate (a)). It amplifies exposure on winners; it cannot
  manufacture directional selection, so the prior is that it raises BOTH return and
  variance and leaves Sharpe ~flat or worse.
OOS HYGIENE: in-sample only; lockbox never touched. Read-only; no DB / production code.
Run: uv run --env-file .env.bt python -m src.backtest.analysis.kojiro_pyramid_stage0
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from src.backtest.sign_benchmark import split_lockbox
from src.core.types import Timeframe
from src.data.cache import load_cache

ATR_PERIOD = 14
STOP_N = 2.0               # aggregate stop = 2N below the latest fill (book core)
MAX_UNITS = 4             # 1 base + 3 adds
FEE_RATE = float(os.getenv("FEE", "0.0002"))
S, M, L = 5, 20, 40       # the book's canonical daily set
BPY = 365


def _resample(df, rule):
    o = df.resample(rule).agg(open=("open", "first"), high=("high", "max"),
                              low=("low", "min"), close=("close", "last"))
    return o.dropna()


def _atr(high, low, close, period):
    h, l, c = np.asarray(high), np.asarray(low), np.asarray(close)
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    out = np.full_like(tr, np.nan)
    if len(tr) >= period:
        out[period - 1] = tr[:period].mean()
        for i in range(period, len(tr)):
            out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def _stage(s, m, l):
    n = len(s)
    st = np.zeros(n, dtype=int)
    for i in range(n):
        if not (np.isnan(s[i]) or np.isnan(m[i]) or np.isnan(l[i])):
            if s[i] > m[i] > l[i]:
                st[i] = 1
            elif l[i] > m[i] > s[i]:
                st[i] = 4
    return st


def walk(opens, highs, lows, closes, atrs, s, m, st, add_spacing):
    """Single-position both-sided MA-stage walk with pyramiding.

    ``add_spacing`` in ATR units (0 = baseline, no adds). Returns
    (bar_net, n_trades, win_trades, units_per_trade). bar_net is the per-bar capital
    return in 1%-units (1 unit * 1N move = 1.0). Stop/adds anchored to actual fills.
    """
    n = len(opens)
    bar_net = np.zeros(n, dtype=float)
    n_trades = win_trades = 0
    units_log: list[int] = []
    pos = 0                     # +1 long, -1 short, 0 flat
    N0 = 0.0
    units: list[float] = []     # fill prices of open units
    last_fill = 0.0
    agg_stop = 0.0
    trade_pnl = 0.0             # running 1%-unit pnl of the open trade (for win/loss)
    prev_close = 0.0
    t = 1
    while t < n - 1:
        if pos == 0:
            rising = s[t] > s[t - 1] and m[t] > m[t - 1]
            falling = s[t] < s[t - 1] and m[t] < m[t - 1]
            go_long = st[t] == 1 and rising
            go_short = st[t] == 4 and falling
            if (go_long or go_short) and atrs[t] > 0:
                pos = 1 if go_long else -1
                N0 = atrs[t]
                fill = opens[t + 1]
                units = [fill]
                last_fill = fill
                agg_stop = fill - STOP_N * N0 if pos == 1 else fill + STOP_N * N0
                # entry bar t+1: 1 unit marked open->close, entry fee.
                r = pos * (closes[t + 1] - fill) / N0 - FEE_RATE * fill / N0
                bar_net[t + 1] = r
                trade_pnl = r
                prev_close = closes[t + 1]
                n_trades += 1
                t += 2
                continue
            t += 1
            continue

        long = pos == 1
        # 1. aggregate stop (pessimistic, pre-bar level), exits ALL units.
        if (long and lows[t] <= agg_stop) or (not long and highs[t] >= agg_stop):
            k = len(units)
            r = k * pos * (agg_stop - prev_close) / N0 - k * FEE_RATE * agg_stop / N0
            bar_net[t] = r
            trade_pnl += r
            win_trades += 1 if trade_pnl > 0 else 0
            units_log.append(k)
            pos = 0
            t += 1
            continue

        bar_r = len(units) * pos * (closes[t] - prev_close) / N0    # hold mark-to-mkt

        # 2. pyramiding adds (stop-order fills at last_fill +/- spacing).
        if add_spacing > 0:
            while len(units) < MAX_UNITS:
                trigger = last_fill + add_spacing * N0 if long else last_fill - add_spacing * N0
                hit = (long and highs[t] >= trigger) or (not long and lows[t] <= trigger)
                if not hit:
                    break
                units.append(trigger)
                last_fill = trigger
                agg_stop = trigger - STOP_N * N0 if long else trigger + STOP_N * N0
                # new unit: marked trigger->close on this bar, + entry fee.
                bar_r += pos * (closes[t] - trigger) / N0 - FEE_RATE * trigger / N0

        # 3. native stage-flip exit -> all units out at next open.
        left = (long and not (s[t] > m[t])) or (not long and not (s[t] < m[t]))
        if left:
            ex = opens[t + 1]
            k = len(units)
            bar_net[t] = bar_r
            r2 = k * pos * (ex - closes[t]) / N0 - k * FEE_RATE * ex / N0
            bar_net[t + 1] = r2
            trade_pnl += bar_r + r2
            win_trades += 1 if trade_pnl > 0 else 0
            units_log.append(k)
            pos = 0
            t += 2
            continue

        bar_net[t] = bar_r
        trade_pnl += bar_r
        prev_close = closes[t]
        t += 1
    return bar_net, n_trades, win_trades, units_log


def _sharpe_ann(stream, bpy):
    a = np.asarray(stream)
    std = a.std(ddof=1)
    return float(a.mean() / std * np.sqrt(bpy)) if std > 0 else 0.0


def main() -> None:
    product = os.getenv("KJ_PRODUCT", "GMO_BTC_JPY")
    cache = load_cache(Timeframe.H1, product=product)
    is_b, _ = split_lockbox(cache.bars)
    boundary = is_b[-1].timestamp
    df = _resample(cache.to_frame(), "1D").loc[:boundary]
    opens = df["open"].to_numpy(); highs = df["high"].to_numpy()
    lows = df["low"].to_numpy(); closes = df["close"].to_numpy()
    atrs = _atr(highs, lows, closes, ATR_PERIOD)
    s = pd.Series(closes).rolling(S).mean().to_numpy()
    m = pd.Series(closes).rolling(M).mean().to_numpy()
    l = pd.Series(closes).rolling(L).mean().to_numpy()
    st = _stage(s, m, l)

    bh = (closes[1:] - closes[:-1]) / closes[:-1]
    bh_sh = float(bh.mean() / bh.std(ddof=1) * np.sqrt(BPY)) if bh.std(ddof=1) > 0 else 0.0
    yrs = len(df) / BPY

    print(f"{product} DAILY 5/20/40 MA-stage, pyramiding (max {MAX_UNITS} units, 2N agg-stop), IN-SAMPLE")
    print(f"{len(df)} days ({yrs:.1f}y)  {df.index[0].date()} -> {df.index[-1].date()}   "
          f"B&H eqSharpe={bh_sh:+.3f}\n")
    print(f"{'arm':>14} {'trades':>7} {'avgUnits':>9} {'win%':>6} {'totRet%':>9} "
          f"{'annRet%':>9} {'eqSharpe':>9} {'maxDD%':>8} {'mean_r%':>8} {'beatBH':>7}")
    print("-" * 96)
    for name, spc in [("baseline(1u)", 0.0), ("pyr-0.5N", 0.5), ("pyr-1.0N", 1.0)]:
        bar_net, nt, wt, ulog = walk(opens, highs, lows, closes, atrs, s, m, st, spc)
        sh = _sharpe_ann(bar_net, BPY)
        tot = bar_net.sum()                    # in 1%-units
        tot_pct = tot * 1.0                     # 1 unit-bar == 1% capital
        ann_pct = tot_pct / yrs
        eq = np.cumsum(bar_net)                 # equity curve in 1%-units
        dd = float((np.maximum.accumulate(eq) - eq).max())  # max drawdown, 1%-units
        mean_r = tot / nt if nt else 0.0       # mean per-trade capital return, 1%-units
        avg_u = float(np.mean(ulog)) if ulog else 1.0
        winr = wt / nt if nt else 0.0
        beat = "YES" if sh >= bh_sh else "no"
        print(f"{name:>14} {nt:>7} {avg_u:>9.2f} {winr:>6.2f} {tot_pct:>9.1f} "
              f"{ann_pct:>9.1f} {sh:>9.3f} {dd:>8.1f} {mean_r:>8.2f} {beat:>7}")

    # Per-calendar-year robustness (is it one regime, e.g. the 2021 bull?).
    print("\nper-year capital return %  (1% risk/unit):  strat = pyr-1.0N")
    bar_net, *_ = walk(opens, highs, lows, closes, atrs, s, m, st, 1.0)
    base_net, *_ = walk(opens, highs, lows, closes, atrs, s, m, st, 0.0)
    years = pd.Series(df.index).dt.year.to_numpy()
    bh_bar = np.zeros(len(closes)); bh_bar[1:] = bh
    print(f"{'year':>6} {'base%':>8} {'pyr1N%':>8} {'B&H%':>8}")
    for y in sorted(set(years.tolist())):
        msk = years == y
        print(f"{y:>6} {base_net[msk].sum():>8.1f} {bar_net[msk].sum():>8.1f} "
              f"{bh_bar[msk].sum() * 100:>8.1f}")

    print("\nGATE: an arm's eqSharpe >= B&H (beatBH=YES) -> pyramiding gives the daily cell an edge.")
    print("Note: annRet% assumes 1% risk per unit (book sizing); n is thin on daily IS (SE~1/sqrt(n)).")
    print("OOS reserved: lockbox untouched.")


if __name__ == "__main__":
    main()
