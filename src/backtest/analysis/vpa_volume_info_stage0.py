"""Stage-0 foundational probe: does relative VOLUME carry forward information on
GMO BTC/JPY 1h — confirmation, exhaustion (inverted), or null?

Anna Coulling's VPA (docs/books/dekidaka.md) rests on ONE axiom: volume CONFIRMS
price (wide body + high volume -> genuine -> continuation; the move is real). The
sister JP-stocks-daily repo's adaptation notes already record the OPPOSITE on that
market — `vol_breakout_confirm` rejected INVERTED (high-vol breakouts underperform),
`lowprice_volspike` rejected INVERTED (spike marks the move ENDING). This repo has
its own corroboration: `density_breakout_vol` (volume acceptance) was rejected vs the
time-at-price profile. Before building ANY of the six VPA sign candidates, settle the
gating question on THIS market: which way does volume point on BTC/JPY 1h?

METHOD (per-fire forward distribution, the doc's prescribed Stage-0 — NOT a strategy):
  Per bar features (relative, per the VPA Cardinal Rule): vol_vs_avg = volume/SMA(volume,N),
  body_frac, close_pos, range_vs_avg. Forward signed-CONTINUATION return at horizon H:
    dir = +1 if close>open else -1 ; cont_r(t,H) = dir * (close[t+H]/close[t] - 1).
    cont_r > 0  <=> the bar's own direction continued (continuation paid).
  Cut each conditioning subset into vol_vs_avg quartiles (Q1 low .. Q4 extreme) and
  read mean cont_r + DR across quartiles, plus corr(vol_vs_avg, cont_r):
    monotone UP   (Q4>Q1, corr>0)  = VPA confirmation holds (volume = genuineness),
    monotone DOWN (Q4<Q1, corr<0)  = EXHAUSTION/inverted (volume = the move ending),
    flat                            = volume is noise here.

  Subsets: all-up bars, all-down bars (the core effort-vs-result claim), wide-body up
  bars (the canonical CONFIRMATION bar), narrow-body up bars (the NO-DEMAND/exhaustion
  bar), and 20-bar-high breakout bars (vol_breakout_confirm). Baseline = unconditional
  forward drift, so each cell reads as lift over the drift floor.

READ (pre-registered interpretation; this is diagnostic, not a ship gate):
  If high-vol cells do NOT beat low-vol cells on cont_r for the CONTINUATION subsets
  (up/down/wide-up/breakout) — i.e. corr <= 0 or flat — then VPA's confirmation axiom
  does NOT hold on BTC/JPY 1h, and the confirmation/breakout-gate VPA signs
  (vol_breakout_confirm, effort-vs-result confirmation) are dead on arrival here, just
  as on the JP-stocks repo. A NEGATIVE corr additionally supports the EXHAUSTION/climax
  reversal reading (the only VPA family then worth a probe — but those are bottom/top
  fishing reversals, the family this repo's nulls keep killing). No production change
  rides on this probe; it decides WHICH (if any) VPA sign earns a real Stage-0.
OOS HYGIENE: in-sample only; the lockbox OOS is never touched.

Read-only: no DB writes, no production sign/strategy changes. Unregistered.
Run: uv run --env-file .env.bt python -m src.backtest.analysis.vpa_volume_info_stage0
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from src.backtest.sign_benchmark import split_lockbox
from src.core.types import Timeframe
from src.data.cache import load_cache

VOL_N = int(os.getenv("VPA_VOL_N", "20"))     # rolling baseline for vol_vs_avg / range
HORIZONS = (6, 24, 48)                          # forward bars (~6h, 1d, 2d on 1h)


def _quartile_table(vmult: np.ndarray, cont: np.ndarray, mask: np.ndarray, label: str, H: int) -> None:
    """Print n / mean cont_r(%) / DR per vol_vs_avg quartile for the masked subset."""
    v = vmult[mask]
    c = cont[mask]
    ok = np.isfinite(v) & np.isfinite(c)
    v, c = v[ok], c[ok]
    if v.size < 40:
        print(f"  {label:18} H{H:<3} n={v.size:<6} (too thin)")
        return
    qs = np.quantile(v, [0.25, 0.5, 0.75])
    edges = [-np.inf, *qs, np.inf]
    cells = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (v > lo) & (v <= hi)
        cc = c[m]
        cells.append((cc.size, float(cc.mean() * 100), float((cc > 0).mean())))
    corr = float(np.corrcoef(v, c)[0, 1]) if v.size > 2 else 0.0
    q1r, q4r = cells[0][1], cells[-1][1]
    cells_s = "  ".join(f"Q{i+1}[{n}] {r:+.2f}%/{d:.0%}" for i, (n, r, d) in enumerate(cells))
    arrow = "UP(confirm)" if corr > 0.01 else ("DOWN(exhaust)" if corr < -0.01 else "flat")
    print(f"  {label:18} H{H:<3} {cells_s}   Q4-Q1 {q4r - q1r:+.2f}%  corr {corr:+.3f} {arrow}")


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
    n = len(df)
    print(f"{product} 1h IN-SAMPLE: {n} bars  {df.index[0]} -> {df.index[-1]}  (vol baseline N={VOL_N})\n")

    rng = np.maximum(h - low, 1e-12)
    body_frac = np.abs(c - o) / rng
    vol_avg = pd.Series(vol).rolling(VOL_N).mean().to_numpy()
    vmult = np.where(vol_avg > 0, vol / vol_avg, np.nan)
    direction = np.where(c >= o, 1.0, -1.0)
    up = c > o
    down = c < o
    body_med = np.nanmedian(body_frac)
    wide_up = up & (body_frac > body_med)
    narrow_up = up & (body_frac <= body_med)
    # 20-bar-high breakout: close clears the prior 20-bar high.
    prior_hi = pd.Series(h).rolling(20).max().shift(1).to_numpy()
    breakout = c > prior_hi

    for H in HORIZONS:
        fwd = np.full(n, np.nan)
        fwd[: n - H] = c[H:] / c[: n - H] - 1.0
        cont = direction * fwd  # signed continuation: >0 = bar's direction continued

        base = cont[np.isfinite(cont)]
        print(f"== horizon H={H} ==  unconditional cont_r {base.mean() * 100:+.3f}%  "
              f"DR {(base > 0).mean():.1%}  (drift floor)")
        _quartile_table(vmult, cont, up, "up bars", H)
        _quartile_table(vmult, cont, down, "down bars", H)
        _quartile_table(vmult, cont, wide_up, "wide-body up", H)
        _quartile_table(vmult, cont, narrow_up, "narrow up (no-dem)", H)
        _quartile_table(vmult, cont, breakout, "20h breakout", H)
        print()

    print("READ: continuation subsets (up/down/wide-up/breakout) with corr>0 & Q4>Q1 = VPA")
    print("confirmation holds; corr<0 & Q4<Q1 = EXHAUSTION/inverted (volume marks the move ending);")
    print("flat = volume is noise. Decides which (if any) VPA sign earns a real Stage-0.")


if __name__ == "__main__":
    main()
