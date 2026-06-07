# Strategy: `vol_expansion_ride` (squeeze→expansion ride)

Idea-stage **hit** (Strategy idea #2) — the first *new* candidate on this branch to clear
the lockbox triage, and a genuine diversifier alongside `density_pullback`. After the
whole branch's lesson that **turnover cost kills edges** (grid, BCH 2-leg, 15m/5m density
all died on it), this targets a deliberately **low-frequency, cost-light** trigger.

| | |
|---|---|
| **Name** | `vol_expansion_ride` |
| **Class** | `src/strategy/vol_expansion_ride.py` → `VolExpansionRideStrategy` (subclasses `RandomHedgeStrategy`) |
| **Simulator** | `MultiSimulator` |
| **Entry** | volatility **squeeze→expansion**: prior ATR in its low tail (rank ≤ 0.25) and a true-range burst (TR ≥ 2× prior ATR) → ride the burst bar's direction (market, next open) |
| **Exit** | tuned ride exit (zs-band SL `sl_mult=0.75`, next-dense TP, slow ratchet `recalc=48`, time stop 120) — inherited |
| **Default timeframe** | **1h** |
| **Status** | **idea-stage candidate** (not yet ship-gated/forward-checked). Clears lockbox triage but has a high drawdown and 2 weak folds. See §2. |

---

## 1. Hypothesis

A volatility squeeze (compressed ATR) that resolves into an expansion (a true-range
burst) often starts a directional move; ride that direction with the dense-aware ride
exit. Squeeze→expansion is rare → few trades → cost-light, the opposite of the 15m/5m
density probe that died on turnover.

## 2. Results (idea-stage, fixed lockbox OOS 2025-04 → 2026-04)

**Cost-robust** — beats B&H (IS +0.55 / OOS −0.16) in both splits at every cost level,
on **untuned defaults**:

| round-trip cost | IS eqSh | OOS eqSh | trades |
|---|---|---|---|
| 0.04% | +1.12 | +1.18 | 803 |
| **0.10% (realistic)** | **+0.92** | **+0.92** | 803 |
| 0.20% | +0.58 | +0.48 | 803 |

**Diversifier:** bar-return correlation **+0.20 to density_pullback**, **−0.05 to BTC**
(< 0.30 → genuinely different edge, not a density-cousin).

**Walk-forward (fixed config, 6 folds): 4/6 positive** — strong in the 2023-24 bull
(+3.10) and both recent bears (beats falling B&H), but **negative in 2 folds**: early
2021 (−1.26, DD 0.99) and the 2023 raging bull (−0.96, expansions get chopped). **Main
caveat: high drawdown** (full-lockbox DD 1.15, vs density_pullback's 0.34) — entries live
in high-vol regimes.

## 3. Verdict & next

A real **2nd-strategy candidate** — cost-robust, diversifying, beats B&H both splits
untuned — but not a slam dunk (high DD, 2 weak folds). Promotion path: formal ship-gate
(`run_cycle`), address the drawdown (sizing / tighter stop / a vol-target overlay), and a
fresh live-forward before capital. Lineage: reuses the `random_hedge` ride exit; sibling
of [`density_pullback.md`](density_pullback.md).
