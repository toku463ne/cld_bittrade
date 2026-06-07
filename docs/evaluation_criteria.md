# Sign / Strategy Evaluation Criteria

This document defines how empirical evidence is judged when reviewing a sign or
strategy change. **All agents in `.claude/agents/` reference this file** so
their reasoning shares one rubric.

When in doubt, the question is always: **does the evidence justify the change,
on the dimensions that matter for live trading?**

> **Note**: Adapted from
> [cld_trade_advisor/docs/evaluation_criteria.md](https://github.com/toku463ne/cld_trade_advisor/blob/main/docs/evaluation_criteria.md)
> for BTC/JPY scalping. Key changes: FY → monthly periods; N225 regime →
> BTC ATR regime; kumo/ADX regime → ATR regime; product = FX_BTC_JPY only.

---

## 1. Evidence Sources (in order of weight)

| # | Source                              | What it measures                                              | Where it lives                                       |
|---|-------------------------------------|---------------------------------------------------------------|------------------------------------------------------|
| 1 | Multi-month benchmark (training set) | Aggregate DR and event volume across training months         | `src/analysis/benchmark.md` § Multi-Month Benchmark  |
| 2 | OOS backtest (most recent 20%)      | Out-of-sample directional rate, regime-gated                  | `src/analysis/benchmark.md` § OOS                    |
| 3 | Regime analysis (ATR bear/bull)     | Cell-level DR / mag_flw / mag_rev / EV with p-value gate      | `src/analysis/benchmark.md` § Regime Analysis        |
| 4 | Score calibration                   | Spearman ρ between `sign_score` and signed return + Q1–Q4 EV  | `src/analysis/benchmark.md` § Score Calibration      |
| 5 | Theoretical/visual rationale        | The reason we expected the change to help                     | code comments, session notes                         |

Empirical evidence (rows 1–4) **outweighs** theoretical rationale (row 5). A
visually compelling pattern that does not show up in multi-month DR is not
sufficient to keep a change.

---

## 2. Core Metrics

- **DR** — directional rate. Fraction of fires that move in the expected
  direction over the evaluation horizon (next confirmed zigzag peak within
  ~30 bars on the selected timeframe).
- **n_events** — sample size of fired events.
- **mag_flw / mag_rev** — average magnitude of the move when the event went
  forward vs reversed.
- **EV** — expected value: `dr × mag_flw − (1 − dr) × mag_rev`. Primary
  ranking metric.
- **perm_pass** — permutation-test pass rate (DR vs shuffled baseline).
- **Spearman ρ** — score-to-return rank correlation.

---

## 3. Materiality Thresholds

A change is **material** only if at least one of these holds:

| Dimension      | Material if …                                                                                      |
|----------------|----------------------------------------------------------------------------------------------------|
| DR change      | abs(ΔDR) ≥ **1.0 pp** at n ≥ 1,000 events, or ≥ **2.0 pp** at smaller n                          |
| n_events       | Drop of ≥ 50% — must be justified by a DR or EV lift, else the filter is cutting signal not noise  |
| EV             | Sign change (positive ↔ negative) or magnitude change ≥ 0.3 pp                                    |
| OOS            | Regime-gated Δ DR ≥ 3 pp vs all-events DR                                                         |
| Calibration    | Spearman ρ flips sign, or moves between [-0.05, +0.05] and outside                                |

Changes below these thresholds are noise; do not act on them in isolation.

---

## 4. Decision Matrix

For a sign change being evaluated against rebench results:

| DR change  | n change            | Verdict                                                                          |
|------------|---------------------|----------------------------------------------------------------------------------|
| ↑ ≥ 1 pp   | stable / mild drop  | **Keep**                                                                         |
| ↑ ≥ 1 pp   | drop ≥ 50%          | **Keep** if strategy can tolerate the lower fire rate; check OOS                 |
| flat       | drop ≥ 50%          | **Revert** — filter cut volume without quality lift                              |
| ↓ ≥ 1 pp   | any                 | **Revert or isolate** — find which gate within the change caused the regression  |
| ↓ < 1 pp   | stable              | **Watch** — re-evaluate after one more month of data                             |

---

## 5. Common Failure Modes (the Critic's checklist)

Failure modes 1–7 apply to all changes. Items 8–10 apply specifically to
changes that touch entry/exit timing against band-based exits (ATR trail,
fixed TP/SL) — where IV lifts systematically over-predict live A/B performance.
Item 11 applies to per-bar decision-factor UI. Item 12 applies to
slot-constrained, skip-not-queue portfolio backtests.

1. **Sample-size illusion**: n < 100 events in a cell is too noisy to read DR
   from. Aggregate before drawing a conclusion.

2. **Regime overfit**: a gate trained on a low-volatility window will look
   great in-sample and fail in high-volatility regimes (or vice versa). Always
   check bear_DR and bull_DR separately (ATR regime split).

3. **Definition drift**: the analysis used to motivate a gate often uses a
   slightly different definition than the gate as implemented. Re-check that
   the live detector matches the benchmark definition exactly.

4. **Filter masquerading as signal**: cutting events 65% and keeping DR flat
   means the filter caught nothing useful — and may have removed real signal
   by chance.

5. **Score-calibration over-reading**: low Spearman ρ in `benchmark.md`
   § Score Calibration is **necessary but not sufficient** to retire
   `sign_score` from the ranking key. ρ ≈ 0 measures direction-to-next-zigzag,
   but `sign_score` may encode magnitude information that direction-ρ misses
   and that matters under band-based exits (ATR trail, fixed TP/SL).
   **Rule:** treat ρ ≈ 0 as a *flag to investigate*, not a green light to
   drop `sign_score`. Any score-retirement proposal MUST clear an A/B
   falsifier — |ΔSharpe| ≥ 0.05 with positive sign across the full training
   period — before shipping. The honest ranking is `EV` *then* `sign_score`,
   not `EV` alone.

6. **Compounded gates**: stacking state-machine + persistence + hysteresis +
   crossover gates makes any single bad gate hard to detect. Add gates one at
   a time and rebench after each.

7. **Forward-looking leakage**: a regime label that uses any data from after
   `fire_date` will inflate DR. Confirm regime snapshot is built strictly from
   history available at fire time.

8. **Wait-IV survivor-inflation trap**: when an IV measures "remaining move to
   the original target" (e.g. peak − entry_K), a positive K>0 lift can come
   from either (a) survivor magnitude inflation — events that drop out by K had
   small original magnitudes — or (b) the dropped cohort being identifiable in
   real time. Only (b) supports a live gate. Discriminate by asking: under the
   live exit, what does the "would-be-dropped" cohort earn vs the
   "would-be-kept" cohort? If the dropped cohort recovers under the live exit,
   mechanism (a) dominates and the IV's lift is not ship-able.

9. **Band-based exit definition drift**: any IV that measures alpha against a
   fixed target (peak, original_signed_return, fixed-horizon return)
   over-counts the alpha available to a band-based exit (ATR trail, fixed
   TP/SL). The live exit truncates the path at TP/SL on intermediate bars —
   alpha after the band fires is unrealisable. Any change against a band-based
   exit MUST be validated via a faithful composite walk probe (simulate the
   live exit bar-by-bar with the proposed gate) before A/B is authorized. The
   TP-within-K probe alone is NECESSARY BUT NOT SUFFICIENT.

10. **IV-to-A/B optimism on entry/exit timing**: IV lifts for entry-timing or
    exit-timing changes against ATR-trail / fixed-TP/SL class exits
    systematically over-predict live A/B performance. Treat IV evidence as
    *upper bound* on live impact, not best estimate. Probe-first is the default
    path; direct-to-A/B requires explicit justification.

11. **Multi-factor display dilution**: a UI that shows several weak factors
    side-by-side invites the reader to average them as equal evidence. A
    per-bar decision-factor display (e.g. the Backtest tab metrics panel) is
    honest only if every factor obeys all of:
    - **Measured strength shown** — each factor renders with its effect size
      (ΔEV / ΔDR / ρ), never a bare label.
    - **Sample size shown; n ≥ 100 to read as a factor** — a factor backed by
      n < 100 renders greyed and captioned "too small to read".
    - **Provenance link** — each factor names the `benchmark.md` section or
      `docs/analysis/` artifact it comes from.
    - **No per-bar claim for cell-level aggregates** — regime EV/DR, sign
      calibration ρ, and any (sign, ATR regime) cell statistic are NOT
      per-bar; they must sit in a visually separate "context, not bar-specific"
      block.
    - **No A/B-negative factor** — a factor that lost money in a faithful
      strategy A/B is not shown on the decision surface at all.
    - **Production vs experimental tier** — factors validated OOS render in
      the production tier; in-sample-only or mixed-evidence factors render in
      a visually distinct experimental tier.

12. **Slot-contention / fill-order luck (skip-not-queue books)**: when a
    backtest fills a fixed number of capacity slots and **SKIPS** candidates
    when full (rather than queueing them), the realized trade set is **one
    fill-order path**, and that order is an unmeasured variance source. Two
    binding consequences:
    - **Use a fill-order PERMUTATION null, not a day-resampling bootstrap**,
      to judge any selection/ordering intervention. Shuffle the within-bar
      candidate order K times (≥200) and read the arm's percentile in the
      resulting distribution.
    - **Don't re-apply an internal cap externally.** If a simulator's trade
      output is sparse vs the raw signal, check for an internal cap that SKIPS
      rather than queues before concluding "thin choice set." Feeding the
      already-capped output into a second selector double-counts the cap.
    - **Capacity vs selection asymmetry**: a structural change (more slots) can
      certify at current n via a paired shuffle null because it moves the whole
      distribution; a selection rule cannot, because it is a single favorable
      draw within the band.
    - **Paired null beats single-arm-vs-null for ordering rules**: scoring one
      deterministic ordering against the shuffle null conflates the rule with
      its lucky draw. Any "ordering beats baseline" claim must be confirmed by
      a paired shuffle null before it is believed, even when the single-arm
      clears per-month and OOS gates.

---

## 6. Variant Selection (A/B between strategy/sign variants)

This section governs choosing between **variants of the same strategy** — one
knob changed at a time (e.g. time-at-price vs volume-acceptance density profile,
or `vol_transform` ∈ {linear, sqrt, log}). It is about *generalization*, not
in-sample fit. **Pre-register these rules in code/notes BEFORE seeing variant
results**; do not redefine the metric after the numbers land.

### 6.1 The trap: single-split OOS level is not a selection criterion

- A high OOS Sharpe on one split — or **OOS rising above IS** — is **not** a
  positive signal. It is as likely to be a favorable-regime accident as a
  structural edge. Never pick a variant because its single-split OOS "looks good"
  or because OOS > IS.
- The generalization signal is **low IS→OOS degradation across multiple
  windows**, not the absolute OOS level on one window.

### 6.2 Degradation is a GATE, not the ranking objective

Walk-forward efficiency `WFE = OOS_Sharpe / IS_Sharpe` is a useful **overfitting
gate** but a poor selection *objective*, for two reasons that bite hardest in
this project's low-frequency regime:

1. **Unstable at small IS Sharpe.** Per-trade Sharpe has SE ≈ `√((1+0.5·SR²)/n)
   ≈ 1/√n`. At IS Sharpe ≈ 0.20 on n ≈ 90, SE ≈ 0.10 — the *denominator* carries
   ~50% relative error, so a ratio of two such estimates is far noisier than
   either. `0.18/0.20 = 0.90` and `0.10/0.20 = 0.50` are **not statistically
   distinguishable** at these n. An IS floor does not fix this; 0.20 is not
   bounded away from zero relative to its own SE.
2. **Rewards low IS.** A weak-but-flat variant (IS 0.18 → OOS 0.16, WFE 0.89)
   scores above a stronger one that gives a little back (IS 0.40 → OOS 0.20, WFE
   0.50), even though the latter has higher OOS *and* IS. Retention is a
   *diagnostic*, not the objective; optimizing it re-creates "stable mediocrity"
   above the floor.

### 6.3 The three-criteria rule (AND, kept separate)

Select a variant only if **all three** hold; never collapse them into one ratio:

| Criterion | Role | Rule |
|-----------|------|------|
| **IS floor** | exclude dead variants | IS Sharpe ≥ a pre-registered minimum (and > 0) |
| **WFE gate** | exclude overfit variants | median `OOS/IS` across windows ≥ **0.5**; reject any window with `OOS Sharpe < 0` (the existing OVERFIT flag) |
| **Absolute floor** | require a real edge | pooled-OOS Sharpe ≥ Buy-and-hold BTC/JPY (the ship gate in CLAUDE.md § Ship criteria) |

**Ranking objective for survivors must be ratio-free** — use `min(IS, OOS)`
across windows, or the **OOS Sharpe lower confidence bound**. Both prefer
"high *and* retained" and punish both low IS and large drops without dividing by
a noisy denominator.

### 6.4 Sample size is the binding constraint, not split topology

density_breakout fires ≈ 24 trades/year on GMO 1h. Consequences:

| OOS window | ~trades | SE(Sharpe) | usable? |
|-----------|---------|-----------|---------|
| ~4 months | ~8 | 0.35 | no |
| ~1 year | ~24 | 0.20 | barely |
| ~1.7 year (3-fold) | ~40 | 0.16 | noisy |
| **pooled OOS** (~120) | ~120 | **0.09** | yes |

- A **per-window** Sharpe (3-fold *or* 5-fold) is too noisy to anchor a
  trustworthy ratio. At ~24 trades/yr, walk-forward **degenerates into ≈3 folds
  anyway** (IS ≥ ~2y, non-overlapping OOS ≥ ~1y) — so "3 fixed periods" and
  "walk-forward" converge on 1h. The split topology is not where the win is.
- **Where the statistical weight actually goes:**
  1. **Pool OOS trades across folds**, then judge the pooled OOS Sharpe with a
     permutation / bootstrap CI (n ≈ 120, SE ≈ 0.09) — one trustworthy number
     instead of several noisy ones.
  2. **Lean on per-*period* consistency, not per-*fold* — but the period must
     scale with trade frequency.** A consistency sign-test is only meaningful if
     each period holds *several* trades; otherwise per-period non-neg% collapses
     into the per-trade win rate and tells you nothing new. The CLAUDE.md table's
     "1 week" unit for 1h is **wrong for a ~24-trade/yr trend-ride** — a week
     holds ≈ 0.5 trades, so weekly buckets are mostly empty and the "fails ≥80%
     consistency" verdict they produce is a period-length artifact, not a real
     defect (this exact false-negative hit density_breakout). **Frequency-adaptive
     rule:** pick the coarsest period that still gives enough buckets — target
     **≥ ~5 trades/period AND ≥ ~12–15 periods**. At ~24 trades/yr that is the
     **quarter** (≈6 trades/period, ~20 periods over 5y), not the week. Report the
     consistency gate at that granularity; coarser still (year, n=5) is a sanity
     check only — too few buckets to gate on. Per-window folds remain a coarse
     sign check, never a ratio magnitude.
  3. **Make the consistency threshold RELATIVE, not an absolute 80%** (revised
     2026-06-07). The original gate ("≥ 4/5 periods non-negative" → 80%) is an
     *absolute* bar inside a relative-benchmark framework, and it is mis-calibrated
     two ways: (i) "4/5" is 80% at n=5 but does not scale — applied to ~17 quarters
     it is a stiffer demand; (ii) **buy-and-hold itself is non-negative in only ~62%
     of in-sample quarters**, so 80% asks the strategy to be *more consistent than
     the thing it is benchmarked against* — impossible for a lumpy trend-ride /
     diversifier (per-trade DR ~0.35, edge carried by a few big winners) even when
     the edge is real. The gate is therefore **relative**: the strategy's
     quarterly non-negative fraction must be **≥ buy-and-hold's own** over the same
     window. This still fails a genuinely one-regime strategy (it would trail B&H's
     consistency) and matches the Sharpe gate's displaced-capital logic, without the
     absolute bias against diversifier payoffs. Implemented in
     `src/backtest/cycle.py::_quarter_consistency`.
  4. **Test the entry-edge where n is large.** The density *definition* is an
     entry question; measure its degradation on 5m/15m (100k+ bars, thousands of
     fires) even if the variant is traded on 1h. Caveat: microstructure differs,
     so transfer is not guaranteed — use it to rank the *definition's*
     generalization, then confirm on the traded timeframe.
  5. **Gate (a) is both-splits, equity-Sharpe, split-matched** (tightened
     2026-06-07). Use the annualised **equity-path** Sharpe (scale-invariant →
     identical for single- and multi-position; the old single-position path
     compared a per-trade Sharpe to *0*, not B&H) and require it ≥ B&H in **both**
     the IS and OOS splits, **each split vs its own B&H** (IS-vs-IS, OOS-vs-OOS).
     Split-matching is essential: in the current OOS window BTC fell (B&H OOS
     Sharpe ≈ −0.60), so the OOS leg is cleared by beating a *falling* market — the
     displaced-capital principle. Never compare OOS strategy Sharpe to *IS* B&H
     (the apples-to-oranges trap). Implemented in `src/backtest/cycle.py`.

### 6.5 Walk-forward vs fixed lockbox — complementary roles

- **Walk-forward** (fixed-config across folds — *not* per-fold re-selection)
  measures structural stability across regimes; this is the tool for comparing
  variants. Anchored WF *with* re-selection tests the *selection process*, not a
  single structure, so it answers a different question.
- **One untouched lockbox** (a final holdout never looked at during development)
  is the only source of an *honest* final estimate. **Never iterate against the
  walk-forward** — doing so re-selects configs that flatter the WF, which is
  overfitting to it. WF measures robustness; the lockbox produces the number.
- Fixed named-regime splits are preferable when the question is "does it survive
  the 2022 bear?" rather than average behavior.

#### 6.5.1 Idea-stage lockbox (added 2026-06-07)

For triaging **new** ideas fast, use a **fixed pre-registered historical lockbox** as
the OOS instead of waiting weeks for live paper-forward: tune only on bars **before
2025-04-01**, evaluate once on **2025-04-01 → 2026-04-01** (`split_lockbox` in
`sign_benchmark.py`; ~2 months after it are a live buffer). Rationale: a never-tuned-on
historical year is an honest OOS available *instantly*, which matters in the
idea/exploration stage where most candidates die. Discipline / limits:

- **Per idea, evaluate the lockbox once** — don't tune against it (that turns it into
  in-sample). Re-cutting it idea after idea slowly erodes it (multiple comparisons), so
  it is a *triage* holdout, not a final certificate.
