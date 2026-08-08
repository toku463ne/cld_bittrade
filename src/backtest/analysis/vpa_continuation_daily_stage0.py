"""Stage-0 (bias-corrected re-test): VPA high-volume wide-body CONTINUATION on DAILY BTC.

WHY (2026-06-28, after the Kojiro bias check): the 1h VPA continuation
(`vpa_hivol_continuation_stage0.py`) was the ONLY book-derived feature that beat its
random null (lift_z 1.4-1.9 > 1) yet was net-NEGATIVE — because the 1h base rate
("buy any up bar + ride") was −0.19 (mean-reversion + trail whipsaw at 1h). That is the
SAME 1h problem the Kojiro MA-stage only escaped on the DAILY timeframe (where the
continuation base rate turns positive). So the 1h-only rejection may be a timeframe
bias: an info-carrying volume signal bolted onto a NEGATIVE 1h base rate could flip
net-positive on daily, where the base rate is positive. This re-tests it on daily,
otherwise identical to the 1h probe (same sign, same ride exit, same random-up-bar null).

KEY DIAGNOSTIC: the null's OWN Sharpe (null_sh) = the daily "buy any up bar + ride" base
rate. If it is now POSITIVE (vs 1h's −0.19) AND the VPA selection still beats it
(lift_z >= 1), the sign can be net-positive — the bias would be confirmed. If the daily
base rate is still ~0/negative, or the selection no longer beats null, the rejection
holds and was not a timeframe artifact.

ENTRY: confirmation bar = up bar, body_frac>=BODY_THR, vol/SMA(vol,N)>=VOL_THR,
  close_pos>=CLOSE_POS_THR (mirror for shorts). Two-bar fill. EXIT: ATR-trail ride
  (reuses high2_low2_probe.walk; sl2/trail2/time48 — 48 days on daily).
NULL: random equal-size same-direction-bar subset, same exit, SEEDS seeds.
GATE (pre-registered): long portfolio clears (G1) net>0 & Sharpe>=+0.10, (G2) lift_z>=+1.0,
  (G3) n>=30. FALSIFIER: lift_z<=0 -> selection adds nothing over "buy any up bar" -> the
  rejection was NOT a timeframe bias.
OOS HYGIENE: in-sample only; lockbox untouched. Read-only, unregistered.
Run: uv run --env-file .env.bt python -m src.backtest.analysis.vpa_continuation_daily_stage0
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from src.backtest.analysis.high2_low2_probe import Fire, _portfolio, _stats, walk
from src.backtest.sign_benchmark import split_lockbox
from src.core.types import Side, Timeframe
from src.data.cache import load_cache
from src.indicators import atr

VOL_N = int(os.getenv("VPA_VOL_N", "20"))
BODY_THR = float(os.getenv("VPA_BODY_THR", "0.5"))
CLOSE_POS_THR = float(os.getenv("VPA_CLOSE_THR", "0.6"))
THRESHOLDS = [float(x) for x in os.getenv("VPA_THR", "1.2,1.5,2.0").split(",")]
SEEDS = int(os.getenv("HL_SEEDS", "40"))
RULE = os.getenv("VPA_RULE", "1D")


def _null(opens, highs, lows, closes, atrs, pool, side, count):
    if count <= 0 or pool.size < count:
        return 0.0, 0.0
    sharpes = []
    for s in range(SEEDS):
        rng = np.random.default_rng(s)
        picks = [Fire(int(b), side, highs[int(b)] if side is Side.LONG else lows[int(b)])
                 for b in rng.choice(pool, size=count, replace=False)]
        picks.sort(key=lambda f: f.bar)
        sharpes.append(_stats(_portfolio(opens, highs, lows, closes, atrs, picks, False))[2])
    a = np.asarray(sharpes)
    return float(a.mean()), float(a.std())


def main() -> None:
    product = os.getenv("HL_PRODUCT", "GMO_BTC_JPY")
    cache = load_cache(Timeframe.H1, product=product)
    is_b, _ = split_lockbox(cache.bars)
    boundary = is_b[-1].timestamp
    h1 = cache.to_frame()
    df = h1.resample(RULE).agg(open=("open", "first"), high=("high", "max"),
                               low=("low", "min"), close=("close", "last"),
                               volume=("volume", "sum")).dropna().loc[:boundary]
    o = df["open"].to_numpy(); h = df["high"].to_numpy()
    low = df["low"].to_numpy(); c = df["close"].to_numpy(); vol = df["volume"].to_numpy()
    opens, highs, lows, closes = o.tolist(), h.tolist(), low.tolist(), c.tolist()
    atrs = [float(v) for v in atr(df, 14).to_numpy()]
    n = len(df)

    rng_ = np.maximum(h - low, 1e-12)
    body_frac = np.abs(c - o) / rng_
    close_pos = (c - low) / rng_
    vol_avg = pd.Series(vol).rolling(VOL_N).mean().to_numpy()
    vmult = np.where(vol_avg > 0, vol / vol_avg, np.nan)
    up = c > o
    down = c < o
    up_pool = np.array([t for t in range(n - 1) if up[t]], dtype=int)
    down_pool = np.array([t for t in range(n - 1) if down[t]], dtype=int)
    print(f"{product} {RULE} IN-SAMPLE: {n} bars  {df.index[0].date()} -> {df.index[-1].date()}  "
          f"(body>={BODY_THR} close_pos>={CLOSE_POS_THR} volN={VOL_N})\n")

    print(f"{'arm':6} {'thr':>5} {'view':11} {'n':>5} {'sum_ret':>9} {'sharpe':>8} {'win':>6} "
          f"{'lift_z':>7} {'null_sh(base rate)':>20}")
    print("-" * 78)
    for thr in THRESHOLDS:
        for side, dirmask, pool, sig_arr in (("long", up, up_pool, highs), ("short", down, down_pool, lows)):
            sd = Side.LONG if side == "long" else Side.SHORT
            sel = (dirmask & (body_frac >= BODY_THR) & (vmult >= thr)
                   & ((close_pos >= CLOSE_POS_THR) if side == "long" else (close_pos <= 1 - CLOSE_POS_THR)))
            fires = [Fire(t, sd, sig_arr[t]) for t in range(n - 1) if sel[t]]
            eq = [r[0] for fr in fires if (r := walk(opens, highs, lows, closes, fr, atrs[fr.bar], False)) is not None]
            en, es, esh, ew = _stats(eq)
            pf = _portfolio(opens, highs, lows, closes, atrs, fires, False)
            pn, ps, psh, pw = _stats(pf)
            nmean, nsd = _null(opens, highs, lows, closes, atrs, pool, sd, pn)
            z = (psh - nmean) / nsd if nsd > 0 else 0.0
            print(f"{side:6} {thr:>5.1f} {'entry-qual':11} {en:>5} {es:>9.4f} {esh:>8.3f} {ew:>6.2f} {'-':>7}")
            print(f"{side:6} {thr:>5.1f} {'portfolio':11} {pn:>5} {ps:>9.4f} {psh:>8.3f} {pw:>6.2f} "
                  f"{z:>7.2f} {nmean:>+13.3f}±{nsd:.3f}")
        print()

    print("GATE (long portfolio): G1 net>0 & sharpe>=+0.10 ; G2 lift_z>=+1.0 ; G3 n>=30.")
    print("DIAGNOSTIC: null_sh = daily 'buy any up bar + ride' base rate (1h was −0.19).")
    print("FALSIFIER: lift_z<=0 -> selection adds nothing; rejection was NOT a timeframe bias.")
    print("OOS reserved: lockbox untouched.")


if __name__ == "__main__":
    main()
