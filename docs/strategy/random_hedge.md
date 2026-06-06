# Strategy: `random_hedge` (null-entry control)

A deliberate **null-entry baseline**, not a tradeable strategy. It opens a
**market-neutral long+short hedged pair on random bars** and exits each leg with
the project's best exit machinery (adaptive zs stop + next-dense target +
periodic ratchet). The point is to answer one question the whole research arc kept
raising — *is the edge in the exit, not the entry?* If random entries with smart
exits made money, the exit alone would be the edge. They do not.

| | |
|---|---|
| **Name** | `random_hedge` |
| **Class** | `src/strategy/random_hedge.py` → `RandomHedgeStrategy` |
| **Simulator** | `src/simulator/multi_simulator.py` → `MultiSimulator` (≤ `max_slots`) |
| **Reuses** | `ZsTpSl` (`src/exit/zs_tp_sl.py`), `_next_dense` (`density_multi_breakout`), `detect_peaks` (`src/indicators/zigzag.py`) |
| **Default config** | `entry_prob=0.01, seed=0, zigzag_size=12, sl_mult=1.0, recalc_bars=12, time_stop_bars=120, target_window=336, max_slots=50` |
| **Default timeframe** | **1h** |
| **Status** | **REJECT / control** — `ship=False`. Random entry + these exits is net-negative in-sample (IS equity Sharpe **−0.35**). The exit does not manufacture edge from noise. Kept as the **null baseline** to measure real entries against. See §5. **Update (§6):** subtracting the one robust *bad* entry (high-volatility bars) lifts the baseline to IS eqSharpe **+0.34** — variant `random_hedge_volfilter`. **Update (§7):** a better-priced density-edge *limit* entry (`random_hedge_density`) does **not** lift it — worse IS, negative OOS (adverse selection + fade-dies-in-trends). **Current best (§6 "Current best setup"):** ATR-Q4 gate + tuned slow-ratchet exit (`recalc_bars=48`) → IS eqSharpe **+0.87** / OOS **+0.76** (8-seed), 4/5 IS years + 2/2 OOS years positive — the registered default of `random_hedge_volfilter`. |

---

## 1. Hypothesis (and why a hedged pair)

Every entry probe on this branch found the density breakout has **no directional
entry edge** (DR ≈ 0.50 at every horizon — see [`findings.md`](../findings.md));
the payoff lives in the exit / position management. `random_hedge` tests that
head-on by removing entry skill entirely.

The **hedged pair** (a long *and* a short on the same random bar) makes the entry
**perfectly market-neutral** — at fill the pair has zero directional expectation —
so any P&L can only come from the **asymmetric exits**. This is also a strong
correctness check: a hedged pair is zero-sum at entry, so a high win rate on *both*
legs is impossible without a bug (see §4).

## 2. Entry — random, hedged, seeded

On each bar (after warmup), with probability `entry_prob` (default 0.01), emit a
**pair** of signals — one LONG, one SHORT — at the bar close; both fill at the next
bar's open (two-bar rule). A seeded `numpy` RNG makes the backtest deterministic.
The entry carries **no skill** and is a placeholder: the intended use is to swap in
a better-priced entry later and measure the lift over this baseline.

## 3. Exit — zs stop + dense target + periodic ratchet

Per-leg `ExitConfig` plus a dynamic ratchet hook, whichever triggers first:

- **Stop (`sl_abs`)** — `sl_mult × band`, where `band` is the `ZsTpSl` EWA of recent
  zigzag leg sizes (adaptive volatility; high-side winsorised). Side-independent.
- **Take-profit (`tp_abs`)** — the next *pre-existing* dense node beyond entry in
  the trade direction (`_next_dense`, `target_window=336`), at least
  `target_min_dist_frac × band` away so it is not trivially close.
- **Ratchet (`dynamic_exit`)** — every `recalc_bars` (12) bars, if the leg is
  winning, trail the stop to `favorable_extreme ∓ band` (never loosened). This is
  the "recalculate the SL toward the winner side" rule.
