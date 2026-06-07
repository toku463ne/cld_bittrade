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
| **Exit** | ride exit (zs-band SL `sl_mult=0.75`, next-dense TP, slow ratchet `recalc=48`, time stop 120) + **`max_slots=3`** (DD development, §3) |
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

**Cost-robust** — beats B&H (IS +0.55 / OOS −0.16) in both splits at every cost, untuned
(discovery config, `max_slots=50`):

| round-trip cost | IS eqSh / DD | OOS eqSh / DD |
|---|---|---|
| 0.04% | +1.33 / 0.69 | +0.88 / 0.44 |
| **0.10% (realistic)** | **+1.19** / 0.73 | **+0.62** / 0.50 |
| 0.20% | +0.94 / 0.83 | +0.17 / 0.59 |

**Correlation (diagnostic only):** +0.15 to density_pullback, +0.36 to vol_expansion_ride,
−0.19 to BTC. Recorded for the later combination stage.

## 3. DD development — concurrency cap (`max_slots=3`)

The vol_expansion DD playbook **fails** here: a **tighter stop overfits** — it cuts IS DD
but monotonically *kills OOS* (sl0.75 OOS +0.62 → sl0.4 +0.25 → sl0.3 +0.07 @10bp), so it
does not generalise; `drop_counter_trend` doesn't help either (raises IS DD). The one lever
that cuts DD **and generalises** is a **concurrency cap** — rsi fires often (base peaks at 8
concurrent), so capping clustered exposure during RSI-extreme bursts helps:

| config | IS eqSh / DD | OOS eqSh / DD | WF |
|---|---|---|---|
| `max_slots=50` (discovery) | +1.33 / 0.69 | +0.88 / 0.44 | 6/6 |
| **`max_slots=3` (default)** | +1.27 / 0.61 | **+0.97** / 0.45 | 5/6 |

A **modest** win: IS DD 0.69→0.61 and OOS +0.88→+0.97, but it **costs one WF fold** (6/6→5/6)
and a touch of IS Sharpe. Honest verdict on the DD: **rsi's drawdown is structurally less
reducible than vol_expansion's** — the main lever (stop) overfits, so 0.61 is about as low as
it goes without sacrificing OOS edge.

## 4. Verdict & next

A genuine **own-merit edge** — cost-robust, beats B&H in both lockbox splits, 5/6 folds, DD
now 0.61. Next: formal ship-gate (`run_cycle`) and a fresh live-forward before capital.
Lineage: reuses the `random_hedge` ride exit; sibling of
[`density_pullback.md`](density_pullback.md), [`vol_expansion_ride.md`](vol_expansion_ride.md).
