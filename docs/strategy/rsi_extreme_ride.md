# Strategy: `rsi_extreme_ride` (RSI extreme as continuation)

Idea-stage **hit** — the strongest walk-forward robustness of any new idea on the branch.
We set out to probe RSI/BB **reversal** (fade extremes); that lost. The direction flip is
the edge: on 1h BTC an **RSI extreme is a continuation signal**, not a reversion one.

| | |
|---|---|
| **Name** | `rsi_extreme_ride` |
| **Class** | `src/strategy/rsi_extreme_ride.py` → `RsiExtremeRideStrategy` (subclasses `RandomHedgeStrategy`) |
| **Simulator** | `MultiSimulator` |
| **Entry** | RSI(14) crosses **into oversold → SHORT**, **into overbought → LONG** (continuation; one per excursion). `reversal=True` = the rejected fade variant. |
| **Exit** | ride exit (zs-band SL `sl_mult=0.75`, next-dense TP, slow ratchet `recalc=48`, time stop 120) — inherited |
| **Default timeframe** | **1h** |
| **Status** | **idea-stage candidate** (own-merit pass). Cost-robust, beats B&H both lockbox splits, **5/6 walk-forward folds**. Not yet ship-gated / forward-checked. |

---

## 1. The flip (reversal → continuation)

Mean-reversion (fade oversold/overbought) **lost** — IS −0.25 / OOS −0.45 even at 4 bp,
below B&H — because on 1h BTC extremes tend to *continue*, and a continuation ride-exit is
mismatched with a reversion entry. Flipping the side (oversold → short, overbought → long)
turns it into a momentum/continuation entry, which carries the edge. (Same lesson as the
BCH ratio: the *direction* of the premise was the bug, not the signal.)

## 2. Results (idea-stage, lockbox OOS 2025-04 → 2026-04, own merit)

**Cost-robust** — beats B&H (IS +0.55 / OOS −0.16) in both splits at every cost, untuned:

| round-trip cost | IS eqSh / DD | OOS eqSh / DD |
|---|---|---|
| 0.04% | +1.33 / 0.69 | +0.88 / 0.44 |
| **0.10% (realistic)** | **+1.19** / 0.73 | **+0.62** / 0.50 |
| 0.20% | +0.94 / 0.83 | +0.17 / 0.59 |

**Walk-forward (fixed config, 6 folds): 5/6 positive** — the only miss is fold 1
(−0.10, essentially flat, where B&H was −0.95). Strong in 2023-24 and the 2025 bear
(+1.41 vs B&H −1.37). The best new-idea fold robustness on the branch.

**Correlation (diagnostic only — not a gate at the idea stage):** +0.15 to
density_pullback, +0.36 to vol_expansion_ride, −0.19 to BTC. Recorded for the later
combination stage.

## 3. Verdict & next

A genuine **own-merit edge** — cost-robust, beats B&H in both lockbox splits untuned,
5/6 folds, moderate DD (0.7). Stronger fold-robustness than vol_expansion_ride (5/6 vs
4/6). Next: formal ship-gate (`run_cycle`) and a fresh live-forward before capital; the DD
(~0.7) is an optional development target (the `sl_mult` / `drop_counter_trend` levers that
helped vol_expansion_ride are available). Lineage: reuses the `random_hedge` ride exit;
sibling of [`density_pullback.md`](density_pullback.md), [`vol_expansion_ride.md`](vol_expansion_ride.md).