- **Time stop** — `time_stop_bars` (120 ≈ 5 days) backstop.

## 4. Harness change + two bugs caught

**Harness:** the `MultiSimulator` filled one signal per bar, so "both sides at
once" was not expressible. Added `Strategy.precompute_multi() -> {ts: [Signal,…]}`
and a list-of-pendings fill loop (each leg fills while a slot is free, two-bar rule
preserved). Single-signal `precompute` is wrapped as one-element lists, so existing
strategies are unchanged — `density_multi_breakout` is byte-identical (608 trades,
eqSharpe 0.903 / 0.842).

**Two bugs the hedged-pair sanity check exposed** (the first run printed an
impossible eqSharpe **7.8 / 80 % win / PF 70**):

1. **Same-bar trailing look-ahead** — the ratchet recomputed the stop from the
   current bar's high, then the *same* bar's low triggered it, booking the bar's
   range as profit. Fixed: breach-check against the prior-bar stop **before**
   recomputing for future bars.
2. **`id(pos)` stale state (the real culprit)** — per-position ratchet state was
   keyed on `id(pos)`. CPython reuses freed object addresses, so a new position
   inherited a *dead* position's ratcheted stop and "exited" immediately at a
   stale favorable level (fake +60 %-in-1-bar wins at a constant price). Fixed by
   keying on `(entry_idx, side)`, which is unique per position and cleared each run.

> **Lesson:** never key per-object state on `id()` across object lifetimes; and a
> control whose result looks too good is doing its job — a hedged pair *cannot*
> win on both legs.

## 5. Results (bug-free, GMO 1h ~5y)

### Aggregate

| metric | in-sample | OOS |
|---|---|---|
| **equity Sharpe** | **−0.346** | +1.155 |
| total return | −0.51 | +0.27 |
| **DR** (win rate) | **0.370** | 0.395 |
| profit factor | 0.94 | 1.19 |
| max DD | 0.70 | 0.16 |
| trades | 710 | 152 |

vs B&H annualised Sharpe **+0.64**. Exit mix (all): trail 460 · stop 272 · target
109 · time 21. **`ship=False`.** DR ≈ 0.37–0.40 is sub-coin-flip — expected for a
trend-ride payoff (few big winners), but here the winners do **not** cover the
losers in-sample (PF 0.94).

### Per-period (frequency-adaptive: ~175 trades/yr → year / quarter, not week)

**In-sample, by year** — `DR | total_return | max_DD`:

| year | n | DR | total_return | max_DD |
|---|---|---|---|---|
| 2021 | 119 | 0.370 | +0.0144 | 0.295 |
| 2022 | 167 | 0.371 | **−0.3961** | 0.403 |
| 2023 | 162 | 0.346 | −0.1219 | 0.221 |
| 2024 | 204 | 0.382 | +0.0253 | 0.253 |
| 2025 | 58 | 0.397 | −0.0321 | 0.180 |

→ IS consistency: **2/5 years (40 %)** and **7/17 quarters (41 %)** non-negative —
far below the ≥ 80 % ship gate. The loss is concentrated in the 2022–23 bear
(−0.40 / −0.12); the hedged pair bleeds the stop+cost in trendless/whipsaw years.

**OOS, by year:**

| year | n | DR | total_return | max_DD |
|---|---|---|---|---|
| 2025 | 102 | 0.392 | +0.1392 | 0.150 |
| 2026 | 50 | 0.400 | +0.1260 | 0.161 |

→ OOS consistency: 2/2 years, **3/5 quarters (60 %)**.

Random entry + smart exits is **net-negative in-sample and fails the consistency
gate badly** (40 %). The exit machinery shapes the payoff distribution but **cannot
create edge from a random entry**. The negative-IS / positive-OOS split (and the
much smaller OOS sample) is the regime-artifact tell seen elsewhere on this branch
— a single split disagreeing in sign — not a stable edge.

