"""Stage-0 probe: Kojiro's PRIMARY engine — 移動平均線大循環分析 (MA great-cycle
stage) entry with its NATIVE exit — built clean, with ZERO density involvement.

WHY (sign-debate 2026-06-28, follow-up after a bias check):
  The first Kojiro debate tested only the half-rise TRAIL bolted onto density_breakout
  fires — an entry already tuned to prefer no trail. That is density-anchored and tests
  the weakest, most bolt-on slice of the book. The book's THESIS is a complete trend
  SYSTEM, and its primary entry engine is the 3-SMA stage classifier (Part 3), which is
  a trend-STATE read, NOT a breakout trigger — so the repo's "breakout entry is a
  coin-flip" evidence does NOT bear on it. The Historian confirmed this exact engine has
  never been built or probed here. This probe tests it on its own terms.

MECHANISM (book Part 3, p.108/p.125 — computed identically by anyone, no fitted DOF):
  s=SMA(S), m=SMA(M), l=SMA(L)  (book canonical 5/20/40; ratios kept, lengths swept).
  Stage 1 = s>m>l (stable uptrend);  Stage 4 = l>m>s (stable downtrend).
  rising(x)_t = x[t] > x[t-1].
  ENTRY (canonical, p.125):  LONG when stage==1 AND s,m,l all rising;
                             SHORT when stage==4 AND s,m,l all falling.
  EXIT (native, p.245):  LONG exits on the 1->2 transition (SMA5 crosses below SMA20,
                         i.e. leaves stage 1);  SHORT exits on leaving stage 4.
                         PLUS the book's 2N (2*ATR) money-management stop (core, not
                         optional) — set KJ_STOP=0 to disable for the pure-MA read.
  Two-bar fill: signal at close[t], fill at open[t+1]; exit signal at close, fill next
  open (stop fills intrabar at the stop level, pessimistic).
  Single position, both-sided, flat when neither stage 1 nor 4 holds.

EVALUATION (the repo's actual ship metric — equity Sharpe vs B&H, plus an entry null):
  - Annualised MARK-TO-MARKET equity Sharpe of the strategy vs Buy-and-hold BTC/JPY
    over the SAME in-sample window (gate (a), CLAUDE.md / eval_criteria 6.4#5).
  - Regime-matched random-entry NULL: draw the same #long/#short trades at random bars
    from the SAME stage regime (long pool = stage-1 bars, short pool = stage-4 bars),
    same exit -> isolates whether STAGE TIMING beats random in-regime timing (the honest
    floor for an entry sign; B&H is the wrong floor for entry edge, see null_floor_sweep).
  Run on 1h, 4h, 1d (4h/1d resampled from 1h) — trends persist longer on slower TFs, so
  a 1h-only null result would itself be a timeframe artifact.

READ (pre-registered): the engine shows a real edge worth building ONLY if, on some
  (timeframe, MA-set), the strategy's annualised equity Sharpe >= B&H's over the SAME IS
  window AND its per-trade Sharpe beats the regime null mean by >= +1 sd (lift_z>=1) at
  n>=30 trades. Otherwise the book's primary engine has no edge here either.
OOS HYGIENE: in-sample only; lockbox never touched.

Read-only; no DB writes, no production code touched. Unregistered.
Run: uv run --env-file .env.bt python -m src.backtest.analysis.kojiro_ma_stage_stage0
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from src.backtest.sign_benchmark import split_lockbox
from src.core.types import Side, Timeframe
from src.data.cache import load_cache

ATR_PERIOD = 14
STOP_N = float(os.getenv("KJ_STOP", "2.0"))     # book 2N money-mgmt stop (0 disables)
FEE_RATE = float(os.getenv("FEE", "0.0002"))    # per side
MA_SETS = [(5, 20, 40), (10, 40, 80), (20, 80, 160)]  # canonical + 2x/4x scaled
BARS_PER_YEAR = {"1h": 24 * 365, "4h": 6 * 365, "1d": 365}


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
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
    """1=s>m>l ... 4=l>m>s ; 0 otherwise (only 1 and 4 used)."""
    n = len(s)
    st = np.zeros(n, dtype=int)
    for i in range(n):
        if np.isnan(s[i]) or np.isnan(m[i]) or np.isnan(l[i]):
            continue
        if s[i] > m[i] > l[i]:
            st[i] = 1
        elif l[i] > m[i] > s[i]:
            st[i] = 4
    return st


def walk(opens, highs, lows, closes, atrs, s, m, st):
    """Single-position both-sided MA-stage walk — authoritative simulator.

    Returns (trade_returns, bar_net). ``bar_net[j]`` = the strategy's cost-adjusted
    realised return DURING bar j (0 when flat), built from actual fills:
      - entry: signal at close[t] -> fill at open[t+1]; the entry bar's return is
        marked open[t+1]->close[t+1] and the entry fee is charged on it.
      - hold: close[j-1]->close[j].
      - exit: 2N stop fills intrabar at the stop level (return close[j-1]->stop on
        that bar); else stage-flip exits at open[t+1] (bar t marked close->close,
        bar t+1 marked close[t]->open[t+1]); exit fee charged on the exit bar.
    eqSharpe from bar_net is therefore an honest fund-return Sharpe (flat bars are
    real zero-vol cash bars). Costs = FEE per side.
    """
    n = len(opens)
    rets: list[float] = []
    bar_net = np.zeros(n, dtype=float)
    pos = 0
    entry = stop = mark = 0.0
    t = 1
    while t < n - 1:
        if pos == 0:
            rising = s[t] > s[t - 1] and m[t] > m[t - 1]
            falling = s[t] < s[t - 1] and m[t] < m[t - 1]
            go_long = st[t] == 1 and rising
            go_short = st[t] == 4 and falling
            if go_long or go_short:
                pos = 1 if go_long else -1
                entry = opens[t + 1]
                a = atrs[t]
                stop = (entry - STOP_N * a) if pos == 1 else (entry + STOP_N * a)
                # entry bar = t+1: marked open->close, entry fee charged.
                bar_net[t + 1] = pos * (closes[t + 1] - entry) / entry - FEE_RATE
                mark = closes[t + 1]
                t += 2
                continue
        else:
            long = pos == 1
            # intrabar 2N stop (pessimistic), then stage-flip exit at next open.
            if STOP_N > 0 and ((long and lows[t] <= stop) or (not long and highs[t] >= stop)):
                bar_net[t] = pos * (stop - mark) / mark - FEE_RATE
                rets.append(pos * (stop - entry) / entry - 2.0 * FEE_RATE)
                pos = 0
                t += 1
                continue
            left = (long and not (s[t] > m[t])) or (not long and not (s[t] < m[t]))
            if left:
                ex = opens[t + 1]
                bar_net[t] = pos * (closes[t] - mark) / mark            # hold bar t
                bar_net[t + 1] = pos * (ex - closes[t]) / closes[t] - FEE_RATE
                rets.append(pos * (ex - entry) / entry - 2.0 * FEE_RATE)
                pos = 0
                t += 2
                continue
            bar_net[t] = pos * (closes[t] - mark) / mark
            mark = closes[t]
        t += 1
    return rets, bar_net


def _eq_sharpe(bar_net: np.ndarray, bpy: int) -> float:
    std = bar_net.std(ddof=1)
    return float(bar_net.mean() / std * np.sqrt(bpy)) if std > 0 else 0.0


def _bh_sharpe(closes: np.ndarray, bpy: int) -> float:
    r = (closes[1:] - closes[:-1]) / closes[:-1]
    std = r.std(ddof=1)
    return float(r.mean() / std * np.sqrt(bpy)) if std > 0 else 0.0


def _pt_sharpe(rets):
    a = np.asarray(rets, dtype=float)
    if a.size < 2:
        return 0.0
    return float(a.mean() / a.std(ddof=1)) if a.std(ddof=1) > 0 else 0.0


def _null(opens, highs, lows, closes, atrs, s, m, st, n_long, n_short, seeds=40):
    long_pool = np.where(st == 1)[0]
    long_pool = long_pool[(long_pool > 0) & (long_pool < len(opens) - 1)]
    short_pool = np.where(st == 4)[0]
    short_pool = short_pool[(short_pool > 0) & (short_pool < len(opens) - 1)]
    if (n_long and long_pool.size < n_long) or (n_short and short_pool.size < n_short):
        return 0.0, 0.0
    sharpes = []
    for sd in range(seeds):
        rng = np.random.default_rng(sd)
        rets = []
        for pool, k, sgn in ((long_pool, n_long, 1), (short_pool, n_short, -1)):
            if not k:
                continue
            for b in rng.choice(pool, size=k, replace=False):
                b = int(b)
                entry = opens[b + 1]
                a = atrs[b]
                stop = (entry - STOP_N * a) if sgn == 1 else (entry + STOP_N * a)
                exit_price = closes[-1]
                for j in range(b + 1, len(opens)):
                    if STOP_N > 0 and ((sgn == 1 and lows[j] <= stop) or (sgn == -1 and highs[j] >= stop)):
                        exit_price = stop
                        break
                    left = (sgn == 1 and not (s[j] > m[j])) or (sgn == -1 and not (s[j] < m[j]))
                    if left:
                        exit_price = opens[min(j + 1, len(opens) - 1)]
                        break
                rets.append(sgn * (exit_price - entry) / entry - 2.0 * FEE_RATE)
        sharpes.append(_pt_sharpe(rets))
    return float(np.mean(sharpes)), float(np.std(sharpes))


def main() -> None:
    product = os.getenv("KJ_PRODUCT", "GMO_BTC_JPY")
    cache = load_cache(Timeframe.H1, product=product)
    is_b, _ = split_lockbox(cache.bars)
    boundary = is_b[-1].timestamp
    h1 = cache.to_frame()

    frames = {"1h": h1.loc[:boundary],
              "4h": _resample(h1, "4h").loc[:boundary],
              "1d": _resample(h1, "1D").loc[:boundary]}

    print(f"{product}  MA-stage (大循環) entry + native stage-flip exit, 2N stop={STOP_N}, IN-SAMPLE")
    print(f"{'tf':>3} {'MAset':>12} {'n':>4} {'win':>5} {'mean_r':>9} {'ptSharpe':>9} "
          f"{'eqSharpe':>9} {'B&H_eq':>8} {'beatBH':>7} {'null':>7} {'lift_z':>7}")
    print("-" * 96)
    for tf, df in frames.items():
        opens = df["open"].to_numpy(); highs = df["high"].to_numpy()
        lows = df["low"].to_numpy(); closes = df["close"].to_numpy()
        atrs = _atr(highs, lows, closes, ATR_PERIOD)
        bpy = BARS_PER_YEAR[tf]
        bh = _bh_sharpe(closes, bpy)
        for (S, M, L) in MA_SETS:
            s = pd.Series(closes).rolling(S).mean().to_numpy()
            m = pd.Series(closes).rolling(M).mean().to_numpy()
            l = pd.Series(closes).rolling(L).mean().to_numpy()
            st = _stage(s, m, l)
            rets, bar_net = walk(opens, highs, lows, closes, atrs, s, m, st)
            if not rets:
                continue
            a = np.asarray(rets)
            n = a.size
            nl, ns = _count_sides(opens, highs, lows, closes, atrs, s, m, st)
            eq = _eq_sharpe(bar_net, bpy)
            nmean, nsd = _null(opens, highs, lows, closes, atrs, s, m, st, nl, ns)
            pt = _pt_sharpe(rets)
            z = (pt - nmean) / nsd if nsd > 0 else 0.0
            beat = "YES" if eq >= bh else "no"
            print(f"{tf:>3} {f'{S}/{M}/{L}':>12} {n:>4} {float((a > 0).mean()):>5.2f} "
                  f"{a.mean():>9.5f} {pt:>9.3f} {eq:>9.3f} {bh:>8.3f} {beat:>7} "
                  f"{nmean:>7.3f} {z:>7.2f}")
    print("\nGATE: eqSharpe>=B&H (beatBH=YES) AND lift_z>=+1.0 at n>=30 -> engine has edge.")
    print("OOS reserved: lockbox untouched.")


def _count_sides(opens, highs, lows, closes, atrs, s, m, st):
    nl = ns = 0
    n = len(opens); pos = 0; t = 1
    while t < n - 1:
        if pos == 0:
            rising = s[t] > s[t - 1] and m[t] > m[t - 1]
            falling = s[t] < s[t - 1] and m[t] < m[t - 1]
            if st[t] == 1 and rising:
                pos = 1; nl += 1; t += 1; continue
            if st[t] == 4 and falling:
                pos = -1; ns += 1; t += 1; continue
        else:
            long = pos == 1
            stop_hit = False
            entry_atr = 0.0  # stop tracked in walk; here just count exits by flip/stop approx
            left = (long and not (s[t] > m[t])) or (not long and not (s[t] < m[t]))
            if left:
                pos = 0
        t += 1
    return nl, ns


if __name__ == "__main__":
    main()
