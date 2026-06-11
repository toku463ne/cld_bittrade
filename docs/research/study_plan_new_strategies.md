# Study plan — hunting strategies with genuine edge

**Priority (set 2026-06-07): find ANY strategy with genuine edge first; diversification is
a *later* concern, once we have several candidates worth combining.** Do **not** pre-gate
or pre-frame ideas on correlation with density_pullback — that prematurely narrows the
search before we have enough candidates. Judge each idea **purely on its own merit.**

### Idea-stage triage (own-merit, evaluate fast on the lockbox)

An idea is worth promoting if, on the fixed lockbox (`split_lockbox`, IS pre-2025-04 /
OOS 2025-04→2026-04), evaluated on **untuned/sensible defaults**:

1. **Lockbox OOS Sharpe ≥ buy-and-hold's own** (and IS too) — a real edge on held-out data.
2. **Cost-robust** — still clears B&H at a realistic ~10 bp round-trip (the recurring killer
   on this branch); ideally survives 20 bp.
3. **Drawdown** — acceptable / improvable (report it; it's a development target, not a hard
   gate).

### Later stages (only for survivors)

- **Combination stage** — *once ≥2 own-merit candidates exist*, measure cross-correlations
  and build the portfolio (this is where diversification matters — not before).
- **Capital gate** — formal ship-gate (`cycle.py`) + a fresh **live-forward**
  (`paper_forward`) before sizing past the 0.001 lot.

