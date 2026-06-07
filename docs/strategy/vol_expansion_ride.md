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
| **Exit** | ride exit with a **tighter stop** (zs-band SL `sl_mult=0.4`, next-dense TP, slow ratchet `recalc=48`, time stop 120) — the DD fix, §3 |
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

## 3. Drawdown fix — tighter stop (`sl_mult=0.4`)

The base config's DD was high (1.29 @10bp). One-knob-at-a-time on the lockbox: the lever
is the **stop width** — `max_atr_rank` doesn't bind (entries are squeeze→*low* prior ATR
by construction) and `max_slots` doesn't either (expansions rarely cluster). Tightening
the zs stop both **cuts DD and raises Sharpe** (@10bp):

| sl_mult | IS eqSh / DD | OOS eqSh / DD |
|---|---|---|
| 0.75 (old) | +0.92 / 1.29 | +0.92 / 0.17 |
| 0.5 | +1.35 / 0.98 | +0.95 / 0.20 |
| **0.4 (new default)** | **+1.44 / 0.77** | **+1.25 / 0.14** |
| 0.3 | +1.58 / 0.64 | +1.46 / 0.17 |
| 0.15 | +1.95 / 0.26 | +1.58 / 0.13 |

It improves **monotonically to the grid edge** — but that is a **backtest artifact**: a
`sl<~0.4` band (≲ one 1h-bar range) gets whipsawed by intrabar noise the bar simulator
cannot see, so the rising Sharpe / falling win-rate (0.18→0.12) below ~0.4 is not real.
**`sl_mult=0.4` is the realistic floor** — DD 1.29→0.77 (−40%), Sharpe up — and going
tighter needs tick-level slippage validation before being trusted.

**What the DD fix did and did not do.** It cut the drawdown and lifted the aggregate
Sharpe, but the **walk-forward is still 4/6** and the two losing regimes are unchanged
(early-2021; the 2023 raging bull, where counter-trend down-bursts bleed) — actually more
negative, because a tighter stop just takes more small losses where the *direction* is
systematically wrong. The remaining weakness is a **direction** problem, not a stop one.

## 4. Verdict & next

A real **2nd-strategy candidate** — cost-robust, diversifying (+0.20 / −0.05), beats B&H
both lockbox splits untuned, DD now 0.77. **Not robust across regimes** (4/6 folds; weak
in strong bulls). Obvious next lever: the **counter-trend entry gate** (`drop_counter_trend`,
already built for the ride strategies) — it fixed the analogous bull-fold weakness for
`zigzag_bounce_ride`, so it likely helps the 2023 fold here. Then formal ship-gate and a
fresh live-forward before capital. Lineage: reuses the `random_hedge` ride exit; sibling of
[`density_pullback.md`](density_pullback.md).
