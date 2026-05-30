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

## 6. When to Revert vs Investigate

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

## 7. What the Judge Weighs

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

## 8. Iterated Debate Protocol

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