"""Validate the daily-momentum lead: IS/OOS, per-year, decomposition, significance.

The daily probe found the project's first positive gross edge (time-series
momentum + Turtle breakout, net-positive even after ~4 bp/day swap). Before
believing it, apply real rigor:

- **IS/OOS**: train on first 80% of days, hold out the most recent 20%.
- **Per-year consistency**: ship gate analogue — how many calendar years net-positive.
- **Long/short decomposition** (TSMOM): is the edge genuine short-side timing, or
  just leveraged length in a bull market?
- **Significance**: annualised Sharpe -> t-stat (= Sharpe·√years); ~5 years is few
  independent trend regimes, so a high Sharpe can still be insignificant.
- **Swap sensitivity**: net Sharpe at swap ∈ {0, 4, 8} bp/day (the rate is an
  estimate; the net verdict must be robust to it).

Benchmark = buy-and-hold (per CLAUDE.md). All NET figures include swap (always-in
for TSMOM; per-day-held for Donchian).
Run: uv run --env-file .env.bt python -m src.backtest.analysis.daily_momentum_validate
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.backtest.analysis.daily_momentum_probe import SWAP_BP_PER_DAY, donchian, to_daily


def _t_and_sharpe(r: np.ndarray, years: float) -> tuple[float, float, float]:
    """(annualised Sharpe, t-stat, total %) for a daily-return array."""
    if r.size < 2:
        return 0.0, 0.0, 0.0
    sd = float(r.std(ddof=1))
    sh_d = float(r.mean() / sd) if sd > 0 else 0.0
    return sh_d * np.sqrt(365.0), sh_d * np.sqrt(r.size), float(r.sum()) * 100.0


def tsmom_series(c: np.ndarray, dts: pd.DatetimeIndex, L: int) -> tuple[pd.Series, pd.Series]:
    """Gross daily TSMOM returns and position, indexed by realisation date."""
    n = len(c)
    pos = np.sign(c[L : n - 1] / c[0 : n - 1 - L] - 1.0)
    ret_next = (c[L + 1 : n] - c[L : n - 1]) / c[L : n - 1]
    idx = dts[L + 1 : n]
    return pd.Series(pos * ret_next, index=idx), pd.Series(pos, index=idx)


def main() -> None:
    d = to_daily()
    c = d["close"].to_numpy(dtype=float)
    dts = pd.DatetimeIndex(d.index)
    bh_daily = pd.Series(np.diff(c) / c[:-1], index=dts[1:])
    years = (dts[-1] - dts[0]).days / 365.25
    print(f"GMO daily {dts[0]:%Y-%m-%d}..{dts[-1]:%Y-%m-%d} ({years:.1f}y)  "
          f"buy&hold = {(c[-1]/c[0]-1)*100:+.0f}%  swap={SWAP_BP_PER_DAY:.0f}bp/day\n")

    for L in (30, 60):
        gross, pos = tsmom_series(c, dts, L)
        net = gross - SWAP_BP_PER_DAY / 1e4
        gy = (dts[-1] - gross.index[0]).days / 365.25
        print(f"=== TSMOM lookback={L}d  (n={len(gross)} days) ===")
        for label, r in (("gross", gross.to_numpy()), ("net(swap)", net.to_numpy())):
            sh, t, tot = _t_and_sharpe(r, gy)
            print(f"  full {label:9} Sharpe={sh:+.2f}  t={t:+.2f}  total={tot:+.0f}%")

        # IS / OOS split (first 80% / last 20% of days)
        k = int(0.8 * len(net))
        for label, seg in (("IS ", net.iloc[:k]), ("OOS", net.iloc[k:])):
            sh, t, tot = _t_and_sharpe(seg.to_numpy(), len(seg) / 365.25)
            print(f"  {label} net      Sharpe={sh:+.2f}  t={t:+.2f}  total={tot:+.0f}%  "
                  f"({seg.index[0]:%Y-%m}..{seg.index[-1]:%Y-%m})")

        # Per-year net vs buy-and-hold
        ny = net.groupby(pd.DatetimeIndex(net.index).year).sum() * 100
        by = bh_daily.groupby(pd.DatetimeIndex(bh_daily.index).year).sum() * 100
        pos_years = int((ny >= 0).sum())
        print(f"  per-year net (≥0 in {pos_years}/{len(ny)} yrs):")
        for y in ny.index:
            print(f"      {y}: strat {ny[y]:+6.0f}%   b&h {by.get(y, float('nan')):+6.0f}%")

        # Long / short decomposition (gross)
        g = gross.to_numpy()
        p = pos.to_numpy()
        lc, sc = float(g[p > 0].sum()) * 100, float(g[p < 0].sum()) * 100
        print(f"  decomp (gross): long days={int((p>0).sum())} contrib={lc:+.0f}%  | "
              f"short days={int((p<0).sum())} contrib={sc:+.0f}%")

        # Swap sensitivity
        sens = "  swap sensitivity (net Sharpe):  " + "  ".join(
            f"{s:.0f}bp={_t_and_sharpe(gross.to_numpy() - s/1e4, gy)[0]:+.2f}" for s in (0, 4, 8)
        )
        print(sens + "\n")

    # Donchian 55/20 — thin sample, report IS/OOS per-trade
    o, h, low, cc = (d[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    trades = donchian(o, h, low, cc, 55, 20)
    gr = np.array([g for _, g, _ in trades])
    dy = np.array([dd for _, _, dd in trades])
    net_tr = gr - (SWAP_BP_PER_DAY * dy + 1.0) / 1e4
    k = int(0.8 * len(net_tr))
    print(f"=== Donchian 55/20  (n={len(trades)} trades — THIN, n<100) ===")
    print(f"  full net  total={net_tr.sum()*100:+.0f}%  per-trade Sharpe={(net_tr.mean()/net_tr.std(ddof=1)):+.3f}")
    print(f"  IS  net   total={net_tr[:k].sum()*100:+.0f}%  (first {k} trades)")
    print(f"  OOS net   total={net_tr[k:].sum()*100:+.0f}%  (last {len(net_tr)-k} trades)")


if __name__ == "__main__":
    main()
