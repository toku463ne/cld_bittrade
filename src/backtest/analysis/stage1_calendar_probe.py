"""Stage-1 edge probe: JST calendar/flow family (Strategy E).

Tests whether GMO BTC_JPY leaves a tradeable calendar footprint — the 00:00 JST
swap cutoff, Tokyo open, US session, weekend fiat-ramp drift — fully orthogonal to
the price-structure book. The entire risk is multiple testing (168 hour×dow cells
throw ~8 false positives at p<.05), so two arms each carry their own control:

1. **Named family (7, Holm-corrected):** the mechanism-motivated buckets.
2. **Full 168-cell grid:** a circular-rotation max-|t| permutation test (rotate the
   return series against fixed calendar labels — preserves return autocorrelation,
   destroys calendar alignment), so the best cell is judged against what shuffled
   calendars produce, not against a naive per-cell threshold.

Pre-registered kill bars (study plan §E): KILL the family unless >=1 effect is
Holm-significant (named) or beats the rotation null (grid), AND same-sign in both
IS halves, AND same-sign on ETH, AND tradeable net of one 4 bp round-trip per
occurrence. BTC primary + ETH cross-confirm; lockbox-IS only (OOS held out).

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.stage1_calendar_probe
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.backtest.sign_benchmark import split_lockbox
from src.core.types import Timeframe
from src.data.cache import load_cache

FEE_RT = 0.0004  # one round-trip per overlay occurrence (4 bp)
N_ROT = 2000  # circular rotations for the grid max-|t| null
ALPHA = 0.05


def _norm_sf(z: float) -> float:
    """Two-sided normal tail prob (large-n t -> z; avoids a scipy dependency)."""
    return math.erfc(abs(z) / math.sqrt(2.0))


def _load(product: str) -> pd.DataFrame:
    """Lockbox-IS 1h returns with JST calendar columns and an early/late half flag."""
    bars = load_cache(Timeframe("1h"), product=product).bars
    is_bars, _ = split_lockbox(bars)  # OOS held out
    ts = pd.DatetimeIndex([b.timestamp for b in is_bars])
    close = np.array([b.close for b in is_bars], dtype=float)
    ret = np.concatenate([[np.nan], close[1:] / close[:-1] - 1.0])
    df = pd.DataFrame({"ret": ret}, index=ts).iloc[1:]
    idx = pd.DatetimeIndex(df.index)
    df["hour"] = idx.hour
    df["dow"] = idx.dayofweek  # Mon=0 .. Sun=6
    df["date"] = idx.normalize()
    iso = idx.isocalendar()
    df["week"] = iso.year.to_numpy() * 100 + iso.week.to_numpy()
    df["late"] = idx > idx[len(df) // 2]
    return df


def _bucket_t(r: np.ndarray) -> tuple[int, float, float]:
    """(n, mean_bp, t) for a return sample."""
    n = len(r)
    if n < 3:
        return n, 0.0, 0.0
    m = float(r.mean())
    sd = float(r.std(ddof=1))
    t = m / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return n, m * 1e4, t


@dataclass(slots=True)
class Named:
    name: str
    mask: np.ndarray
    group: str  # "date" or "week" — the tradeable occurrence unit


def _named(df: pd.DataFrame) -> list[Named]:
    h, d = df["hour"].to_numpy(), df["dow"].to_numpy()
    return [
        Named("weekend", d >= 5, "week"),
        Named("pre_cutoff_21_23", np.isin(h, [21, 22, 23]), "date"),
        Named("post_cutoff_00_01", np.isin(h, [0, 1]), "date"),
        Named("tokyo_open_09_11", np.isin(h, [9, 10, 11]), "date"),
        Named("us_session_22_05", np.isin(h, [22, 23, 0, 1, 2, 3, 4, 5]), "date"),
        Named("friday", d == 4, "date"),
        Named("monday", d == 0, "date"),
    ]


def _overlay_net_bp(df: pd.DataFrame, mask: np.ndarray, group: str) -> tuple[float, float, float]:
    """Per-occurrence overlay net of one RT: (net_bp, early_bp, late_bp)."""
    sub = df[mask]
    occ = sub.groupby(sub[group])["ret"].sum() - FEE_RT
    early = df[mask & ~df["late"].to_numpy()]
    late = df[mask & df["late"].to_numpy()]
    e = early.groupby(early[group])["ret"].sum() - FEE_RT
    la = late.groupby(late[group])["ret"].sum() - FEE_RT
    return float(occ.mean() * 1e4), float(e.mean() * 1e4), float(la.mean() * 1e4)


def _holm(pvals: list[float]) -> list[bool]:
    """Holm-Bonferroni step-down at ALPHA; returns reject flags in input order."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    reject = [False] * m
    for rank, i in enumerate(order):
        if pvals[i] <= ALPHA / (m - rank):
            reject[i] = True
        else:
            break
    return reject


