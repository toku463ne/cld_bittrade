# Candidate benchmark table

At-a-glance comparison of the multi-position strategy candidates, all on **one consistent
basis** (snapshot **2026-06-07**, GMO_BTC_JPY 1h):

- **Split:** the fixed **lockbox** (`split_lockbox`) — IS = pre-2025-04-01, OOS =
  2025-04-01 → 2026-04-01.
- **IS / OOS Sharpe** = annualised mark-to-market **equity** Sharpe at the default **4 bp**
  round-trip cost. **OOS@10bp** = OOS equity Sharpe at a realistic **10 bp** round-trip —
  the cost-robustness check (the recurring edge-killer on this branch).
- **DR** = win rate, **mean_r** = mean net return per trade (both signal-level diagnostics,
  *not* ship criteria). **IS_DD / OOS_DD** = max drawdown of the per-trade-return curve.
- **WF** = fixed-config 6-fold walk-forward (full series, 4 bp); folds with positive eqSharpe.
- **cBTC / cDP** = bar-return correlation to BTC / to density_pullback — *diagnostics for the
  later combination stage, not idea-stage gates*.
- **Benchmark:** B&H lockbox Sharpe **IS +0.55 / OOS −0.16** (so OOS@10bp clears B&H if > −0.16).

| candidate | n | IS_sh | DR | IS_DD | mean_r | OOS_sh | OOS_DD | OOS@10bp | WF | cBTC | cDP | status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **density_pullback** | 428 | **+1.39** | 0.36 | **0.34** | +0.0048 | +1.11 | 0.15 | +0.90 | **6/6** | +0.04 | +1.00 | ship✓ |
| **vol_expansion_ride** | 526 | **+1.56** | 0.21 | 0.41 | +0.0034 | +1.27 | 0.12 | +0.99 | 4/6 | −0.04 | +0.16 | candidate |
| **rsi_extreme_ride** | 1001 | +1.33 | 0.34 | 0.69 | +0.0044 | +0.88 | 0.44 | +0.62 | **6/6** | −0.19 | +0.15 | candidate |
| **random_hedge_volfilter** | 518 | +0.98 | 0.36 | **0.27** | +0.0028 | **+1.69** | 0.09 | **+1.34** | **6/6** | −0.09 | +0.15 | near-miss* |
| **zigzag_bounce_ride** | 564 | +0.32 | 0.39 | 0.71 | +0.0029 | +1.05 | 0.38 | +0.86 | **6/6** | −0.08 | +0.17 | candidate |
| **density_multi_breakout** | 439 | +1.03 | 0.40 | 0.56 | +0.0063 | +0.32 | 0.42 | +0.20 | 5/6 | +0.03 | +0.68 | weak (cost) |
| random_hedge (null) | 684 | −0.15 | 0.37 | 0.70 | −0.0006 | +0.55 | 0.12 | +0.08 | 4/6 | +0.03 | +0.14 | null baseline |

\* `random_hedge_volfilter` (and the `random_hedge` null) are **seeded** (seed=0); their
single-seed lockbox numbers are rosier than the 8-seed mean — treat as indicative, not final.
All others are deterministic.

## Read at a glance

- **All six candidates beat B&H** (IS +0.55 / OOS −0.16) in both splits and stay positive at
  a realistic 10 bp — the bar that killed grid / BCH / 15m-5m density.
- **density_pullback** is the most balanced and only *shipped* one: strong both splits, **lowest
  DD among the strong (0.34), 6/6 folds**.
- **vol_expansion_ride** has the **highest IS (+1.56)** and a strong cost-robust OOS (+0.99), but
  only 4/6 folds (weak in raging bulls).
- **rsi_extreme_ride** and **zigzag_bounce_ride** are **6/6 folds** but carry higher DD (0.69 /
  0.71); rsi's OOS is more cost-sensitive (+0.62).
- **random_hedge_volfilter** *looks* best on this split (OOS +1.69, DD 0.27, +1.34 @10bp) but it
  is seed-0 and OOS-lucky — the 8-seed mean is far more modest; do not over-read it.
- **density_multi_breakout** is the weakest: OOS only +0.32 and **not cost-robust** (+0.20 @10bp),
  plus the highest density correlation (cDP 0.68).
- **DR is sub-0.5 for all** (trend-ride payoff — few big winners; vol_expansion is the extreme at
  0.21). Per CLAUDE.md, DR/mean_r are diagnostics only.

## Caveats & regeneration

A lockbox snapshot, not a final verdict — the lockbox has been reused across ideas (erodes it),
so the **finalist still needs a fresh live-forward** (`paper_forward`) before real capital. Single
IS/OOS split + 6 coarse folds; ride-exit candidates share the same exit (correlations in `cDP`).
Regenerate by re-running the metric script against `split_lockbox` for each registered strategy.
