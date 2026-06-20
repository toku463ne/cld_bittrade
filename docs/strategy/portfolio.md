# Multi-asset portfolio of the shipped books (2026-06-11; honest-fill refresh 2026-06-20)

Combining the promotable books for **yearly-return stability**. They trade different
instruments, so slots cannot be shared across them (only the BTC dp+ver pair shares slots,
folded into `combo_dp_ver`). Analysis: `src/backtest/analysis/portfolio_combine.py`
(+ the slot-efficiency sweep in its docstring). Normalization = **return on required
capital** = Σ(net per-trade returns) / peak concurrency — scale-invariant across BTC (~10M
JPY) / ETH (~250k) / XRP (~200), the only honest way to combine them.

> **2026-06-20 — all numbers below regenerated on honest fills.** The trail ratchet was
> booking exits at a stale stop level the bar never traded at (recalc-jump phantom fill;
> see `trail-recalc-phantom-fill`). The fix (`random_hedge.py`, commit 9bdbcd4) cut every
> ride book's Sharpe 25–50%. The headline portfolio numbers fell accordingly and **the live
> BTC book was switched `combo_dp_ver` → `density_pullback`** (head-to-head below). The
> structural findings (ETH redundant, XRP the diversifier) survive unchanged.

## The two structural findings (robust, mechanism-backed)

1. **ETH is yearly-redundant with BTC** — cross-book yearly-return correlation **+0.99**.
   Both are `density_pullback` on co-moving crypto; holding both adds capital without
   diversification. ETH is a satellite, not a third leg.
2. **XRP is the only diversifier** (corr **~0.5** to the BTC/ETH books) **and the steadiest
   book** — positive every full year, never the deep-loss book. It is the stability anchor.

## Slot number = required capital (the first lever)

PnL **saturates early** — running 12 slots wastes 2–3× the capital:

| book | slots for ~full PnL | peak occupancy (12-slot run) |
|---|---|---|
| combo_dp_ver | **6** (98% of PnL; 89% at 4) | 11 |
| density_pullback | **6** (99% of PnL; 87% at 4) | 10 |
| density_pullback_eth | **4** (99% of PnL; saturates by 4) | 6 |
| density_pullback_xrp | **6** (99% of PnL; 94% at 4) | 8 |

Use **6 / 4 / 6** (BTC / ETH / XRP). This ~doubles-to-triples return-on-capital for ≤1% PnL
given up vs the saturation point.

## Per-book yearly return-on-capital (efficient slots, honest fills)

| book (slots) | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|
| combo_dp_ver (6) | +0.02 | +0.06 | **+0.32** | +0.08 |
| density_pullback (6) | +0.01 | +0.05 | **+0.24** | +0.07 |
| density_pullback_eth (4) | −0.03 | −0.00 | +0.17 | +0.04 |
| density_pullback_xrp (6) | +0.05 | +0.02 | +0.06 | +0.04 |

Both BTC books are **lumpy** (2024-loaded); XRP is flat-and-steady. Note that `combo`'s only
lift over plain `density_pullback` (≈ +0.01 / +0.01 / +0.08 / +0.01 by year) is the
`vol_expansion_ride` leg, and it lands almost entirely in 2024 — see the head-to-head.

## BTC book: `combo_dp_ver` vs `density_pullback` (head-to-head, honest fills)

The `combo` book was adopted on the premise that its `vol_expansion_ride` leg diversifies
`density_pullback`'s weak folds for free (shared slots, zero contention). On honest fills
that premise no longer holds: `vol_expansion_ride` is OOS-dead/OVERFIT (standalone OOS equity
Sharpe ≈ 0.005), and its marginal contribution is concentrated in 2024, not the 2022/2023
folds it was meant to cover.

| | combo_dp_ver | density_pullback |
|---|---|---|
| IS / OOS equity Sharpe (cycle, vs B&H 0.64 / −0.85) | 1.37 / 0.37 | 1.23 / 0.40 |
| Capital efficiency (6 slots) | 875 tr, ROC 4682/slot | 568 tr, ROC 3817/slot |
| BTC45/XRP55 portfolio ySharpe | 1.17 | **1.29** |
| …stdev / worst year | 0.07 / +0.04 | **0.05 / +0.03** |
| Mechanisms | 2 | **1** |

`combo` earns ~23% more PnL on the same capital, but it buys that almost entirely from the
OOS-dead leg and at the cost of lumpiness — so the *risk-adjusted* portfolio is better with
plain `density_pullback`. **Decision (2026-06-20): the live BTC book is `density_pullback`.**

