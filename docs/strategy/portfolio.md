# Multi-asset portfolio of the shipped books (2026-06-11)

Combining the three promotable books for **yearly-return stability**. They trade different
instruments, so slots cannot be shared across them (only the BTC dp+ver pair shares slots,
already folded into `combo_dp_ver`). Analysis: `src/backtest/analysis/portfolio_combine.py`
(+ the slot-efficiency sweep in its docstring). Normalization = **return on required
capital** = Σ(net per-trade returns) / peak concurrency — scale-invariant across BTC (~10M
JPY) / ETH (~250k) / XRP (~200), the only honest way to combine them.

## The two structural findings (robust, mechanism-backed)

1. **ETH is yearly-redundant with BTC** — cross-book yearly-return correlation **+0.98**.
   Both are `density_pullback` on co-moving crypto; holding both adds capital without
   diversification. ETH is a satellite, not a third leg.
2. **XRP is the only diversifier** (corr **~0.4** to the BTC/ETH books) **and the steadiest
   book** — positive every full year, strongest in 2022/2023 when BTC/ETH are weak. It is
   the stability anchor.

## Slot number = required capital (the first lever)

PnL **saturates early** — running 12 slots wastes 2–3× the capital:

| book | slots for ~full PnL | 12-slot waste |
|---|---|---|
| combo_dp_ver | **6** (98% of PnL; 95% at 4) | peak occ 11 |
| density_pullback_eth | **4** (saturates by 4; peak occ 6) | 2× |
| density_pullback_xrp | **6** (97%; peak occ 8) | 2× |

Use **combo 6 / eth 4 / xrp 6**. This ~doubles-to-triples return-on-capital for <3% PnL
given up (e.g. combo 2024 return-on-capital +0.23 at 11 slots → **+0.42** at 6).

## Per-book yearly return-on-capital (efficient slots)

| book (slots) | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|
| combo_dp_ver (6) | +0.06 | +0.11 | **+0.42** | +0.15 |
| density_pullback_eth (4) | −0.01 | +0.04 | +0.19 | +0.07 |
| density_pullback_xrp (6) | +0.09 | +0.13 | +0.13 | +0.06 |

combo is the highest-return but **lumpy** (2024-loaded); XRP is flat-and-steady.

## Slot size = capital weights (the second lever)

Weights are **capital fractions** (achieving them needs per-asset lot sizing — XRP/ETH lots
scale up vs BTC's 0.001 minimum to deploy equal JPY). Full-year (2022–25) stability
(**`mean`** = simple arithmetic average of the four full-year return-on-capital figures —
2022–2025, partial 2021/2026 excluded; not compounded/CAGR):

| weighting (BTC/ETH/XRP) | worst yr | stdev | ySharpe | mean | note |
|---|---|---|---|---|---|
| equal 1/3 | +0.04 | 0.09 | 1.37 | +0.12 | combo's 2024 spike lifts mean, adds variance |
| **2-book 45/0/55** | **+0.08** | 0.08 | **1.68** | **+0.14** | **recommended — drops redundant ETH** |
| 3-book 35/15/50 | +0.06 | 0.08 | 1.62 | +0.13 | ETH satellite (optional) |
| inverse-vol 13/24/63 | +0.06 | 0.05 | 1.96 | +0.10 | most stable, but XRP-concentrated |
| max-ySharpe (fitted) | +0.06 | 0.03 | 3.06 | +0.10 | = XRP-only; overfits 4 obs |

**Recommendation: BTC 45% / XRP 55%, ETH dropped (or ≤15% satellite), each at its efficient
slot count.** Positive every full year (worst +0.08 return-on-capital), mean ~+0.14/yr,
ySharpe 1.68. Tilting further to XRP (inverse-vol) raises ySharpe to ~1.96 but concentrates
in one asset.

## JPY view (2026-06-11) — concrete yen, and two confirmations

Re-run in **absolute JPY** at a fixed **10,000 JPY notional per slot** (= BTC's 0.001 min lot at
~10M; each asset's lot set to match), efficient slots. This confirms the return-on-capital story
in real money and settles two practical questions:

| portfolio | capital | worst yr | stdev | ySharpe | mean/yr | 5.1yr PnL |
|---|---|---|---|---|---|---|
| **combo_dp_ver(6) + xrp(6)** | 120k | **+6.6%** | 15.0% | **1.46** | +21.9% | **+133k** |
| dp(6)+ver(4)+xrp(6) *separate* | 160k | +5.2% | 11.2% | 1.46 | +16.4% | +133k |
| combo(6) + **eth(4)** + xrp(6) | 160k | +4.7% | 14.8% | 1.31 | +19.3% | +155k |

1. **Hold dp+ver as `combo_dp_ver` (shared BTC slots), NOT as separate books.** The separate
   trio produces the *identical* +133k JPY but on 160k capital vs the combo's 120k — sharing
   slots saves 25% of capital for zero return (the slot-sharing efficiency, in yen).
2. **Adding `density_pullback_eth` does not help yearly stability.** It adds +22k absolute PnL
   but needs +40k capital (return-on-capital 21.9%→19.3%), and **lowers risk-adjusted
   stability** (ySharpe 1.46→1.31, worst year +6.6%→+4.7%). ETH's yearly return is **+0.90
   correlated** with the combo+xrp book — a near-duplicate of the BTC exposure, so it dilutes
   rather than diversifies. Confirms the corr-+0.98 redundancy finding above, in JPY.

Net: the JPY-optimal book is **`combo_dp_ver` + `density_pullback_xrp`** (the 2-book BTC/XRP
above), tilted toward XRP for stability. (Lot caveat: at 10k/slot the BTC lot came to ~0.00156,
above the 0.001 minimum — in live trading BTC's JPY/slot floats with price.)

## Caveats (do not over-trust the weights)

- **~4 full yearly observations** — the *fitted* maximin/max-ySharpe weights (which pile into
  XRP and zero ETH) overfit; they are diagnostics. The 45/55 split is a judgment anchored on
  the two structural findings, not the fit.
- **XRP's steadiness may be window-luck** — it is the best single book *on this backtest*; the
  ≤55% cap limits the damage if its forward edge degrades. Don't go XRP-only.
- **All books are still forward-ACCRUING** (no CONFIRMED live record yet; earliest ~mid-Aug
  2026). The weights are a backtest construction; size only after the forwards confirm.
- Min-lot 0.001 BTC sets the smallest combo chunk (~6 slots × 0.001 × price); the portfolio
  minimum capital follows from that.
