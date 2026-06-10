# Shared book: `density_pullback` + `vol_expansion_ride` (12 slots)

**2026-06-10 probe** (`src/backtest/analysis/combo_dp_ver_probe.py`): run both shipped
strategies' signal streams through **one 12-slot book** — the same peak-capital budget as
`density_pullback` alone. Rationale: dp rarely fills its book (IS occupancy mean 1.66,
p95 4.9, max 10), ver is low-turnover (IS mean 0.68, max 4), and their correlation is low
(cDP +0.10) — so the merged book should raise slot utilisation and smooth the path, unless
contention costs more than diversification pays.

Mechanically exact: both strategies use the identical inherited ride-exit machinery
(`RandomHedgeStrategy.dynamic_exit` ratchet, `recalc_bars=48`; the trail band is
per-position via each signal's `exit_config`), so the merged book reproduces each
strategy's exits bar-for-bar. No parameter was tuned for this probe — it composes two
already-shipped configs, so selection risk is minimal.

## Result (GMO 1h, 80/20 split, calm cost)

| arm | IS eqSh | OOS eqSh | IS DD | n IS | IS occupancy (max/p95/mean) | consistency | WF |
|---|---|---|---|---|---|---|---|
| dp alone (12 slots) | +1.50 | +0.95 | 0.47 | 451 | 10 / 4.9 / 1.66 | 80% | 6/6, mean +1.18 |
| ver alone (uncapped) | +1.46 | +0.82 | 0.26 | 247 | 4 / 2.0 / 0.68 | 82% | 5/6, mean +1.16 |
| **combo (shared 12)** | **+1.92** | **+1.16** | 0.48 | **698** | **11** / 4.0 / 1.53 | **94%** | **6/6, mean +1.62** |
| sum-of-books control | +1.92 | +1.16 | 0.48 | 698 | (uses more slots) | 94% | — |

- **Zero slot contention**: 0 of 698 IS trades dropped; combined peak occupancy is 11 ≤ 12.
  The shared book equals the sum-of-separate-books control on every metric while holding
  the peak-capital budget at dp's existing 12 slots (peak 11 vs dp's own 10).
- **The weak folds are complementary** — the heart of the win: dp's worst fold is f2
  (+0.09, 2022 bear) where ver posts +1.58; ver's worst is f3 (−0.72, 2023 bull) where dp
  posts +0.67. Combo folds: `+1.10 +0.90 +0.53 +4.00 +2.46 +0.72` — its minimum fold
  (+0.53) is far above either component's minimum.
- **Quarterly consistency 94%** (vs 80/82% alone, B&H 62%) — the "more stability" goal.
  Absolute DD is flat (~0.48 of one-slot notional) while the book earns ~+55% more trades
  and +0.42 IS Sharpe, so return/DD improves materially.

## Caveats / live notes

- Peak occupancy 11 of 12 leaves only 1 slot of headroom historically; a future overlap
  burst could contend. Acceptable: contention drops a *new entry*, never an open position.
- Pre-existing (not combo-specific): the ratchet keys trail state by `(entry_idx, side)`,
  so two same-bar same-side fills share trail state; the merge adds rare cross-strategy
  occurrences of an artifact dp already has internally.
- This satisfies the CLAUDE.md portfolio-level correlation requirement for running both
  live (corr +0.10, fold-complementary), **per-strategy minimum lot still applies**.
- Numbers are the calm cost basis; both components individually survive
  `--bitflyer-realistic` (dp IS 1.31/OOS 0.58; ver IS 1.28/OOS 0.47), and the combo's
  costs are additive (same trades), so realistic-basis survival follows.
- The live-forward should track the **combined book** going forward, since that is what
  would trade; the per-strategy forwards remain the per-edge confirmations.