## Slot size = capital weights (the second lever)

Weights are **capital fractions** (achieving them needs per-asset lot sizing — XRP/ETH lots
scale up vs BTC's 0.001 minimum to deploy equal JPY). Full-year (2022–25) stability, **BTC book
= `density_pullback`** (`mean` = simple average of the four full-year return-on-capital figures,
not compounded):

| weighting (BTC/ETH/XRP) | worst yr | stdev | ySharpe | mean | note |
|---|---|---|---|---|---|
| equal 1/3 | +0.01 | 0.07 | 0.90 | +0.06 | ETH drags; 2024 spike adds variance |
| **2-book 45/0/55** | **+0.03** | 0.05 | **1.29** | +0.07 | **recommended — drops redundant ETH** |
| 3-book 35/15/50 | +0.02 | 0.05 | 1.14 | +0.06 | ETH satellite (optional, lowers ySharpe) |
| inverse-vol 11/13/76 | +0.02 | 0.03 | 1.60 | +0.05 | most stable, but XRP-concentrated |
| max-ySharpe (fitted) | +0.02 | 0.02 | 2.85 | +0.04 | = XRP-only; overfits 4 obs |

**Recommendation: BTC 45% `density_pullback` / XRP 55% `density_pullback_xrp`, ETH dropped (or
≤15% satellite), each at its efficient slot count.** Positive every full year (worst +0.03
return-on-capital), mean ~+0.07/yr, ySharpe 1.29. Tilting further to XRP (inverse-vol) raises
ySharpe to ~1.60 but concentrates in one asset.

## JPY view — concrete yen (honest fills, equal 6/6 slots = 50/50 capital)

Re-run in **absolute JPY** at a fixed **10,000 JPY notional per slot**, efficient slots
(full-year 2022–25 stats; `pnl` over the ~5.1yr sample):

| portfolio | capital | worst yr | stdev | ySharpe | mean/yr | 5.1yr PnL |
|---|---|---|---|---|---|---|
| **density_pullback(6) + xrp(6)** | 120k | **+3.0%** | 5.5% | **1.23** | +6.8% | +36.9k |
| combo_dp_ver(6) + xrp(6) | 120k | +3.4% | 7.2% | 1.12 | +8.0% | +43.5k |
| combo(6) + eth(4) + xrp(6) | 160k | +1.7% | 7.6% | 0.94 | +7.1% | +53.0k |
| dp(6) + eth(4) + xrp(6) | 160k | +1.4% | 6.3% | 0.97 | +6.2% | +46.5k |

1. **`density_pullback` over `combo` for the BTC book** holds in yen: `combo` earns more
   absolute PnL (+43.5k vs +36.9k) but at a lower ySharpe (1.12 vs 1.23) and higher year-to-
   year variance (7.2% vs 5.5%) — return bought with lumpiness, from the OOS-dead leg.
2. **Adding `density_pullback_eth` does not help risk-adjusted stability.** It lifts absolute
   PnL but needs +40k capital and lowers ySharpe (dp+xrp 1.23 → dp+eth+xrp 0.97), because
   ETH's yearly return is ~+0.99 correlated with the BTC book — a near-duplicate that dilutes
   rather than diversifies. Confirms the redundancy finding in yen.

Net: the JPY-optimal book is **`density_pullback` + `density_pullback_xrp`** (the 2-book
BTC/XRP above), tilted toward XRP for stability. (Lot caveat: at 10k/slot the BTC lot came to
~0.00156, above the 0.001 minimum — in live trading BTC's JPY/slot floats with price.)

## Caveats (do not over-trust the weights)

- **Honest-fill basis (2026-06-20):** all figures use the realisable trail fill. The earlier
  version of this doc (phantom fills) overstated every Sharpe/return by 25–50% and recommended
  `combo` for the BTC book; superseded.
- **~4 full yearly observations** — the *fitted* maximin/max-ySharpe weights (which pile into
  XRP and zero ETH) overfit; they are diagnostics. The 45/55 split is a judgment anchored on
  the two structural findings, not the fit.
- **XRP's steadiness may be window-luck** — it is the best single book *on this backtest*; the
  ≤55% cap limits the damage if its forward edge degrades. Don't go XRP-only.
- **All books are still forward-ACCRUING** (no CONFIRMED live record yet). The weights are a
  backtest construction; size only after the forwards confirm.
- Min-lot 0.001 BTC sets the smallest chunk (~6 slots × 0.001 × price); the portfolio minimum
  capital follows from that.
