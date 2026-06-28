"""Stage-0: standalone VPA **climax-reversal sequence** entry on 1h BTC.

The one genuinely ISOLATED family from docs/books/dekidaka.md (Coulling VPA) vs the
shipped books: every live edge is continuation/breakout/vol-expansion; this is the
orthogonal REVERSAL family (selling/buying climax). The repo previously dismissed the
VPA reversal family from a FOUNDATIONAL down-bar-volume correlation (corr~0, memory
vpa-volume-btc-confirmatory-but-faint) -- but a gated multi-bar climax SEQUENCE
detector (extreme vol + reversal-bar wick + close-position, inside a steep-trend
regime) was never actually built and measured. This probe closes that gap.

LONG arm = SELLING CLIMAX at a bottom: bar sits in a steep-decline regime (close <
  SMA(REGIME_N) AND price fell >= DECLINE over the last REGIME_N bars), with extreme
  vol_vs_avg = vol/SMA(vol,VOL_N) >= THR, a long LOWER wick (lower_wick_frac >=
  WICK_THR) and close_pos >= 0.5 (sellers absorbed, close lifts back up). Fire LONG.
SHORT arm = BUYING CLIMAX at a top (mirror): steep-advance regime, extreme vol, long
  UPPER wick, close_pos <= 0.5. Fire SHORT. Two-bar fill at open[t+1]; ATR-trail ride.
NULL (regime-matched, the honest floor for a SELECTION sign): random equal-size
  subset of ALL bars IN THE SAME steep regime (long pool = steep-decline bars; short
  pool = steep-advance bars), same direction, same exit, SEEDS seeds. Holds the
  counter-trend regime exposure constant and asks only whether the climax SELECTION
  (extreme-vol + wick + close) beats "buy any bar in the down-regime and ride the
  bounce". If the sign only matches this null, the VPA climax features add nothing
  over the regime alone (the high2_low2 / sweep_reclaim failure mode).

PRE-REGISTERED ACCEPT GATE (written before running; do not change after):
  On GMO_BTC_JPY 1h IN-SAMPLE, treat an arm as a candidate sign ONLY if its PORTFOLIO
  view clears ALL of:
    (G1) net sum_ret > 0 AND per-trade Sharpe >= +0.10, AND
    (G2) Sharpe beats the regime-matched random null mean by >= +1.0 sd (lift_z>=1.0),
    (G3) n >= 30 portfolio fills (else too thin to read -- flag, do not conclude).
FALSIFIER: if lift_z <= 0 (Sharpe <= regime-matched null), the climax selection adds
  nothing over "buy any bar in the regime and ride" -> REJECT the VPA reversal family
  (confirms the dead-reversal prior + the corr~0 down-bar-volume foundational check).
OOS HYGIENE: in-sample only; the lockbox OOS is never touched.

Read-only, unregistered. Run:
  uv run --env-file .env.bt python -m src.backtest.analysis.climax_reversal_stage0
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

VOL_N = int(os.getenv("CLX_VOL_N", "20"))
REGIME_N = int(os.getenv("CLX_REGIME_N", "20"))         # lookback for the steep-trend regime
DECLINE = float(os.getenv("CLX_DECLINE", "0.02"))       # >=2% move over REGIME_N bars = "steep"
WICK_THR = float(os.getenv("CLX_WICK_THR", "0.4"))      # long rejection wick (>= 40% of range)
THRESHOLDS = [float(x) for x in os.getenv("CLX_THR", "2.0,2.5,3.0").split(",")]
SEEDS = int(os.getenv("HL_SEEDS", "40"))


def _null(opens, highs, lows, closes, atrs, pool: np.ndarray, side: Side, count: int) -> tuple[float, float]:
    """Regime-matched random subset null: (sharpe_mean, sharpe_sd) over SEEDS seeds."""
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
    close_pos = (c - low) / rng_
    upper_wick = (h - np.maximum(o, c)) / rng_
    lower_wick = (np.minimum(o, c) - low) / rng_
    vol_avg = pd.Series(vol).rolling(VOL_N).mean().to_numpy()
    vmult = np.where(vol_avg > 0, vol / vol_avg, np.nan)

    sma = pd.Series(c).rolling(REGIME_N).mean().to_numpy()
    past = pd.Series(c).shift(REGIME_N).to_numpy()
    chg = np.where(past > 0, (c - past) / past, np.nan)            # signed move over REGIME_N
    down_regime = (c < sma) & (chg <= -DECLINE)                    # steep decline (long/selling-climax)
    up_regime = (c > sma) & (chg >= DECLINE)                       # steep advance (short/buying-climax)
    down_pool = np.array([t for t in range(REGIME_N, n - 1) if down_regime[t]], dtype=int)
    up_pool = np.array([t for t in range(REGIME_N, n - 1) if up_regime[t]], dtype=int)

    print(f"{product} 1h IN-SAMPLE: {n} bars  {df.index[0]} -> {df.index[-1]}")
    print(f"  regime: |chg|>={DECLINE:.0%} over {REGIME_N}b vs SMA  (down-pool {down_pool.size}, up-pool {up_pool.size})")
    print(f"  climax: wick>={WICK_THR} close_pos gated, vol baseline N={VOL_N}\n")

    print(f"{'arm':6} {'thr':>5} {'view':11} {'n':>5} {'sum_ret':>9} {'sharpe':>8} {'win':>6} {'lift_z':>7}")
    print("-" * 64)
    for thr in THRESHOLDS:
        for side, regime, pool, sig_arr in (
            ("long", down_regime, down_pool, highs),
            ("short", up_regime, up_pool, lows),
        ):
            sd = Side.LONG if side == "long" else Side.SHORT
            if side == "long":
                sel = regime & (vmult >= thr) & (lower_wick >= WICK_THR) & (close_pos >= 0.5)
            else:
                sel = regime & (vmult >= thr) & (upper_wick >= WICK_THR) & (close_pos <= 0.5)
            fires = [Fire(t, sd, sig_arr[t]) for t in range(REGIME_N, n - 1) if sel[t]]
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

    print("GATE (per arm portfolio): G1 net>0 & sharpe>=+0.10 ; G2 lift_z>=+1.0 ; G3 n>=30.")
    print("FALSIFIER: lift_z<=0 -> climax selection adds nothing over 'buy any bar in regime' -> REJECT.")
    print("OOS reserved: lockbox untouched.")


if __name__ == "__main__":
    main()