## 6. Bad-entry probe — *subtract* the worst contexts (the asymmetry test)

> Premise (the user's): **finding a *bad* entry is easier than finding a good
> one.** We never found a directional *good* entry on this branch; this asks the
> mirror question — is there a context where the hedged pair reliably *loses*, so
> we can just not trade it? Probe:
> `src/backtest/analysis/random_hedge_badentry_probe.py`. Label = realised **pair**
> return (long leg + short leg, net) from an actual `random_hedge` run; each entry
> bar is tagged by five causal context features and bucketed IS vs OOS.

**The hedged-pair P&L mechanism makes the prediction:** in a *trend* one leg rides
to the dense target while the other takes a small zs stop → net **positive**; in
*wide chop* BOTH legs whipsaw out at the stop → net **negative + double cost**. So
the pair should lose where the range is wide — i.e. **high volatility**. (Note this
is the **opposite** of `density_multi_breakout`, where a *directional* breakout
*needs* volatility to follow through and loses in dead-calm boxes. A neutral pair
and a directional breakout want opposite vol regimes — both mechanistic.)

**Per-bucket realised pair return (mean_r), IS vs OOS:**

| feature | bucket | IS mean_r | OOS mean_r | robust? |
|---|---|---|---|---|
| **ATR(14) pct** | Q1 (low vol) | **+0.0051** | **+0.0025** | ✅ both + |
| | Q4 (high vol) | **−0.0099** | **−0.0012** | ✅ both − |
| BB width pct | Q4 (wide) | −0.0072 | **+0.0074** | ✗ flips |
| BB %B | upper (>.8) | −0.0066 | −0.0002 | ✗ OOS ~flat |
| near zigzag peak | — | 336/355 in one bin | — | ✗ degenerate |
| candle range pct | Q1 / Q3 | +0.003 / −0.004 | flips | ✗ not robust |

Only **ATR realized volatility** separates winners from losers with the *same sign
in both splits* (eval §6 degradation-over-absolute). The other four — BB width, BB
position, zigzag-peak proximity, outsized candle — are **not** robust (BB width is
a vol proxy that flips OOS; near-peak is degenerate because *some* peak is always
within 0.5%). So the single avoidable bad entry is **high vol**.

**Filter result (`max_atr_rank`, drop the ATR top quartile → `random_hedge_volfilter`):**

| variant | IS eqSharpe | OOS eqSharpe | IS ret | IS DD |
|---|---|---|---|---|
| baseline | **−0.346** | +1.155 | −0.51 | 0.70 |
| **drop ATR Q4** (`rank≥.75`) | **+0.337** | +0.569 | +0.33 | **0.30** |
| drop top-half (`≥.50`) | +0.936 | +0.157 | +0.75 | 0.18 |
| keep only low-vol (`≥.25`) | +1.145 | +0.067 | +0.53 | 0.20 |

Subtracting just the worst quartile **flips the null baseline positive and halves
the drawdown** (0.70→0.30). Tighter cuts raise IS but **overfit** — OOS collapses
toward 0 as we cut more — so the gentle **Q4-only** cut is the pre-registered
setting.

**Seed robustness (8 seeds):** the IS lift is real, not a one-seed fluke — filtered
IS eqSharpe beats baseline in **7/8 seeds** (mean lift **+0.28**) and is positive
in 7/8. The **OOS** does *not* improve: the recent ~1y OOS window was a clean
directional regime where even random pairs profit (baseline OOS positive in 8/8),
so cutting high-vol bars just trades less of a good thing (filtered OOS positive
7/8 but lower). Consistent with the per-bucket table: ATR-Q4 is *strongly* negative
over the 4y IS (−0.0099) but only *weakly* negative in the 1y OOS (−0.0012). The
bad-entry signature is real and large in-sample; the OOS window is too favorable/
short to add power.

**Verdict:** the user's thesis holds — we found no good *directional* entry, but a
**robust bad entry (high realized volatility)** whose removal turns a net-negative
random baseline into a positive, lower-drawdown one. This is a *risk/context* gate
(when not to trade a neutral pair), not a directional edge. `random_hedge_volfilter`
is the registered variant; still `ship=False` (it is a control lineage), but it is
now the **stronger null baseline** to measure a real-priced entry against.

### Batch 2 — five more bad-entry candidates (chop / persistence / indecision / congestion / volume)

A second, mechanistically-distinct sweep (all aimed at the pair's failure mode —
chop/mean-reversion whipsaws both legs — and chosen to *not* be raw ATR proxies):

| feature | bad bucket | IS mean_r | OOS mean_r | robust? |
|---|---|---|---|---|
| **Choppiness Index** | Q4 (sideways) | −0.0035 | −0.0034 | ✅ + Q1 (trending) good both |
| Return autocorr (lag-1) | trend(>+.05) | −0.0048 | −0.0034 | ⚠️ robust but mostly an ATR proxy |
| Volume pct | Q4 (high) | −0.0046 | −0.0093 | ⚠️ only Q4; rest noise (ATR proxy) |
| Candle body fraction | — | flips IS→OOS | — | ✗ |
| Value-area position | — | all neg / noisy | — | ✗ |

**Independence test (the important one).** Re-bucketing *after* dropping ATR-Q4,
**only Choppiness survives**: IS stays monotone (Q1 +0.0049 → Q4 −0.0025), OOS
(Q1 +0.0107 → Q4 −0.0035) — Q4 negative in both splits even within the lower-vol
kept set. The autocorr signal mostly collapses (trend −0.0048 → −0.0014), i.e. it
was largely re-expressing high vol. So choppiness is a genuinely **ATR-independent**
per-trade predictor.

**But it does not ship — the per-trade signal ≠ the portfolio metric.** Adding the
Choppiness filter (`max_chop_rank`) does *not* lift the equity Sharpe and stacking
it on ATR slightly *hurts* (8-seed mean IS eqSharpe):

| config | IS eqSh | OOS eqSh | IS+ seeds |
|---|---|---|---|
| baseline | +0.170 | +0.856 | 5/8 |
| **ATR-Q4** | **+0.454** | +0.462 | **7/8** |
| CHOP-Q4 alone | +0.114 | +0.844 | 4/8 |
| ATR-Q4 + CHOP-Q4 | +0.401 | +0.403 | 5/8 |

The chop cut removes only *mildly* negative trades (conditional −0.0025 vs ATR's
−0.0099) and the lost diversification across the overlapping book outweighs the
trimmed losers. This is the same per-trade-vs-portfolio gap the regime-gate work
hit: a real diagnostic separation need not be a shippable portfolio lever.
`max_chop_rank` is kept as a research lever (off by default); **ATR-Q4 remains the
only bad-entry gate that improves the portfolio metric.**

### Current best setup — ATR-Q4 gate + tuned (slow-ratchet) exit

The exit was tuned (grid + anchored walk-forward on `density_pullback`, see
[`density_pullback.md`](density_pullback.md) §4) and the dominant lever — a **slow
ratchet** — transfers straight to `random_hedge`: recomputing the trailing stop
every **48** bars instead of 12 stops choking the runners. Holding the ATR-Q4 gate
and `sl_mult=1.0 / time_stop_bars=120`, the 8-seed mean equity Sharpe climbs monotone
in `recalc_bars` — **12: IS +0.45 / OOS +0.46 → 24: +0.70 / +0.45 → 48: +0.87 /
+0.76** (8/8 IS, 7/8 OOS positive), both above B&H +0.64. This is the registered
default of `random_hedge_volfilter`:

> **Current setup:** `max_atr_rank=0.75, sl_mult=1.0, recalc_bars=48, time_stop_bars=120`
> — **IS equity Sharpe +0.87 / OOS +0.76** (8-seed mean) vs B&H +0.64.

**Per-period breakdown (8-seed mean; `ret`/`max_DD` are net per-trade-return-cumulative,
`Sharpe`/`Sortino` are per-trade — the headline portfolio metric is the equity Sharpe
above; per-trade understates overlapping slots).**

*In-sample, by year:*

| period | n | DR | ret | max_DD | Sharpe | Sortino |
|---|---|---|---|---|---|---|
| 2021 | 100 | 0.372 | +0.087 | 0.340 | +0.015 | +0.071 |
| 2022 | 128 | 0.393 | −0.018 | 0.278 | −0.004 | −0.012 |
| 2023 | 122 | 0.375 | +0.259 | 0.230 | +0.070 | +0.283 |
| 2024 | 140 | 0.396 | +0.551 | 0.213 | +0.110 | +0.436 |
| 2025 | 50 | 0.401 | +0.123 | 0.129 | +0.062 | +0.273 |

→ **4/5 years non-negative** (2022 is −0.018, essentially flat in the bear); per-trade
DR ~0.37–0.40 (sub-coin-flip is normal for this trend-ride payoff — few big winners).

*In-sample, by quarter* (17 quarters): **12/17 non-negative**; the worst is 2023Q3
(ret −0.110, Sharpe −0.26), the best 2023Q4 (+0.263, Sortino +1.09).

| period | n | DR | ret | max_DD | Sharpe | Sortino |
|---|---|---|---|---|---|---|
| 2021Q2 | 24 | 0.413 | +0.108 | 0.175 | +0.071 | +0.237 |
| 2021Q3 | 35 | 0.373 | −0.014 | 0.209 | −0.042 | −0.042 |
| 2021Q4 | 41 | 0.347 | −0.008 | 0.229 | −0.042 | −0.050 |
| 2022Q1 | 28 | 0.374 | −0.036 | 0.166 | −0.093 | −0.237 |
| 2022Q2 | 32 | 0.386 | −0.027 | 0.149 | −0.027 | −0.061 |
| 2022Q3 | 36 | 0.426 | +0.062 | 0.126 | +0.051 | +0.186 |
| 2022Q4 | 31 | 0.372 | −0.016 | 0.095 | −0.030 | −0.018 |
| 2023Q1 | 25 | 0.380 | +0.009 | 0.130 | −0.008 | +0.053 |
| 2023Q2 | 31 | 0.408 | +0.097 | 0.081 | +0.061 | +0.477 |
| 2023Q3 | 31 | 0.264 | −0.110 | 0.138 | −0.263 | −0.708 |
| 2023Q4 | 34 | 0.444 | +0.263 | 0.081 | +0.216 | +1.089 |
| 2024Q1 | 28 | 0.408 | +0.075 | 0.111 | +0.084 | +0.450 |
| 2024Q2 | 41 | 0.392 | +0.103 | 0.121 | +0.065 | +0.302 |
| 2024Q3 | 38 | 0.398 | +0.155 | 0.140 | +0.098 | +0.424 |
| 2024Q4 | 34 | 0.402 | +0.219 | 0.099 | +0.120 | +0.997 |
| 2025Q1 | 31 | 0.393 | +0.118 | 0.117 | +0.087 | +0.383 |
| 2025Q2 | 19 | 0.419 | +0.005 | 0.075 | −0.050 | +0.102 |

*OOS, by year:* **2/2 positive.**

| period | n | DR | ret | max_DD | Sharpe | Sortino |
|---|---|---|---|---|---|---|
| 2025 | 79 | 0.400 | +0.136 | 0.142 | +0.069 | +0.214 |
| 2026 | 52 | 0.385 | +0.037 | 0.149 | +0.021 | +0.102 |

Still `ship=False` for the consistency gate (12/17 quarters = 71% < 80%), but this is
the strongest random_hedge-family config: a bad-entry *risk* gate plus a slow-ratchet
exit, IS +0.87 / OOS +0.76, positive in 4/5 IS years and 2/2 OOS years.

## 7. Better-priced entry — density-edge limit pair (`random_hedge_density`, REJECT)

The payoff step: plug a **better-priced** entry into this exact exit framework and
measure the lift over the random market baseline. Chosen scheme (`src/strategy/
random_hedge_density.py`): on a random bar, rest a **buy-limit at the value-area
low** (dense support) and a **sell-limit at the value-area high** (dense
resistance) — each a genuine concession (long limit below the close, short above,
never marketable), resting `limit_window` bars then cancelled. The exit (zs SL +
next-dense TP + ratchet) is unchanged; the next-dense TP naturally targets the
*other* side of the range, so this is a **fade-the-box mean-reversion** entry.

**Harness change (backward-compatible).** `Signal` gained `limit_price` /
`limit_expiry_bars`; `MultiSimulator` now rests limit orders (fills at the limit on
a touch within the window, else cancels) alongside market orders. `limit_price=None`
is the existing market path, so all other strategies are unchanged —
`density_multi_breakout` is byte-identical (460 IS / 148 OOS, eqSharpe 0.903 / 0.842).

**Result (8-seed mean equity Sharpe, GMO 1h):**

| entry | IS eqSh | OOS eqSh | IS+ seeds | IS trades |
|---|---|---|---|---|
| random market (baseline) | +0.170 | +0.856 | 5/8 | 715 |
| random market + ATR-Q4 | +0.454 | +0.462 | 7/8 | 540 |
| **density-limit (no gate)** | **+0.151** | **−1.209** | 6/8 | 152 |
| density-limit + ATR-Q4 | −0.167 | −1.021 | 3/8 | 128 |

The better-priced entry is **worse, not better** — no lift in-sample and strongly
**negative OOS**. Robust to parameters: a `va_window × limit_window` sweep
(84/168/336 × 12/24/48) is ≤ +0.11 IS and **negative OOS in all 9 cells** — it is
structural, not a mistune.

**Why (mechanism, not a bug).** Per-side/exit breakdown: fills happen on both legs
but are **adversely selected** — TAKE_PROFIT is the minority while STOP/TRAIL
dominate, i.e. a limit at the box edge fills disproportionately when price is
*continuing through* the level, not bouncing off it (the winner's-curse of resting
limits). And fading the box is a **mean-reversion** bet that gets run over in trends:
in the directional OOS the long leg is destroyed (win 0.23, mean_r −0.008). The
"better price" is illusory once you condition on getting filled.

**Verdict:** `ship=False`. A density-edge (mean-reversion) limit entry does **not**
rescue the framework — combined with §1–§6 (no directional edge; the exit can't
make edge from noise; only a *risk* gate helps), no entry-pricing trick tested lifts
`random_hedge` to a shippable edge. The untested inverse is a **momentum/pullback**
entry (buy *with* the trend on a retrace) — the opposite of fading — which the
adverse-selection + fade-dies-in-trends findings here both point toward; not yet built.

## 8. Conclusion & use

This **tempers** the "the edge is in the exit" framing: the exit is necessary but
not sufficient — `density_multi_breakout` needs *both* its selective entry and its
dense-aware exit. `random_hedge`'s real value is as a **null baseline**: plug a
candidate entry into this exact exit framework and judge it by **lift over random**
(a stronger test than absolute Sharpe) — done in §7 for a density-edge limit entry
(rejected) and in [`density_pullback.md`](density_pullback.md) for a *directional*
pullback entry (the positive bookend: the first entry to clearly beat this null
baseline in-sample, +0.68 vs +0.17 — entry quality does lift over random, and a
pullback fill improves robustness/DD over a market fill). Research lineage / sibling
negatives: [`findings.md`](../findings.md),
[`density_multi_breakout.md`](density_multi_breakout.md).
