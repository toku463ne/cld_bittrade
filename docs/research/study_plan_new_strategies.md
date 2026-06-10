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