- The eventual **finalist** (the idea that survives to get real capital) still earns a
  **fresh live-forward** check (`paper_forward`) — by then the lockbox has been "used."
- The already-shipped strategies keep the canonical most-recent-20% split
  (`split_in_out_sample`); the lockbox is for **new** idea evaluation, not a re-scoring
  of past results (that would be goalpost-moving, §6.5).

### 6.6 One knob at a time

Change exactly one variable vs the baseline per A/B (mirrors § 5 item 6,
"Compounded gates").
A variant that alters the profile *and* the exit *and* a filter cannot have its
result attributed; build the A/B sibling to differ in a single dimension so any
degradation is traceable to that dimension alone.

---

## 7. When to Revert vs Investigate

- **Revert wholesale** when:
  - The change combined multiple gates and DR fell ≥ 3 pp.
  - There is no clear path to isolating which gate is responsible without
    several rebench cycles.
  - The change's theoretical motivation was already weak.

- **Investigate first** when:
  - One known gate looks suspicious (e.g. ATR threshold too strict).
  - The new event volume is healthy and only DR is off.
  - Sub-population behavior may explain the aggregate (a single regime cell
    is dragging things down).

---

## 8. What the Judge Weighs

Final verdicts are one of:

- **Accept** — empirical evidence clears § 3 thresholds and decision matrix
  in § 4 favors the change. Confidence: H / M / L.
- **Reject** — change regresses on the primary dimension (DR or EV) and § 4
  recommends revert.
- **Insufficient evidence** — sample too small, evidence conflicts across
  sources, or a known gap (calibration not run, OOS incomplete). Specify
  what would resolve it.

The judge MUST state confidence (H / M / L) and the single piece of
evidence that would flip the verdict — this keeps the rubric falsifiable.

---

## 9. Iterated Debate Protocol

When a sign/strategy decision is non-trivial, the agent cycle can run
multiple times via the `/sign-debate <topic>` slash command (see
`.claude/commands/sign-debate.md` for the full spec).

Per iteration: `analyst → proposer → critic → judge`. If the judge
returns "Insufficient evidence," the **Next action** field is executed
autonomously — running an existing analysis script, reading the relevant
benchmark section, or writing a small new one-off script — and the
resulting evidence is fed into the next iteration. The cycle stops on
Accept, Reject, max iterations (default 3), or when the next action
falls outside the autonomous scope (e.g. modifying detector code or
running a full rebench).

This protocol exists so single-round "we need decomposition data first"
verdicts do not stall the workflow on the user's manual intervention.
The judge still produces falsifiers; the harness just resolves the
falsifier autonomously when it can.