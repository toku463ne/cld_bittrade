"""Stage-0: VPA **breakout-bar volume gate** on `density_breakout` (1h BTC).

The volume-information probe (vpa_volume_info_stage0.py) found that on GMO BTC/JPY
1h, volume points the CONFIRMATION direction (not the JP-stocks inversion), and the
cleanest cell is the 20h-breakout bar: high firing-bar volume -> stronger forward
continuation, low-volume breaks -> weakest (VPA's "low-vol break = fakeout"). This
A/B tests whether that whisper survives as a tradeable gate on the production sign.

Reuses the BOPB harness (same structural far-edge exit; only entry SELECTION changes):
  baseline  — every density_breakout fire (production behaviour).
  vol_gate  — only fires whose firing-bar vol_vs_avg = vol/SMA(vol,VOL_N) >= THR
              ("above-average and confirming", VPA Valid-breakout rule).
  anti_gate — only fires BELOW the threshold (VPA's fakeout/low-volume breaks).
  null      — random equal-size subset of baseline (selection control).

PRE-REGISTERED ACCEPT GATE (written before running; do not change after):
  On GMO BTC/JPY 1h IN-SAMPLE, adopt the volume gate on density_breakout ONLY if its
  PORTFOLIO view clears ALL of:
    (G1) vol_gate Sharpe >= baseline Sharpe + 0.05 AND vol_gate net Σret > 0, AND
    (G2) vol_gate Sharpe beats the random equal-size-subset null mean by >= +1.0 sd, AND
    (G3) anti_gate (low-vol breaks) Sharpe < vol_gate Sharpe (VPA's directional claim
         that low-volume breakouts are the weak/fakeout bucket), AND
    (G4) n_gate >= 30.
FALSIFIER: if anti_gate Sharpe >= vol_gate Sharpe, breakout-bar volume is inverted or
  noise here too -> REJECT (matches the JP-stocks vol_breakout_confirm inversion).
OOS HYGIENE: in-sample only; the lockbox OOS is never touched.

Read-only, unregistered. Run:
  uv run --env-file .env.bt python -m src.backtest.analysis.vpa_volgate_ab
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from src.backtest.analysis.bopb_gate_probe import Entry, _portfolio, _stats, walk
from src.backtest.sign_benchmark import split_lockbox
from src.core.types import Timeframe
from src.data.cache import load_cache
from src.signs.density_breakout import DensityBreakoutSign

VOL_N = int(os.getenv("VPA_VOL_N", "20"))
LOT = 0.001
SEEDS = int(os.getenv("HL_SEEDS", "40"))
THRESHOLDS = [float(x) for x in os.getenv("VPA_THR", "0.8,1.0,1.2,1.5").split(",")]


def main() -> None:
    product = os.getenv("HL_PRODUCT", "GMO_BTC_JPY")
    bars = load_cache(Timeframe.H1, product=product).bars
    is_b, _oos = split_lockbox(bars)  # IN-SAMPLE ONLY (hygiene)
    df = load_cache(Timeframe.H1, product=product).to_frame().loc[: is_b[-1].timestamp]
    opens = df["open"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    closes = df["close"].tolist()
    vol = df["volume"].to_numpy()
    vol_avg = pd.Series(vol).rolling(VOL_N).mean().to_numpy()
    vmult = np.where(vol_avg > 0, vol / vol_avg, np.nan)
    pos_of = {ts: i for i, ts in enumerate(df.index)}
    print(f"{product} 1h IN-SAMPLE: {len(df)} bars  {df.index[0]} -> {df.index[-1]}  (vol baseline N={VOL_N})")

    sign = DensityBreakoutSign()
    fires = sign.detect(df)

    # Resolve every fire to a baseline Entry plus its firing-bar vol_vs_avg.
    resolved: list[tuple[Entry, float]] = []
    for f in fires:
        t0 = pos_of.get(pd.Timestamp(f.fired_at))
        if t0 is None or t0 + 1 >= len(opens) or f.ref_price is None or f.ref2_price is None:
            continue
        band_h = abs(f.ref_price - f.ref2_price)
        if band_h <= 0 or not np.isfinite(vmult[t0]):
            continue
        resolved.append((Entry(t0 + 1, opens[t0 + 1], f.side, f.ref2_price, band_h), vmult[t0]))
    base = [e for e, _ in resolved]
    print(f"density_breakout fires resolved: {len(base)}\n")

    base_pf = _portfolio(opens, highs, lows, closes, base)
    bn, bs, bsh, bw = _stats(base_pf)
    print(f"{'arm':10} {'thr':>5} {'n_pf':>5} {'sum_ret':>9} {'sharpe':>8} {'win':>6} {'lift_z':>7}")
    print("-" * 56)
    print(f"{'baseline':10} {'-':>5} {bn:>5} {bs:>9.4f} {bsh:>8.3f} {bw:>6.2f} {'-':>7}")

    for thr in THRESHOLDS:
        gate = [e for e, vm in resolved if vm >= thr]
        anti = [e for e, vm in resolved if vm < thr]
        gpf = _portfolio(opens, highs, lows, closes, gate)
        apf = _portfolio(opens, highs, lows, closes, anti)
        gn, gs, gsh, gw = _stats(gpf)
        an, a_s, ash, aw = _stats(apf)
        # Null: random equal-size subset of baseline, matched to the gate's pf count.
        sharpes = []
        if 0 < gn <= len(base):
            for s in range(SEEDS):
                rng = np.random.default_rng(s)
                pick = [base[i] for i in rng.choice(len(base), size=gn, replace=False)]
                sharpes.append(_stats(_portfolio(opens, highs, lows, closes, pick))[2])
        nmean = float(np.mean(sharpes)) if sharpes else 0.0
        nsd = float(np.std(sharpes)) if sharpes else 0.0
        z = (gsh - nmean) / nsd if nsd > 0 else 0.0
        print(f"{'vol_gate':10} {thr:>5.1f} {gn:>5} {gs:>9.4f} {gsh:>8.3f} {gw:>6.2f} {z:>7.2f}")
        print(f"{'  anti':10} {thr:>5.1f} {an:>5} {a_s:>9.4f} {ash:>8.3f} {aw:>6.2f} {'-':>7}"
              f"   ({'gate>anti OK' if gsh > ash else 'INVERTED: anti>=gate'})")

    print("\nGATE: G1 vol_gate Sharpe>=baseline+0.05 & net>0 ; G2 lift_z>=+1.0 ; "
          "G3 anti<gate ; G4 n>=30.")
    print("FALSIFIER: anti_gate Sharpe>=vol_gate -> breakout-bar volume inverted/noise -> REJECT.")
    print("OOS reserved: lockbox untouched (run cycle WF once only if gate passes).")


if __name__ == "__main__":
    main()
