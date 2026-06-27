"""Stage-0: standalone VPA **high-volume wide-body continuation** entry on 1h BTC.

The last untested thread from docs/books/dekidaka.md. The volume-info probe found
the cleanest confirmatory cell on BTC/JPY 1h is the wide-body up bar on high volume
(VPA's effort-vs-result CONFIRMATION bar: big result + big effort = genuine ->
continuation). Unlike vpa_volgate_ab (which gated the EXISTING density_breakout),
this is a NEW standalone sign facing the repo's full fill-order-null bar.

ENTRY: a "confirmation bar" = up bar (close>open) with body_frac >= BODY_THR (wide
  body), vol_vs_avg = vol/SMA(vol,VOL_N) >= VOL_THR (high volume), close_pos >=
  CLOSE_POS_THR (close in the upper part = bulls won the bar). Fire LONG; mirror for
  the short arm (down bar, low close). Two-bar fill at open[t+1] (the honest
  tradeable version of the drift the info-probe measured).
EXIT: ATR trailing stop ride (reuses high2_low2_probe.walk), same as every with-trend
  ride probe — lets winners run.
NULL (the honest floor for a SELECTION sign): random equal-size subset of ALL up
  bars (longs) / down bars (shorts), same exit, HL_SEEDS seeds. Asks whether the
  volume+body+close SELECTION beats just "enter on any with-direction bar". If the
  sign only matches this null, the VPA confirmation features add nothing over the
  bar's direction alone (the high2_low2 failure mode).

PRE-REGISTERED ACCEPT GATE (written before running; do not change after):
  On GMO BTC/JPY 1h IN-SAMPLE, treat the long arm as a candidate sign ONLY if its
  PORTFOLIO view clears ALL of:
    (G1) net Σret > 0 AND per-trade Sharpe >= +0.10, AND
    (G2) Sharpe beats the random same-direction-bar subset null mean by >= +1.0 sd, AND
    (G3) n >= 30 portfolio fills.
FALSIFIER: if lift_z <= 0 (Sharpe <= random up-bar null), the volume/body/close
  selection adds nothing over "buy any up bar" -> REJECT (matches the marginal drift
  and the high2_low2 below-null result).
OOS HYGIENE: in-sample only; the lockbox OOS is never touched.

Read-only, unregistered. Run:
  uv run --env-file .env.bt python -m src.backtest.analysis.vpa_hivol_continuation_stage0
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
BODY_THR = float(os.getenv("VPA_BODY_THR", "0.5"))      # wide real body (>= half the range)
CLOSE_POS_THR = float(os.getenv("VPA_CLOSE_THR", "0.6"))  # close in the upper part of the bar
THRESHOLDS = [float(x) for x in os.getenv("VPA_THR", "1.2,1.5,2.0").split(",")]
LOT = 0.001
SEEDS = int(os.getenv("HL_SEEDS", "40"))


def _null(opens, highs, lows, closes, atrs, pool: np.ndarray, side: Side, count: int) -> tuple[float, float]:
    """Random same-direction-bar subset null: (sharpe_mean, sharpe_sd) over SEEDS seeds."""
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
    bars = load_cache(Timeframe.H1, product=product).bars
    is_b, _oos = split_lockbox(bars)  # IN-SAMPLE ONLY (hygiene)
    df = load_cache(Timeframe.H1, product=product).to_frame().loc[: is_b[-1].timestamp]
    o = df["open"].to_numpy()
    h = df["high"].to_numpy()
    low = df["low"].to_numpy()
    c = df["close"].to_numpy()
    vol = df["volume"].to_numpy()
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
    print(f"{product} 1h IN-SAMPLE: {n} bars  {df.index[0]} -> {df.index[-1]}  "
          f"(body>={BODY_THR} close_pos>={CLOSE_POS_THR} vol baseline N={VOL_N})\n")

    print(f"{'arm':6} {'thr':>5} {'view':11} {'n':>5} {'sum_ret':>9} {'sharpe':>8} {'win':>6} {'lift_z':>7}")
    print("-" * 60)
    for thr in THRESHOLDS:
        for side, dirmask, pool, sig_arr in (
            ("long", up, up_pool, highs),
            ("short", down, down_pool, lows),
        ):
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
            print(f"{side:6} {thr:>5.1f} {'portfolio':11} {pn:>5} {ps:>9.4f} {psh:>8.3f} {pw:>6.2f} {z:>7.2f}"
                  f"   (null_sh {nmean:+.3f}±{nsd:.3f})")
        print()

    print("GATE (long portfolio): G1 net>0 & sharpe>=+0.10 ; G2 lift_z>=+1.0 ; G3 n>=30.")
    print("FALSIFIER: lift_z<=0 -> volume/body/close selection adds nothing over 'buy any up bar' -> REJECT.")
    print("OOS reserved: lockbox untouched.")


if __name__ == "__main__":
    main()
