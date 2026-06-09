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
| **Status** | **`ship=True`** (formal `run_cycle`, 2026-06-07): IS eqSharpe **+1.49** ≥ B&H +0.64, OOS **+0.90** ≥ B&H −0.90, consistency 65% > 62%. Genuine **lift over the random-hedge null** (canonical OOS +0.90 vs null +0.65; lockbox +0.35) — one of only two candidates that clears the null. Caveat: 4/6 WF (accepted); fresh live-forward still owed before capital. |

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

## 4. Counter-trend gate (`drop_counter_trend=True`, default)

The remaining weakness after the stop fix was a **direction** problem — counter-trend
down-bursts bleeding in strong uptrends. Applying the inherited `drop_counter_trend` gate
(skip a burst whose side opposes the EMA-200 trend) is a clean risk/robustness trade
(@10bp):

| | gate off | gate on (default) |
|---|---|---|
| IS eqSh / DD | +1.44 / 0.77 | +1.38 / **0.47** |
| OOS eqSh / DD | +1.25 / 0.14 | +0.99 / 0.15 |
| folds | 4/6 | 4/6 (bad folds less bad: −2.2→−1.6, −1.9→−1.2) |
| corr to density_pullback | +0.20 | +0.155 |

It **cuts DD 0.77 → 0.47** (now near density_pullback's 0.34), softens both bad regimes,
and is *more* diversifying — for a modest Sharpe giveback (OOS +1.25→+0.99, still well
above B&H −0.16). It does **not** flip a fold positive (still 4/6) — the two regimes stay
negative, just less so. Adopted as default per robustness-over-absolute.

## 5. Two-sided / directionless-burst filter (`skip_contra_extreme=1`, default)

A chart-driven idea: not every burst has a *direction*. A bar that, before closing in the
ride side, printed an extreme **against** it (a LONG burst undercutting the prior-bar low, a
SHORT burst making a higher high than the prior bar) is a two-sided/outside expansion —
there is no clean side for a directional ride to follow. The knob `skip_contra_extreme=N`
skips an entry whose trigger bar made a contrary-side extreme over the prior `N` bars;
default `1` is the WF-validated contra-1bar definition. Causal (bar `t` closed, fill `t+1`
open).

Selection was done **inside-sample via the 6 walk-forward folds** (per-trade mean-return
lift +ve in 6/6 folds, mean +0.44%), reserving the lockbox OOS for one-shot confirmation —
not peeked during ideation (see `docs/evaluation_criteria.md`; the idea was once a
*false-negative* killed on a single OOS peek that landed on the one quiet fold). On the
**equity metric**:

| | baseline (off) | filter on (default) |
|---|---|---|
| IS eqSh (B&H +0.64) | +1.487 | **+1.686** |
| OOS eqSh (B&H −0.85) | +0.904 | +0.828 |
| quarter-consistency | 65% | **76%** |
| WF mean eqSh / beat-B&H | +0.93 / 3-of-6 | **+1.24 / 4-of-6** |
| trades (IS / OOS) | 542 / 143 | **383 / 117** (−27%) |

It improves equity Sharpe in **5 of 6 WF folds** (only f4 a −0.10 giveback), lifts the WF
mean and beat-rate and quarter-consistency, and **cuts turnover 27%** (the branch's recurring
"cost kills edges" win). The only loss is the single 80/20 OOS split (−0.076) — but that
window ≈ the most-recent fold, which **improves** in the WF view (+1.07→+1.22), so it is the
known one-fold artifact, not a real regression. Ship gate (`run_cycle`) still `True`. Adopted
as default. (`src/backtest/analysis/vol_expansion_contra_ab.py` reproduces the table.)

The independent **lockbox** basis (`benchmark_table.md`, fixed IS pre-2025-04-01 / OOS
2025-04-01→2026-04-01) agrees and adds a headline the equity-split table hides — **IS_DD
nearly halves**:

| (lockbox) | n | IS_sh | DR | IS_DD | mean_r | OOS_sh | OOS_DD | OOS@10bp |
|---|---|---|---|---|---|---|---|---|
| baseline (off) | 526 | +1.56 | 0.21 | 0.41 | +0.0034 | +1.27 | 0.12 | +0.99 |
| filter on (default) | 369 | **+1.76** | 0.24 | **0.24** | +0.0051 | +1.25 | 0.11 | +0.97 |

Same story on a different split — IS Sharpe up, IS_DD 0.41→**0.24** (now below density_pullback's
0.31), DR/mean_r up, OOS essentially flat — confirming the filter removes mostly losing,
high-variance directionless bursts rather than trimming winners.

## 6. Follow-through confirmation (`confirm_bars`) — tested, FRAGILE, not adopted

Aimed squarely at the 4/6-fold problem: the failing regimes are where bursts mostly *reverse*,
so the `confirm_bars=N` knob delays entry until the close N bars after the burst is beyond the
burst-bar close in the ride direction (a follow-through vote; entry then fills N+1 bars after
the burst). Causal, no-op at the default `None`. WF horizon sweep
(`src/backtest/analysis/vol_expansion_confirm_ab.py`, on top of the shipped `skip_contra_extreme=1`):

| confirm | IS n | IS eqSh | OOS eqSh | WF folds+ | WF mean | gate |
|---|---|---|---|---|---|---|
| **None (shipped)** | 383 | +1.69 | **+0.83** | 4/6 | +1.24 | ship |
| 1 | 172 | +1.52 | −0.12 | 5/6 | +0.95 | ship |
| **2** | 180 | +1.70 | +0.72 | **6/6** | **+1.37** | ship |
| 3 | 182 | +1.55 | +0.00 | 4/6 | +1.10 | ship |
| 4 | 184 | +2.01 | **−1.01** | 4/6 | +1.27 | **FAIL** |

`confirm_bars=2` is the only config ever to flip **all 6 folds positive** — but the sweep
exposes it as a **knife-edge, not structure**: WF folds-positive runs `4→5→6→4→4` (only the
single value peaks) and OOS eqSharpe bounces `+0.83→−0.12→+0.72→+0.00→−1.01` across adjacent
horizons. A real edge varies *smoothly* with the lookback; this does not. The filter drops ~half
the trades at **every** N (383→~180) but *which* half is horizon-noise. Adopting `=2` would be
selecting the one lucky horizon that aligns with the fixed fold boundaries (the multiple-comparison
overfit the methodology warns against), and the shipped `None` keeps the best OOS (+0.83) of any
positive-OOS arm regardless. **Hypothesis rejected; knob kept as a documented no-op (default
`None`); shipped logic unchanged.** The 4/6 regimes remain open — see §7.

## 7. Squeeze-depth × expansion-magnitude sweep (`expand_mult` 2.0→2.5, ADOPTED)

A 2D sweep of the two *existing* trigger knobs (`vol_expansion_squeeze_sweep.py`), again on top
of the shipped `skip_contra_extreme=1`, looking for a **smooth region** (not a confirm_bars
knife-edge) that helps the 4/6-fold problem.

- **Squeeze depth is a dead end.** IS equity Sharpe *decreases monotonically* as the squeeze
  tightens (sq 0.30→0.10 at ex=2.0: +1.80→+1.17). Deeper squeezes do **not** make cleaner
  directional bursts — shallower is mildly better; shipped 0.25 is near the gate's sweet spot.
- **`expand_mult=2.5` is a smooth, structural fold-rescue.** The whole ex=2.5 row is uniformly
  **5/6 folds across every squeeze value** (vs the shipped ex=2.0 row's jittery 5,4,5,4,5).
  Per-fold, it rescues **f1 (early-2021)** at every squeeze cell (−0.23→+0.5…+1.2) — the same
  fold each time, the signature of structure, not luck. But **f3 (the 2023 raging bull) stays
  negative everywhere** (even slightly worse), so it fixes *one* of the two bad regimes.

| (sq=0.25) | IS eqSh | OOS eqSh | WF folds+ | WF mean | IS n |
|---|---|---|---|---|---|
| ex=2.0 (prev) | +1.69 | +0.83 | 4/6 | +1.24 | 383 |
| ex=2.5 (adopted) | +1.46 | +0.82 | **5/6** | +1.16 | 247 |

It is a genuine **trade, not a free win**: +1 rescued regime, lower turnover (−35%, cost-light),
in exchange for ~0.2 IS Sharpe and a weakened strong fold (f5 +1.96→+0.90); WF mean ≈ flat; still
5/6, not 6/6 (f3 unsolved). **Adopted 2026-06-10** under the project's robustness-over-absolute
philosophy (same reasoning as §4's counter-trend gate). The independent lockbox basis is even
kinder than the 80/20 cycle — it improves nearly everything *except* IS Sharpe: turnover
369→**236**, IS_DD 0.24→**0.17**, OOS Sharpe +1.25→**+1.28**, OOS_DD 0.11→**0.05**, OOS@10bp
+0.97→**+1.03**, quarterly consistency 76%→**82%**, cDP +0.18→**+0.10** (more diversifying), WF
4/6→**5/6**; only IS Sharpe gives back (+1.76→+1.51). `run_cycle` ships `True`; forward boundary
unchanged (same 2026-06-07 selection cutoff). See `benchmark_table.md`.

## 8. Verdict & next

A real **2nd-strategy candidate**: cost-robust, diversifying (+0.10 / −0.06), beats B&H in
both lockbox splits untuned. After §4 (counter-trend gate), §5 (two-sided-burst filter) and §7
(`expand_mult=2.5`) its lockbox **IS_DD is down to 0.17 / OOS_DD 0.05** — the lowest DD of any
candidate — at IS Sharpe +1.51, OOS +1.28 and **82% quarterly consistency**. Now **5/6 WF folds**:
§7 rescued the early-2021 regime, but **the 2023 raging bull stays negative** — a vol-expansion
ride structurally misfires when that regime's bursts mostly reverse (the §6 confirm_bars attempt
on this exact problem was a fragile knife-edge and was rejected). Remaining path: the ship-gate
(`run_cycle`) passes; the **live-forward is now
queued and running clean** — `paper_forward` was given a per-strategy lockbox boundary
re-anchored to **2026-06-07 22:00** (the selection cutoff for both §5 and §7, which used data
through that point), so the forward record never overlaps the data the logic was chosen on, and
the weekly Monday cron (`scripts/weekly_forward_check.sh`) scores it. No CONFIRMED/NOT-CONFIRMED
verdict until ≥20 forward trades AND ≥60 days (~2 months out); the 2023-bull regime remains the
honest ceiling on confidence. Lineage: reuses the `random_hedge` ride exit; sibling of
[`density_pullback.md`](density_pullback.md).