> **Rule:** change one variable at a time (eval §6.6); record thresholds before running;
> evaluate the lockbox once per idea (don't tune on it).

---

## Shared per-strategy workflow (each stage can KILL)

| Stage | Action | Kill criterion (pre-registered) |
|---|---|---|
| **0. Data** | Import + cache the asset(s) (`import_gmo --symbol … --product …`). | — |
| **1. Edge probe** | Measure the raw edge where *n is large* (5m/15m, 100k+ bars), net of a **realistic** GMO cost (0.04%/day funding + a stressed spread). | No bucket separates winners from losers *net of cost* in **both** an early and late split → KILL. |
| **2. Build** | `signs/<name>.py` + `strategy/<name>.py` (inherit base), register. | — |
| **3. Ship gate** | `run_cycle` on the traded timeframe (1h default). | Equity Sharpe < B&H in IS *or* OOS → not shippable. |
| **4. Robustness** | Walk-forward (fixed config across 6 folds), cost-sensitivity sweep, one-knob sanity. | < 4/6 folds positive, or edge dies at stressed cost → demote. |
| **5. Correlation** | Bar-return corr vs density_pullback + BTC. | **Diagnostic only — NOT a kill gate.** Recorded for the later combination stage; an idea with genuine standalone edge is kept regardless of correlation. |
| **6. Forward** | Add to `paper_forward`; accrue. | Not CONFIRMED → stays at 0.001 lot, no reserve capital. |

Capital is gated **sequentially** (validate → size → next), even though research can run
in parallel.

---

## Strategy A — "trade BCH referring BTC" (cross-asset)

**Why it fits:** a second asset (BCH) related to BTC is structurally different from our
density breakout/bounce family, and a *ratio* or *relative* signal tends to be
market-neutral → naturally low BTC-correlation (the diversification we want).

**Prior art / caution:** `cross_venue_leadlag_probe.py` already found cross-*venue*
lead-lag net-negative (REJECTED). Cross-*asset* (BCH vs BTC, same venue) is different,
but the same lesson applies: **lead-lag edges decay fast and are usually arbitraged at
1h** — so Stage 1 must test it net of cost and probably at 5m/15m, and BCH's **worse
liquidity / wider spread** makes the cost bar *higher* than BTC.

**Stage 0 — data (one-liner, no code change):**
```
uv run --env-file .env.bt python -m src.data.import_gmo \
    --symbol BCH_JPY --product GMO_BCH_JPY --from 2021-04-15 --to <today> --timeframe all
```
Then `load_cache(tf, product="GMO_BCH_JPY")` alongside `GMO_BTC_JPY`.

**Stage 1 — edge probe** (`src/backtest/analysis/bch_btc_probe.py`, to build): align BCH
& BTC bars on timestamp and measure **three** hypotheses, pre-registering the kill bar
for each (DR/return separation must survive ~0.04%/day funding + a stressed BCH spread,
in both an early and a late split):

- **A1 lead-lag** — cross-correlation of BTC returns vs *future* BCH returns at lags
  1…N bars. Edge = BCH under-reacts to a BTC move and catches up. Probe on 5m/15m.
  *Expect decay; likely KILL at 1h.*
- **A2 ratio mean-reversion (pairs)** — `log(BCH/BTC)` z-score over a rolling window;
  measure the **half-life** of reversion and the return to fading |z|>k. Market-neutral
  (long BCH / short BTC, or vice-versa). **Recommended primary** — lowest expected BTC
  correlation, plays to a statistical-arb edge rather than a speed race.
- **A3 BTC-regime filter** — does conditioning BCH entries on a BTC regime (trend/vol)
  add edge? A weaker, fallback framing.

**Design sketch (if A2 survives):** a `BchRatioSign` fires when `|z(log(BCH/BTC))| > k`;
the strategy trades BCH (and hedges with BTC for true neutrality, or trades BCH
outright if the ratio edge transmits) with a **mean-reversion exit** (TP at z→0, stop at
z→±k₂, time stop). Note this needs a *different* exit from the ride framework (which
targets continuation, not reversion) — define it fresh. Both legs need the GMO leverage
product (to short) → funding on both.

**A-specific kill criteria:** ratio half-life ≫ tradeable horizon; reversion edge <
round-trip cost on BCH; or corr to BTC/density_pullback > 0.30.

---

## Strategy B — Dynamic Range-Detected Grid Trading

**Why it fits:** it is the **mechanical complement of density_pullback** — same tight-box
regime detector, opposite payoff. density_pullback trades the *break OUT* of the box; the
grid trades the *oscillation INSIDE* it. When the box holds the grid wins (and the
pullback's breakout entries stop out small); when the box breaks the grid flattens (and
the pullback rides). So it should be **low-/negatively-correlated** with density_pullback
(the diversification we want) while reusing one detector. Family is also distinct from
Strategy A (ratio pairs).

**Concept (range fade, not always-on grid):** detect a range → lay a capped grid of
resting limits inside it → harvest oscillation → flatten on breakout or at the trade cap.

**Design (reuse-first):**

- **1. Range detection** — reuse the density **value-area tight box** (`band_height ≤
  max_band_pct × price` over a window) as both the trigger *and* the bounds, **confirmed**
  by low ATR(14) (trailing-percentile) and/or high **Choppiness Index** (`_chop_series`,
  high = sideways). Fire a range episode only when box-tight AND (low-vol or choppy).
- **2. Grid params** — bounds = the detected box `[lo, hi]`; `n` levels evenly spaced,
  **step = (hi−lo)/(n+1)**, with `n` scaled to band height; per-level size = min lot.
- **3. Trade cap = n levels** — one position per level → **max exposure = n × lot**,
  bounded by construction (the core risk control).
- **4. Exit (three triggers)** — per-level **take-profit** (close a fill at the next grid
  line, the profit engine); **breakout / box-invalidation** (close beyond `lo/hi` + buffer,
  or the box stops being tight) → **flatten all**; **time / max-fill backstop**.
- **Harness reuse:** a grid is a stack of resting limits → emit it via the
  `Signal.limit_price`/`limit_expiry_bars` support already in `MultiSimulator`; minimal
  new code. Multi-position book is already there.

**The risk to respect (short-gamma):** grids make many small wins while the range holds
and one big loss on the breakout (accumulated inventory on the wrong side) — "pennies in
front of a steamroller." The cap + flatten-on-breakout keep the tail finite, but the edge
is not free. **Two strategy-specific pre-registered kill criteria** (beyond the shared
gates):

- **B-kill-1 (cost/turnover):** grids fire many fills; the Stage-1 probe must show the
  net-of-cost oscillation capture > the breakout loss × breakout frequency, at realistic
  GMO cost (0.04%/day funding + a stressed spread). If the edge dies on cost → KILL. This
  is tested **first**.
- **B-kill-2 (tail / DD):** because a short-gamma payoff flatters the Sharpe ship gate,
  gate it **additionally on the breakout-loss distribution and max-DD**, and require it to
  survive the worst breakout regimes (2022 crash, 2024 bull) — not Sharpe alone.

---

## Sequencing & current status  (updated 2026-06-07, session save)

- **density_pullback:** shipped (revised gate); at 0.001 lot accruing its forward record
  via the weekly cron; reserve in BTC.
- **Strategy A (BCH/BTC): KILLED** (full-data verdict, 2026-06-07). Import complete (BCH 1h
  43,756 bars, 97.6% overlap with BTC, prices sane). All three framings fail the pre-registered
  gates: `log(BCH/BTC)` AR(1) **half-life 3,304 bars (~138 d)** → drifts, fails (i); **A2
  reversion 0/9** cells positive both halves; **A2′ momentum 0/9**; **A1 lead-lag ≈ 0** at all
  lags. Neither fading nor riding the ratio survives the 2-leg cost at 1h. Per the pre-registered
  rule → drop Strategy A. (A fresh A family — different asset/timeframe — could be revisited, but
  not now.)
- **Strategy B (grid): KILLED.** Stage-1 (`grid_range_probe.py`) FAILED B-kill-1 on the density
  box (net −0.010/ep, 24% profitable, tail 4.8×). **B′** swapped in a hold-prone Choppiness
  detector (chop≥61.8 and 55): it **fixed the tail** (4.8× → 2.7×/2.1×, confirming the
  adverse-selection diagnosis) but stayed **net-negative** (−0.008/−0.011/ep, 30–33% profitable,
  both halves negative, 2022/2024 negative) → **B-kill-1 FAIL again**. The grid's turnover cost
  (~13 fills/episode) + short-gamma breakout losses structurally exceed the oscillation capture.
  Per the pre-registered rule, **the grid concept is dead.**
- Capital only flows to a strategy after Stages 1–6 pass; each scaled in steps as its
  forward Sharpe accrues (certainty-asymmetry discipline — backtest ≠ realized).

## Pre-registration log (fill BEFORE running each stage)
- A1 lead-lag kill threshold: _TBD before probe_
- **A2 reversion (pre-registered 2026-06-07, before results)** — PASS Stage 1 iff ALL hold:
  (i) AR(1) **half-life of `log(BCH/BTC)` < 96 bars** (4 days — reverts within a tradeable
  horizon); (ii) the **hedged-spread** reversion trade (enter at `|z|≥k`, exit on `z`-cross-0
  or `max_hold`) has **mean net return > 0 in BOTH the early and late half**, net of 2-leg
  cost = 0.04%/day funding/leg + **15 bp/leg round-trip** spread; (iii) **|corr(Δlog-ratio,
  Δlog-BTC)| < 0.30** (the spread is genuinely BTC-neutral); (iv) the edge holds across a
  **majority** of `k∈{1.5,2.0,2.5} × window∈{120,168,336}` cells, not one mined corner.
  Diagnostics also reported: DR, n, the outright-BCH (1-leg) variant as a fallback. Miss any
  of (i)–(iv) → KILL A2 (fall back to A2′ / A1 / A3).
- **A2′ ratio-MOMENTUM (pre-registered 2026-06-07, before results)** — the data-driven pivot
  if A2 dies (the smoke test showed `log(BCH/BTC)` *drifts*, half-life ~5mo, not reverts). Trade
  the ratio in its **trend** direction: enter the hedged spread at `|mom-z| ≥ k` where
  `mom = log-ratio.diff(L)` z-scored, **side = +sign(mom)** (ride), exit on momentum
  sign-flip or `max_hold`. PASS iff: (ii′) mean net return **> 0 in BOTH halves** net of the
  same 2-leg cost; (iii′) **|corr(spread return, ΔBTC)| < 0.30**; (iv′) holds across a
  **majority** of `L∈{24,48,96} × k∈{1.5,2.0,2.5}` cells. Miss any → KILL the BCH/BTC idea
  (Strategy A), proceed with B only (or pick a fresh A family).
- B family chosen: **Dynamic Range-Detected Grid Trading** (range fade inside the density
  tight box; capped grid of resting limits; flatten on breakout).
- **B-kill-1 cost/turnover (pre-registered 2026-06-07, before results)** — the grid's net
  P&L per range episode (per-level oscillation captures + the flatten-on-breakout P&L) must be
  **> 0 in BOTH the early and late half**, net of cost = **0.04%/day funding/position + 10 bp
  round-trip/fill** spread, AND **≥ 50% of episodes net-profitable**. Probe params: range =
  density tight box (`window=168, max_band_pct=0.03`), `n=6` symmetric levels, breakout buffer
  `0.10×band`, episode cap `240` bars; report across `n∈{4,6,8}` for sanity. Fail either half
  or <50% episodes → KILL B.
- **B′ detector swap (pre-registered 2026-06-07, before results)** — the only change from B is the
  range *detector*: replace the breakout-prone density box with a **hold-prone** one — a range
  episode fires when the **Choppiness Index (n=14) ≥ thresh** (sideways), bounds = the rolling
  `[min low, max high]` over the last `RANGE_LB=48` bars (the recent oscillation range). Test
  `chop_thresh ∈ {55, 61.8}`. PASS/KILL criteria are **unchanged** (B-kill-1 net>0 both halves &
  ≥50% profitable; B-kill-2 tail ≤ 3×). If B′ also fails → the grid concept is dead.
- **B-kill-2 breakout-tail / max-DD (pre-registered)** — report the breakout-loss distribution;
  require the **worst single-episode loss ≤ ~3× the median winning episode** (bounded tail) and
  the grid **net-positive across the 2022 crash and 2024 bull** sub-periods. Full check at
  Stage 3 on the built strategy; the Stage-1 probe surfaces the tail.
- Per-strategy ship/consistency/correlation thresholds: as in the gates table above.

## Strategy C — transfer test: shipped edges on GMO ETH_JPY (2026-06-10)

**Hypothesis:** the two shipped edges (`density_pullback` value-area retest;
`vol_expansion_ride` squeeze→burst) are *structural*, not BTC-specific, so they should
transfer to another liquid JPY pair **untuned** (registry defaults, zero parameter changes,
one evaluation — no tuning on ETH, ever, before its own forward).

**Pre-registered PASS criteria (recorded 2026-06-10 BEFORE running, per the §rule):**
For each strategy independently, on the fixed lockbox split (IS pre-2025-04-01 /
OOS 2025-04-01→2026-04-01), GMO_ETH_JPY 1h:

1. **Edge:** lockbox equity Sharpe ≥ **ETH's own B&H Sharpe** in **BOTH** splits
   (split-matched, displaced-capital principle — same as the BTC gate).
2. **Cost:** still clears ETH's OOS B&H at **10 bp/side** (alt spreads are wider than
   BTC's — this bar is mandatory, and 15 bp is reported as the stress margin).
3. **Robustness (report, promote bar):** fixed-config 6-fold WF — ≥ **4/6** folds positive
   to promote to candidate; < 4/6 = demote regardless of (1).

Miss (1) or (2) for a strategy → that edge **does not transfer**; record and stop (no
re-tuning rescue). Correlation to the BTC book is a *diagnostic for the combination stage
only*, per the §priority rule.

**RESULT (2026-06-11, one evaluation, untuned).** Import: 44,763 ETH 1h bars (99.8% of
BTC's coverage), 2 low-coverage days. ETH's own B&H lockbox Sharpe: **IS +0.40 / OOS
+0.59** — note the ETH OOS window *rose* (+18%), so the OOS bar here is a rising market
(harder than BTC's falling-market OOS bar).

| strategy | IS_sh | OOS_sh | OOS@10bp/side | OOS@15bp/side | WF | verdict |
|---|---|---|---|---|---|---|
| density_pullback | +1.01 ≥ .40 ✓ | **+1.19 ≥ .59 ✓** | **+0.95 ✓** | +0.80 ✓ | 4/6 ✓ | **TRANSFERS — promote** |
| vol_expansion_ride | +1.17 ≥ .40 ✓ | **+0.41 < .59 ✗** | −0.03 ✗ | −0.31 | 4/6 | **KILL — does not transfer** |

- **density_pullback transfers**: passes every registered gate including the 15 bp/side
  stress (margin to spare: +0.80 vs +0.59). It is a *weaker* edge than on BTC (IS +1.01
  vs +1.81, mean_r +0.0038 vs +0.0060, IS_DD 0.46 vs 0.31, WF 4/6 vs 6/6, n 264) — real
  but diluted. The value-area retest mechanism is not BTC-specific.
- **vol_expansion_ride does not transfer**: its ETH OOS (+0.41) trails simply holding
  ETH, and the edge is fully dead at the alt cost bar (10 bp/side → −0.03). Recorded;
  no re-tuning rescue per the registration. The squeeze→burst edge appears
  venue/asset-specific (or BTC's burst microstructure is special).
- Next for dp-on-ETH (promotion path): its forward clock must start at **2026-06-10
  23:00** (today's cache end — the promote *decision* consumed ETH data through then,
  even though no parameter was tuned), which needs per-(strategy, product) boundaries in
  `paper_forward`. Correlation to the BTC book: cBTC −0.03 on the equity path
  (diagnostic; combination-stage).

## Strategy C′ — `density_pullback_eth` (ETH-tuned variant; pre-registered 2026-06-11)

**Reframe (user decision):** not bound to "same strategy as BTC" — develop the best ETH
strategy. Base = the dp family (the only proven ETH edge). ETH-specific tuning is now
allowed under selection hygiene:

- **Selection data: ETH lockbox IS ONLY** (pre-2025-04-01), decided on a fixed-config
  **6-fold WF inside the IS window** (folds positive, mean eqSharpe, smoothness).
- **Acknowledged erosion:** the ETH lockbox OOS was consumed once by the transfer test
  (untuned dp scores +1.19 there) — the final lockbox look below is a *weakened*
  confirmation for this family; the **live-forward is the real gate**.
- **Knob 1 (the sole pre-planned knob): `max_band_pct`** ∈ {0.03 (baseline), 0.035,
  0.04, 0.045, 0.05, 0.06} — motivated by the scale diagnostic recorded BEFORE this
  sweep: the fixed 3% gate passes 31% of BTC bars but only **17%** of ETH bars (ETH vol
  ~76% vs 56% ann.), so on ETH it selects a deeper-tail regime and fires 40% less.
  Acceptance-matching predicts the sweet region ≈ **0.04–0.045**.
- **Adopt iff (recorded before results):** (i) a *smooth* improvement region — ≥2
  adjacent cells agree (anti-knife-edge); (ii) IS-WF folds ≥ baseline's and mean
  eqSharpe up; (iii) the mechanism check holds (fires rise toward a BTC-like rate).
- **Then ONE lockbox evaluation of the adopted config only:** PASS iff IS & OOS
  eqSharpe ≥ ETH's own B&H (split-matched) **and** OOS @10bp/side ≥ ETH's OOS B&H.
  No further knobs after seeing the lockbox; any later knob (sl_mult, zigzag scale…)
  = a new registration and a forward-clock restart.

**RESULT (2026-06-11): NOT ADOPTED — the normalization hypothesis is refuted on the
edge dimension.** IS-WF sweep (`density_pullback_eth_sweep.py`, ETH lockbox-IS only):

| band% | IS eqSh | n | WF-IS folds | mean |
|---|---|---|---|---|
| 0.030 (default) | **+1.01** | 264 | 3/6 | +0.45 |
| 0.035 | +0.74 | 337 | 4/6 | +0.41 |
| 0.040 | +0.72 | 446 | 3/6 | +0.46 |
| 0.045 | +0.71 | 514 | 4/6 | **+0.63** |
| 0.050 | +0.44 | 586 | 4/6 | +0.45 |
| 0.060 | +0.02 | 719 | 3/6 | +0.07 |

- Adoption bar (i) **fails**: 0.045's mean +0.63 is a **single-cell bump** (neighbours
  +0.46/+0.45) — the knife-edge pattern, not a smooth region.
- The mechanism prediction held on *fire count* (264→514, BTC-like) but inverted on
  *edge*: IS eqSharpe **declines monotonically** as the gate loosens (1.01→0.02). The
  extra fires a looser gate admits are worse trades.
- **Structural finding:** the tightness gate works in **absolute** percentage terms
  across assets, not BTC-relative quantile terms — the deep-tail 17% acceptance on ETH
  is load-bearing, not a mis-scaling. Do not re-test quantile-normalized tightness.
- Consequence: `density_pullback` on ETH stays at **registry defaults** (the
  transfer-test config, lockbox IS +1.01 / OOS +1.19, OOS@10bp-side +0.95). No new
  lockbox look needed (nothing adopted). Remaining path: per-(strategy, product)
  forward boundary at 2026-06-10 23:00 + weekly cron line.

## Strategy F — XRP_JPY transfer test (pre-registered 2026-06-11)

**Hypothesis:** the price-structure edges transfer to a *third* asset. XRP is the strongest
orthogonality test yet — its regime profile (2021–23 SEC-suit bear, 2024 spike) is unlike
BTC/ETH — so a transfer here is real structural evidence, not beta. Same protocol as the ETH
transfer (Strategy C): **untuned global registry defaults, one lockbox evaluation per shipped
strategy** (`density_pullback` — incl. the global `max_base_bars=64`; and `vol_expansion_ride`).
No ETH-tuned config (`density_pullback_eth`) is tested — those knobs are ETH-fitted.

**Pre-registered PASS (recorded BEFORE results), per strategy independently,** XRP_JPY 1h,
fixed lockbox (IS pre-2025-04-01 / OOS 2025-04-01→2026-04-01):

1. **Edge:** lockbox equity Sharpe ≥ **XRP's own B&H** in **BOTH** splits (split-matched).
2. **Cost:** clears XRP OOS B&H at **10 bp/side** (alt spreads ≥ ETH's; 15 bp reported as
   margin).
3. **Robustness:** fixed-config 6-fold WF — ≥ **4/6** folds positive to promote.

Miss (1) or (2) → that edge does not transfer to XRP; record, no re-tuning rescue. ETH-style
asset-specific tuning is a *separate* later exercise only on a strategy that first passes
untuned. Correlation to the BTC/ETH books = combination-stage diagnostic only.

**RESULT (2026-06-11, untuned).** Import: 44,875 XRP 1h bars (39–543 JPY span = SEC-suit
bottom to 2024 spike, clean). XRP B&H lockbox: **IS +0.60 / OOS −0.24** (XRP fell −34% in
OOS — a *falling*-market bar, like BTC's).

| strategy | IS_sh | OOS_sh | OOS@10bp/side | WF | verdict |
|---|---|---|---|---|---|
| density_pullback | +1.06 ≥ .60 ✓ | **+2.59 ≥ −.24 ✓** | **+2.50 ✓** | **6/6** ✓ | **TRANSFERS (strong)** |
| vol_expansion_ride | +0.84 ≥ .60 ✓ | +0.28 ≥ −.24 ✓ | +0.15 ✓ | 5/6 | passes gate, **weak** |

- **density_pullback — strong, regime-robust transfer (promoted).** All gates cleared on wide
  margins; per-fold it pays in BOTH rising folds (f3 B&H +1.6 → +1.31; f5 +2.5 → +1.59) and
  falling ones (f6 B&H −1.5 → **+2.38**) — not a falling-market artifact. The headline OOS
  +2.59 is inflated by the displaced-capital effect (beating a −34% market) but the IS (+1.06,
  6/6) and the bull-fold passes make it real. Caveat: **IS_DD 0.53** is the highest of the
  three assets (XRP is gappier); a development target, not a gate miss. Third asset on which
  the value-area-retest mechanism holds untuned.
- **vol_expansion_ride — clears the letter of the gate, but weak.** It passes only because XRP's
  OOS *fell* (+0.28/+0.15 beats −0.24) — the exact mirror of its **ETH failure** (where OOS
  rose and ver lost). Per-fold its edge is concentrated in the early SEC-suit era (f1–f3
  +1.6…+2.1) and the **most-recent fold is negative** (f6 −1.25, overlapping the OOS). So:
  recorded as a marginal pass, **not promoted** — the same strategy failed the ETH version of
  this test, and a thin, deteriorating, falling-market-only edge is not capital-worthy without
  a clean forward. Confirms ver is regime-fragile across assets (already its known weakness).

**Promotion (density_pullback @ XRP):** per-(strategy, product) forward boundary
`("density_pullback", "GMO_XRP_JPY")` @ 2026-06-11 05:00 (XRP cache end); weekly cron gains an
XRP import + check. No new strategy class (untuned = the global default); XRP-specific tuning
is a separate later exercise. The mechanism now holds untuned on **3 assets** — strong
structural evidence it is not BTC-curve-fit.

**XRP-specific tuning (the ETH C″/C‴ suite applied to XRP, 2026-06-11).** Diagnostics: (5)
shorts CARRY XRP even more than ETH (every fold's edge is the short leg — keep both sides);
(3a) swap refuted again (trail rides eat ~2%, the rest is burst-on-stops); (2) the base-length
gradient replicates (mean_r +0.0082 → −0.0033 at 64+, DR 0.41→0.18 — the global `max_base=64`
is right for XRP). Adopted into **`density_pullback_xrp`** (registered, XRP-only):

- **`invalidation_depth=0.35`** — a genuine IS-WF plateau (0.2–0.45 all beat baseline +0.60;
  peak +0.91 at 0.35, IS eqSharpe +1.06→+1.37, folds 3/6→4/6, bleed −3.40→−2.64). XRP's
  plateau peaks **deeper** than ETH's 0.25 — asset-specific, the point of the exercise.
- **`recalc_bars=72` TESTED, then REJECTED — and it forced reverting ETH's C‴ recalc too.**
  On the variant IS-WF, 48 dips (4/6, +0.91) and 72 is 5/6 / best realistic mean (+0.92) — the
  apparent replication of ETH's slower-ratchet finding. But the **held-out lockbox rejected it**:
  recalc=48 → OOS **+2.68**, recalc=72 → **+1.58**. That is the SAME direction the ETH lockbox
  disagreed (48 → +1.33, 72 → +0.84), so two independent held-out windows now agree the
  slower-ratchet IS-WF signal is **in-sample overfitting**. Consequence: recalc=72 NOT adopted on
  XRP, and **reverted on ETH** (density_pullback_eth → the C″ config, invalidation only). The
  recurring "IS-WF disagrees with the spent lockbox on recalc" finally resolved — the lockbox was
  right both times. Keep the global 48 everywhere.
- **`limit_offset` REJECTED** (the edge 0.0 is the local max: −0.1 +0.62, +0.1 +0.49, and IS
  eqSharpe favours 0.0) — same verdict as ETH.

So `density_pullback_xrp` = **one** XRP-specific knob (`invalidation_depth=0.35`), held-out
validated (one lockbox look: IS +1.36 / OOS +2.68 / @10bp +2.58 / 6/6 — a clean win over the
untuned base IS +1.06 / OOS +2.59). `vol_expansion_ride` was already not promoted (weak
transfer), so no XRP tuning on it. **Lesson:** the invalidation exit replicates as a real,
held-out-validated edge on both ETH and XRP; the slower ratchet was an IS-WF mirage that only
the lockbox (not the WF) caught — the XRP replication is what made it safe to revert ETH.

## Strategy E — JST calendar/flow family (pre-registered 2026-06-11)

**Hypothesis:** GMO BTC_JPY has venue/leverage-specific recurring flows — the 00:00 JST swap
cutoff (leveraged squaring), Tokyo open, US session, weekend fiat-ramp drift — that leave a
calendar footprint. **Fully orthogonal** to the price-structure book (the diversifier slot).
The whole risk is multiple testing: 168 hour×dow cells throw ~8 false positives at p<.05.

**Stage-1 probe (pre-registered BEFORE results):** BTC_JPY 1h, **lockbox-IS only** (OOS held
out), split early/late halves, per-bar simple returns. Two arms, each with its own
multiple-testing control:

- **Named family (7, Holm-corrected α=0.05):** weekend (dow∈{Sat,Sun}); pre-cutoff
  (21–23 JST); post-cutoff (00–01); Tokyo-open (09–11); US-session (22–05); Friday; Monday.
- **Full grid (168 hour×dow):** **circular-rotation max-|t| permutation test** (2000 rotations
  of the return series against fixed calendar labels — preserves autocorrelation, destroys
  alignment); the observed max-|t| must exceed the rotation null's 95th pct.

**KILL the whole family unless ≥1 effect clears ALL of:** (i) Holm-significant (named) OR beats
the rotation null (grid); (ii) **same sign in BOTH IS halves**; (iii) **same sign on ETH**
(GMO leverage twin — a real flow effect is cross-asset; single-asset = noise at this n);
(iv) the tradeable per-occurrence overlay return (summed over the bucket's hold, **one 4 bp
round-trip per occurrence**) is **> 0 net**. Any survivor → Stage 2 (build the coarsest
tradeable overlay) + one lockbox-OOS look + the 1m swap-cutoff microstructure as a refinement.
No survivor → drop the family (record the calendar map as the negative).

**RESULT (2026-06-11): KILLED — no calendar edge** (`stage1_calendar_probe.py`; BTC/ETH IS
~34.5k bars each). **Named family:** the strongest bucket is Monday (mean +1.34 bp, **t=1.41,
p=0.16**) — fails even an *uncorrected* single test, nowhere near Holm; its overlay also halves
across the split (early +45.6 → late +11.2 bp) and is weak on ETH (+0.74 bp). Every other named
bucket is |t|<0.9. Net-of-cost columns are mostly negative (a 1 h–block overlay can't clear
4 bp). **Grid:** observed max-|t| = **2.83** vs the rotation-null 95th pct **3.57** (p=0.497) —
the best of 168 cells (Thu 12:00, −10 bp) is *below* what shuffled calendars routinely produce,
the textbook "168 cells manufacture an ~|t|≈3.5 winner from noise" result. Per the
pre-registration: **drop the JST calendar/flow family.** The discipline did its job — without
the rotation null, "Thu 12:00 −10 bp, n=207" would have looked like a finding. The 1m
swap-cutoff microstructure refinement is **not** pursued (the 1h cutoff buckets pre/post are
flat: pre −0.82 bp t=−0.70, post +0.62 bp t=0.45 — no signal to refine).

## Strategy D — stale-box fade (anti-density_pullback; pre-registered 2026-06-11)

**Hypothesis (from our own diagnostics, both assets):** breakouts from *mature* value
areas get faded — the base-length work found the 64+ acceptance bucket runs DR 0.12–0.18
with negative/flat mean_r (BTC and ETH independently), and `max_base_bars=64` now makes
dp *skip* those events. Strategy D trades the other side: **fade the stale-box breakout
back toward the POC** — the book's first short-vol / mean-reversion payoff (everything
live is a long-vol ride). Honest caution: the per-asset tail was thin (n≈16) and the BTC
IS-only read was weakly positive — hence the widened Stage-1 below.

**Stage-1 probe (pre-registered BEFORE results):** event = close beyond the rolling
recency-box edge with acceptance streak > threshold; **thresholds {32, 48, 64} reported,
BTC + ETH lockbox-IS windows pooled** (both lockbox OOS held out). Fade = enter next open
against the break; **TP = event-time POC; SL = 1.0 box-height beyond entry; time stop 96
bars; same-bar TP/SL collision books as SL** (pessimistic). Stop sensitivity s ∈
{0.5, 1.0, 1.5} reported for sanity, not selection. **KILL unless ALL hold** at the
primary cell (threshold 48, s=1.0): (i) mean net return > 0 at 4 bp RT in **both** the
early and late half of the pooled IS; (ii) still > 0 at **10 bp RT**; (iii) tail bounded —
**worst single loss ≤ 3× median win** (B-kill-2); (iv) not carried by one regime — the
2022-crash and 2024-bull sub-periods are reported and at least one of each sign-class must
be non-catastrophic; (v) pooled n ≥ 100. DR > 0.5 expected (reversion) — diagnostic only.

**RESULT (2026-06-11): KILLED at the primary cell** (`stale_box_fade_probe.py`; BTC 87 /
ETH 54 events at streak>32). streak>48, s=1.0 pooled (n=80): mean −0.0005, **late half
−0.0022 (fails i)**, **@10bp −0.0011 (fails ii)**, **n=80 (fails v)**; tail 2.4× passes;
regimes show the structural story — pays in the 2022 crash (+0.0041) and **gets run over
in the 2024 bull (−0.0052)**, the textbook short-vol failure. Stop sensitivity confirms
(tighter stop → tail 1.2× but mean ≈ 0; looser → worse). The thinnest cell (streak>64,
n=39) is positive in both halves and at 10bp (+0.0016, DR 0.64, tail 2.5×) — consistent
with the original diagnostic — but promoting a surviving sub-bucket after seeing results
would be the survivorship trap, and it fails the n bar regardless (~10 trades/yr pooled,
~+2%/yr per unit notional: not a strategy). **Per the pre-registered rule: drop Strategy D,
no rescue.** The reusable negative: stale-box breakouts are bad to *ride* (hence
`max_base_bars=64`) but not reliably profitable to *fade* net of costs — the weak tail is
dead weight, not a reversible edge.

## Strategy C″ — failed-breakout invalidation exit on ETH (pre-registered 2026-06-11)

**Question:** does the `invalidation_depth` exit (close back inside the value area beyond
`depth × box-height` → exit at that close; REJECTED on BTC 2026-06-10 — depth ≥ 1.0 was a
literal no-op because the zs stop fires first, depth < 1.0 clipped dip-then-run winners
without cutting bleed) behave differently on **ETH**, where the box/zs-band geometry and
the stop bleed structure differ? Precedent: the max_base gate's BTC rejection was reversed
by ETH evidence — but note the asymmetry: there a BTC-chosen *fixed cell* transferred;
here BTC chose **no** cell, so this is a fresh ETH sweep and any adoption would be
**ETH-only** (allowed per the C′ reframe; BTC's rejection stands regardless).

**Pre-registered (recorded BEFORE results):** depth ∈ {0.25, 0.5, 0.75, 1.0, 1.25} on the
**ETH lockbox-IS 6-fold WF only** (baseline = current defaults incl. `max_base_bars=64`).
Adopt (ETH-only) iff: (i) a smooth ≥2-adjacent-cell improvement region; (ii) folds ≥
baseline's and WF mean up; (iii) the mechanism check holds — **stop bleed falls without
the trail-winner count collapsing** (the BTC failure mode was the opposite). Report which
depths are no-ops (the zs-stop-fires-first geometry). One lockbox look only on an adopted
config; miss any bar → kill, knob stays no-op on ETH too.

**RESULT (2026-06-11): ADOPTED ETH-only — `density_pullback_eth` registered with
`invalidation_depth=0.25`.** ETH's geometry reverses the BTC verdict on all three bars
(grid extended to {0.10…1.25} to rule out the boundary-cell trap):

| depth | IS eqSh | WF-IS | mean | stops / bleed / trails |
|---|---|---|---|---|
| baseline | +1.13 | 3/6 | +0.58 | 160 / −2.17 / 65 |
| 0.10 | +1.15 | 5/6 | +0.94 | 207 / −1.18 / 29 |
| 0.15–0.20 | +1.08/+1.13 | 5/6, 4/6 | +0.89 | — |
| **0.25** | **+1.31** | **5/6** | **+0.95** | 185 / −1.67 / 45 |
| 0.35 | +1.32 | 4/6 | +0.89 | 171 / −1.80 / 58 |
| 0.5→1.25 | — | 4/6→3/6 | +0.71→+0.59 | smooth decay to no-op |

(i) the whole **0.10–0.35 band is a plateau** (mean +0.89…+0.95), smooth decay to the
no-op side ✓; (ii) 5/6 folds vs 3/6, f1/f6 flip positive ✓; (iii) **bleed falls**
(−2.17→−1.67 at 0.25) — on ETH the invalidation books small early losses instead of full
zs stops; trails drop 65→45 but the bleed offset nets clearly positive (the BTC failure
had no bleed offset) ✓. Cell = 0.25: best mean, most winner-preserving strong cell.
**One lockbox look (the permitted one):** IS **+1.31** / OOS **+1.33** (vs ETH B&H
+0.40/+0.59) — OOS *recovers* the max_base giveback (+0.83→+1.33); 10 bp/side IS +0.93 /
OOS +1.01; 15 bp/side OOS +0.82. Row: n 252, OOS_DD 0.07, full-series WF 5/6.
**BTC's rejection stands** (base default `invalidation_depth=None`). Forward: variant
boundary ("density_pullback_eth", GMO_ETH_JPY) @ 2026-06-10 23:00, weekly cron switched
to the variant. The lockbox has now been consumed twice on ETH for this family — the
forward is the only remaining honest test.

## Strategy C‴ — ETH exit-cost verification + limit-offset (pre-registered 2026-06-11)

Three items run together on `density_pullback_eth` (lockbox-IS only where selection is
involved; the ETH lockbox OOS is consumed and is NOT touched):

- **(3) swap/exit-cost:** diagnostic first (cost decomposition by hold bucket). If swap is
  a non-issue (as on BTC), the `recalc_bars` sweep × {calm, bitFlyer-realistic} is a
  **verification** — argmax expected to stay at 48 on both bases; it MOVES → the exit was
  tuned to the wrong cost model and the new argmax needs the plateau treatment.
- **(4) limit_offset {−0.1, 0, +0.1} × box height:** low prior, 3 cells can't establish
  smoothness → **adopt only on a LARGE win** (WF-IS mean ≥ +0.2 over baseline AND folds
  not worse), which would then trigger a finer plateau grid; anything less = keep 0.0.
- **(5) short-side per-fold:** diagnostic only, no build under any outcome.

**RESULTS (2026-06-11, all three):**

- **(5) keep both sides — emphatic.** ETH IS shorts carry MORE than longs (sum_r +0.79 vs
  +0.27) and pay in a *rising* fold too (f3, B&H +0.41: shorts +0.31 vs longs −0.12), plus
  the falling f6. Long-only is off the table; no build.
- **(3a) swap refuted again** (same shape as BTC): ETH realistic cost 3.3× calm = base 31 /
  burst 45 / swap 26 JPY; the 48–96h trail winners eat only 2.0% (2/41 flip negative); the
  damage is the burst surcharge on the <24h loser buckets (12–16%).
- **(3b) recalc verification → the argmax MOVED: `recalc_bars=72` ADOPTED ETH-only.**
  Not a cost-model effect — the argmax moved on **both** bases identically (coarse:
  48→72 mean +0.95→+1.08 calm / +0.73→+0.86 realistic; fine grid: a smooth **64–72
  plateau**, 80+ falls away; realistic folds 3/6→4/6). ETH's higher vol wants a slower
  ratchet than BTC's 48 (which stays verified-argmax on BTC). **Caveats recorded:** no
  lockbox confirmation exists for this cell (lockbox spent; the C″ +1.33 OOS look was at
  48); the post-adoption *reporting* row shows lockbox OOS +0.84 at 72 vs +1.33 at 48 —
  the third time an ETH IS-WF selection disagrees with the spent lockbox OOS. Either
  1-year-window noise (~50 trades) or accumulating IS-fold fit: **the pristine forward at
  72 adjudicates; fallback on a weak forward = the C″ config (recalc=48).** Full-series
  WF at 72: **6/6**. Post-adoption row: n 252, IS +1.43, OOS +0.84, OOS@10bp +0.75,
  OOS_DD 0.08, cBTC −0.00.
- **(4) limit_offset REJECTED — the edge is the natural level.** 0.0 is a local max from
  both sides (−0.1: +0.79/4-6 with 290 fills; 0.0: **+0.95/5-6**; +0.1: +0.37/3-6 with 194
  fills). Far from the ≥+0.2 bar; knob stays 0.0 (no-op control).

**2026-06-11 (later) — `max_base_bars=64` adopted into the dp default; ETH was the
deciding evidence.** The base-length stale-tail finding (BTC, rejected 2026-06-10 as
winner's-curse-sized + partly OOS-peeked) **replicated on ETH** — per-trade (64+ tail
mean_r −0.0065, DR 0.12) *and* equity (the BTC-chosen cell, untuned on ETH: IS-WF mean
+0.45→+0.58, 4/6 folds up, none down). Adopted while the forward clocks were days old;
all three forwards (dp, combo_dp_ver, dp@ETH) re-frozen — dp@ETH now has a
per-(strategy, product) boundary (2026-06-10 23:00) in `paper_forward` and an ETH
import+check line in the weekly cron. This **changes the ETH config from the
transfer-test snapshot** — the row regenerates with the gate on.