def _grid_rotation_test(df: pd.DataFrame) -> tuple[float, float, float, int]:
    """Circular-rotation max-|t| test on the 168 hour×dow grid.

    Returns ``(observed_max_t, null_p95, p_value, best_cell_id)``.
    """
    r = df["ret"].to_numpy()
    cell = (df["hour"].to_numpy() * 7 + df["dow"].to_numpy()).astype(int)
    n = len(r)
    counts = np.bincount(cell, minlength=168).astype(float)

    def max_t(x: np.ndarray) -> tuple[float, int]:
        s1 = np.bincount(cell, weights=x, minlength=168)
        s2 = np.bincount(cell, weights=x * x, minlength=168)
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = s1 / counts
            var = (s2 / counts - mean**2) * counts / np.maximum(counts - 1, 1)
            se = np.sqrt(var / counts)
            t = np.where((counts >= 3) & (se > 0), mean / se, 0.0)
        amax = int(np.argmax(np.abs(t)))
        return float(abs(t[amax])), amax

    obs, best = max_t(r)
    rng = np.random.default_rng(0)
    null = np.empty(N_ROT)
    for i in range(N_ROT):
        off = int(rng.integers(1, n))
        null[i], _ = max_t(np.roll(r, off))
    p = float((null >= obs).mean())
    return obs, float(np.percentile(null, 95)), p, best


def main() -> None:
    """Run the calendar probe on BTC (primary) with ETH cross-confirm."""
    btc, eth = _load("GMO_BTC_JPY"), _load("GMO_ETH_JPY")
    print(f"BTC IS bars={len(btc)}  ETH IS bars={len(eth)}  (lockbox OOS held out)")

    # ---- Named family (Holm) ------------------------------------------------
    print("\n=== NAMED FAMILY (Holm-corrected alpha=0.05) ===")
    print(f"  {'bucket':18} {'n':>6} {'mean_bp':>8} {'t':>6} {'p':>8} | "
          f"{'net_bp':>7} {'early':>7} {'late':>7} | {'ETH_bp':>7} {'ETH_t':>6}")
    eth_named = {x.name: x.mask for x in _named(eth)}
    rows = []
    for nm in _named(btc):
        _n, mbp, t = _bucket_t(btc["ret"].to_numpy()[nm.mask])
        p = _norm_sf(t)
        net, e, la = _overlay_net_bp(btc, nm.mask, nm.group)
        _en, embp, et = _bucket_t(eth["ret"].to_numpy()[eth_named[nm.name]])
        rows.append((nm, p, mbp, t, net, e, la, embp, et))
    rej = _holm([r[1] for r in rows])
    survivors = []
    for (nm, p, mbp, t, net, e, la, embp, et), rj in zip(rows, rej, strict=True):
        half_ok = (e > 0) == (la > 0) and abs(e) > 0 and abs(la) > 0
        eth_ok = (embp > 0) == (mbp > 0)
        flag = "HOLM✓" if rj else ""
        mark = " <-- SURVIVOR" if (rj and half_ok and eth_ok and net > 0) else ""
        if rj and half_ok and eth_ok and net > 0:
            survivors.append(nm.name)
        print(f"  {nm.name:18} {len(btc['ret'].to_numpy()[nm.mask]):>6} {mbp:>8.2f} {t:>6.2f} "
              f"{p:>8.4f} | {net:>7.1f} {e:>7.1f} {la:>7.1f} | {embp:>7.2f} {et:>6.2f} "
              f"{flag}{mark}")

    # ---- Full grid (circular-rotation max-|t|) ------------------------------
    print("\n=== FULL 168-CELL GRID (circular-rotation max-|t|, 2000 rotations) ===")
    obs, p95, pval, best = _grid_rotation_test(btc)
    bh, bd = best // 7, best % 7
    dows = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    bn, bmbp, _ = _bucket_t(btc["ret"].to_numpy()[(btc["hour"] == bh) & (btc["dow"] == bd)])
    print(f"  observed max|t|={obs:.2f}  rotation-null p95={p95:.2f}  p={pval:.3f}  "
          f"-> {'BEATS null' if pval < ALPHA else 'within noise'}")
    print(f"  best cell: {dows[bd]} {bh:02d}:00 JST  n={bn} mean={bmbp:+.2f}bp")

    print("\n=== VERDICT ===")
    if survivors:
        print(f"  SURVIVORS (named, all gates): {survivors} -> Stage 2")
    elif pval < ALPHA:
        print(f"  grid beats rotation null (p={pval:.3f}) -> inspect best cell's halves/ETH/cost")
    else:
        print("  NO survivor: no named bucket clears all gates AND the grid is within "
              "rotation noise -> per pre-registration, DROP the calendar family.")


if __name__ == "__main__":
    from src.config import get_settings
    from src.logging_setup import configure_logging

    configure_logging(get_settings().log_level)
    main()
