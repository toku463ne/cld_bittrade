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
| **Status** | **REJECT / control** — `ship=False`. Random entry + these exits is net-negative in-sample (IS equity Sharpe **−0.35**). The exit does not manufacture edge from noise. Kept as the **null baseline** to measure real entries against. See §5. **Update (§6):** subtracting the one robust *bad* entry (high-volatility bars) lifts the baseline to IS eqSharpe **+0.34** — variant `random_hedge_volfilter`. **Update (§7):** a better-priced density-edge *limit* entry (`random_hedge_density`) does **not** lift it — worse IS, negative OOS (adverse selection + fade-dies-in-trends). **Current best (§6 "Current best setup"):** ATR-Q4 gate + tuned exit (`sl_mult=0.75, recalc_bars=48`) → IS eqSharpe **+0.90** / OOS **+1.02** (8-seed), 5/5 IS years + 2/2 OOS years positive — the registered default of `random_hedge_volfilter`. |

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
[`density_pullback.md`](density_pullback.md) §3–§4) and **both** levers transfer
straight to `random_hedge` — they are properties of the shared exit framework. The
**slow ratchet** (recompute the trail every **48** bars, not 12) stops choking the
runners; the 8-seed mean equity Sharpe climbs monotone in `recalc_bars` (at `sl1.0`:
12: IS +0.45 / OOS +0.46 → 24: +0.70 / +0.45 → 48: +0.87 / +0.76). The **tight stop**
(`sl_mult=0.75`, the walk-forward optimum — 6/6 folds on `density_pullback`) then adds
OOS on top (`sl1.0` +0.87 / +0.76 → `sl0.75` **+0.90 / +1.02**). This is the
registered default of `random_hedge_volfilter`:

> **Current setup:** `max_atr_rank=0.75, sl_mult=0.75, recalc_bars=48, time_stop_bars=120`
> — **IS equity Sharpe +0.90 / OOS +1.02** (8-seed mean; 8/8 IS, 7/8 OOS positive) vs
> B&H +0.64.

**Per-period breakdown (8-seed mean; `ret`/`max_DD` are net per-trade-return-cumulative,
`Sharpe`/`Sortino` are per-trade — the headline portfolio metric is the equity Sharpe
above; per-trade understates overlapping slots).**

*In-sample, by year:* **5/5 years non-negative** (the tight stop turns the old 2022
−0.02 positive); per-trade DR ~0.32–0.36 (sub-coin-flip is normal for this trend-ride
payoff — few big winners carried by the ratchet).

| period | n | DR | ret | max_DD | Sharpe | Sortino |
|---|---|---|---|---|---|---|
| 2021 | 100 | 0.324 | +0.126 | 0.341 | +0.025 | +0.133 |
| 2022 | 128 | 0.364 | +0.151 | 0.216 | +0.039 | +0.162 |
| 2023 | 122 | 0.328 | +0.195 | 0.209 | +0.054 | +0.272 |
| 2024 | 140 | 0.351 | +0.479 | 0.201 | +0.104 | +0.489 |
| 2025 | 50 | 0.361 | +0.140 | 0.129 | +0.075 | +0.410 |

*In-sample, by quarter* (17 quarters): **11/17 non-negative**; worst 2023Q3 (ret
−0.107, Sharpe −0.30), best 2023Q4 (+0.186, Sortino +1.05). (One fewer than `sl1.0`'s
12/17 — the tighter stop trades a marginal quarter for stronger years and far better
OOS.)

| period | n | DR | ret | max_DD | Sharpe | Sortino |
|---|---|---|---|---|---|---|
| 2021Q2 | 24 | 0.393 | +0.189 | 0.142 | +0.134 | +0.584 |
| 2021Q3 | 35 | 0.299 | −0.012 | 0.195 | −0.056 | −0.047 |
| 2021Q4 | 41 | 0.295 | −0.051 | 0.211 | −0.095 | −0.216 |
| 2022Q1 | 28 | 0.376 | +0.017 | 0.114 | −0.039 | −0.167 |
| 2022Q2 | 32 | 0.350 | +0.024 | 0.123 | +0.034 | +0.402 |
| 2022Q3 | 36 | 0.402 | +0.124 | 0.123 | +0.107 | +0.499 |
| 2022Q4 | 31 | 0.332 | −0.015 | 0.089 | −0.047 | −0.030 |
| 2023Q1 | 25 | 0.359 | −0.007 | 0.122 | −0.045 | +0.029 |
| 2023Q2 | 31 | 0.343 | +0.122 | 0.075 | +0.110 | +0.737 |
| 2023Q3 | 31 | 0.214 | −0.107 | 0.129 | −0.300 | −0.815 |
| 2023Q4 | 34 | 0.397 | +0.186 | 0.086 | +0.164 | +1.051 |
| 2024Q1 | 28 | 0.354 | +0.040 | 0.103 | +0.051 | +0.278 |
| 2024Q2 | 41 | 0.330 | +0.087 | 0.096 | +0.063 | +0.379 |
| 2024Q3 | 38 | 0.390 | +0.192 | 0.107 | +0.134 | +0.800 |
| 2024Q4 | 34 | 0.342 | +0.160 | 0.119 | +0.075 | +1.094 |
| 2025Q1 | 31 | 0.354 | +0.157 | 0.099 | +0.122 | +0.708 |
| 2025Q2 | 19 | 0.377 | −0.017 | 0.089 | −0.087 | +0.036 |

*OOS, by year:* **2/2 positive** (both stronger than at `sl1.0`).

| period | n | DR | ret | max_DD | Sharpe | Sortino |
|---|---|---|---|---|---|---|
| 2025 | 79 | 0.359 | +0.125 | 0.106 | +0.070 | +0.269 |
| 2026 | 52 | 0.354 | +0.101 | 0.113 | +0.060 | +0.303 |

**Ship verdict (revised relative gate — non-neg quarters ≥ B&H's ~62%, see eval §6.4):**
a **borderline near-miss**. Clears (a) on Sharpe (IS +0.90 / OOS +1.02 > B&H +0.64),
but the consistency is seed-sensitive: at the cycle's `seed=0` it is 59% (just under
B&H 62% → `ship=False`); the 8-seed mean is ~65% (would pass). So it sits right on the
B&H consistency line — call it the strongest *non*-shipping config, behind
`density_pullback` (which clears both gates cleanly). It is positive in **5/5 IS years
and 2/2 OOS years**.

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
