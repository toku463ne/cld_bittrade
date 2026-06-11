"""Multi-asset portfolio of the shipped books — yearly-return stability.

Combines the three promotable books, which trade DIFFERENT instruments (so slots
cannot be shared across them — only the BTC dp+ver pair shares slots, already
folded into ``combo_dp_ver``):

    combo_dp_ver (BTC) | density_pullback_eth (ETH) | density_pullback_xrp (XRP)

Two levers, per the request:
  * slot number — each book's concurrency cap = its REQUIRED capital. The honest
    minimum is the observed peak concurrency (fewer slots than that would drop
    trades); return is measured on that base, so trimming idle slots raises the
    return-on-capital directly.
  * slot size — the per-book capital weight (how the budget is split across books).

Normalization: each book's contribution is **return on required capital** =
(sum of net per-trade returns in the period) / (peak concurrency). ``return_pct``
is already net of cost and per unit notional, so this is scale-invariant across
BTC (~10M JPY) / ETH (~250k) / XRP (~200) — the only honest way to combine them.

Objective: **yearly-return stability**. Reported per weighting: yearly returns,
worst year, stdev, %positive, and yearly Sharpe (mean/stdev). The fitted maximin
weight is a DIAGNOSTIC (≈5 yearly obs overfits); the robust recommendation is the
simple equal-risk split.

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.portfolio_combine
"""

from __future__ import annotations

from itertools import product as iproduct

import numpy as np

from src.core.types import Bar, Timeframe, Trade
from src.data.cache import load_cache
from src.simulator import MultiSimulator
from src.strategy.registry import get_strategy

BOOKS: list[tuple[str, str]] = [
    ("combo_dp_ver", "GMO_BTC_JPY"),
    ("density_pullback_eth", "GMO_ETH_JPY"),
    ("density_pullback_xrp", "GMO_XRP_JPY"),
]
# Capital-efficient slot caps (PnL saturation point from the slot-efficiency sweep:
# combo 98% of PnL at 6, eth saturates by 4 / peak-occ 6, xrp 97% at 6). Running at
# these instead of 12 ~doubles-to-triples return-on-capital with <3% PnL given up.
EFFICIENT_SLOTS: dict[str, int] = {
    "combo_dp_ver": 6,
    "density_pullback_eth": 4,
    "density_pullback_xrp": 6,
}
YEARS = [2021, 2022, 2023, 2024, 2025, 2026]  # 2021/2026 partial


def _peak_concurrency(trades: list[Trade]) -> int:
    """Max simultaneous open positions over the trade event path."""
    if not trades:
        return 1
    ev = sorted([(t.entry_time, 1) for t in trades] + [(t.exit_time, -1) for t in trades])
    cur = mx = 0
    for _, d in ev:
        cur += d
        mx = max(mx, cur)
    return max(mx, 1)


def _yearly_returns(trades: list[Trade], peak: int) -> dict[int, float]:
    """Return-on-required-capital per calendar year (sum net trade returns / peak)."""
    out: dict[int, float] = {y: 0.0 for y in YEARS}
    for t in trades:
        y = t.exit_time.year
        if y in out:
            out[y] += t.return_pct
    return {y: v / peak for y, v in out.items()}


def _stats(yearly: np.ndarray, full_years: np.ndarray) -> dict[str, float]:
    """Stability metrics over the FULL (non-partial) calendar years."""
    fy = yearly[full_years]
    return {
        "mean": float(fy.mean()),
        "stdev": float(fy.std(ddof=1)),
        "worst": float(fy.min()),
        "pos_frac": float((fy > 0).mean()),
        "ysharpe": float(fy.mean() / fy.std(ddof=1)) if fy.std(ddof=1) > 0 else 0.0,
    }


def main() -> None:
    """Compute per-book yearly returns and combine for stability."""
    yr: dict[str, dict[int, float]] = {}
    print("=== per-book yearly return-on-capital (at capital-efficient slot caps) ===")
    for name, prod in BOOKS:
        bars: list[Bar] = load_cache(Timeframe("1h"), product=prod).bars
        strat = get_strategy(name)
        cap = EFFICIENT_SLOTS[name]
        strat.max_slots = cap  # capital-efficient slot cap (return on REQUIRED capital)
        res = MultiSimulator(strat, size=0.001).run(bars)
        peak = _peak_concurrency(res.trades)  # = cap (binding)
        yr[name] = _yearly_returns(res.trades, peak)
        ys = " ".join(f"{yr[name][y]:+.2f}" for y in YEARS)
        print(f"  {name:22} slots={cap:2} (peak {peak})  n={len(res.trades):4}  "
              f"yearly[{','.join(map(str, YEARS))}] = {ys}")

    names = [b[0] for b in BOOKS]
    # full (non-partial) years = those where every book traded a meaningful set; 2021
    # starts mid-April and 2026 is ~5 months -> treat 2022-2025 as the full years.
    full_mask = np.array([y in (2022, 2023, 2024, 2025) for y in YEARS])
    M = np.array([[yr[n][y] for y in YEARS] for n in names])  # books x years

    print("\n=== cross-book yearly-return correlation (full years) ===")
    C = np.corrcoef(M[:, full_mask])
    for i, n in enumerate(names):
        print(f"  {n:22} " + " ".join(f"{C[i, j]:+.2f}" for j in range(len(names))))

    def report(w: np.ndarray, label: str) -> dict[str, float]:
        port = w @ M  # portfolio yearly return-on-capital
        st = _stats(port, full_mask)
        ys = " ".join(f"{port[k]:+.2f}" for k in range(len(YEARS)))
        print(f"  {label:24} w={np.round(w, 2)}  yearly={ys}")
        print(f"  {'':24} worst={st['worst']:+.2f} stdev={st['stdev']:.2f} "
              f"pos={st['pos_frac']:.0%} ySharpe={st['ysharpe']:+.2f} mean={st['mean']:+.2f}")
        return st

    print("\n=== weightings (full-year stability) ===")
    n_b = len(names)
    report(np.ones(n_b) / n_b, "equal-capital (1/3)")
    # inverse-vol (full-year stdev) weights
    vols = np.array([M[i, full_mask].std(ddof=1) for i in range(n_b)])
    iv = (1 / vols) / (1 / vols).sum()
    report(iv, "inverse-vol")
    # maximin-stability grid search (DIAGNOSTIC — overfits ~4 obs)
    grid = [np.array(w) / 20 for w in iproduct(range(21), repeat=n_b) if sum(w) == 20]
    best = max(grid, key=lambda w: _stats(w @ M, full_mask)["worst"])
    report(best, "maximin-worst (fitted*)")
    best_ys = max(grid, key=lambda w: _stats(w @ M, full_mask)["ysharpe"])
    report(best_ys, "max-ySharpe (fitted*)")
    print("  * fitted weights overfit ~4 yearly obs — diagnostics, not a recommendation.")

    # Robust recommendations: anchored on the STRUCTURAL findings, not the 4-obs fit.
    # ETH is yearly-redundant with BTC (corr ~0.98) -> satellite or dropped. XRP is the
    # only diversifier (the steady book) -> stability-first tilts toward it; combo is the
    # strongest but LUMPY (2024-loaded) -> moderate it for stability. Concentration in
    # XRP is capped (its backtest steadiness may be window-luck — forward-risk).
    print("\n=== ROBUST RECOMMENDATIONS (structural, stability-first) ===")
    report(np.array([0.45, 0.0, 0.55]), "2-book  BTC45 / XRP55")
    report(np.array([0.35, 0.15, 0.50]), "3-book  BTC35 / ETH15 / XRP50")


if __name__ == "__main__":
    from src.config import get_settings
    from src.logging_setup import configure_logging

    configure_logging(get_settings().log_level)
    main()
