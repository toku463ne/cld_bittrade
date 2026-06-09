# Candidate benchmark table

At-a-glance comparison of the multi-position strategy candidates, all on **one consistent
basis** (snapshot **2026-06-08**, GMO_BTC_JPY 1h; `vol_expansion_ride` row refreshed
**2026-06-10**). Regenerate any row with
`python -m src.backtest.analysis.benchmark_table_row --strategy <name>`.

> **2026-06-08:** `density_pullback` retuned — (1) **log recency-weighted** value-area
> box (`recency=1.0`, walk-forward-robust: +ve in all 6 folds, beats B&H 5/6 vs 4/6);
> (2) **`limit_window` 24→6** — at ~1 day the retest limit caught delayed reversals
> crashing back through the edge (falling-knife fills), not prompt retests; 6 is the
> swept balance (best IS Sharpe, 6/6 folds, OOS held, ~47 stale trades dropped). Its
> row below is recomputed. (`cBTC`/`cDP` for the other rows are vs the prior dp
> definition and are non-gate diagnostics — left as-is.)
>
> **2026-06-10:** `vol_expansion_ride` gained the **two-sided-burst filter**
> (`skip_contra_extreme=1`, now default) — skip an entry whose squeeze→2×ATR burst bar
> made an extreme *against* the ride side over the prior bar (a directionless/outside
> expansion). Selected inside-sample on the 6 WF folds (per-trade lift +ve 6/6). Its row
> below is recomputed: drops ~30% of trades (526→369) yet **IS Sharpe +1.56→+1.76**,
> **IS_DD nearly halves 0.41→0.24**, DR/mean_r up, OOS ~flat. See `vol_expansion_ride.md` §5.

- **Split:** the fixed **lockbox** (`split_lockbox`) — IS = pre-2025-04-01, OOS =
  2025-04-01 → 2026-04-01.
- **IS / OOS Sharpe** = annualised mark-to-market **equity** Sharpe at the default **4 bp**
  round-trip cost. **OOS@10bp** = OOS equity Sharpe at a realistic **10 bp** round-trip —
  the cost-robustness check (the recurring edge-killer on this branch).
- **DR** = win rate, **mean_r** = mean net return per trade (both signal-level diagnostics,
  *not* ship criteria). **IS_DD / OOS_DD** = max drawdown of the per-trade-return curve.
- **WF** = fixed-config 6-fold walk-forward (full series, 4 bp); folds with positive eqSharpe.
- **cBTC / cDP** = bar-return correlation to BTC / to density_pullback — *diagnostics for the
  later combination stage, not idea-stage gates*.
- **Benchmark:** B&H lockbox Sharpe **IS +0.55 / OOS −0.16** (so OOS@10bp clears B&H if > −0.16).

| candidate | n | IS_sh | DR | IS_DD | mean_r | OOS_sh | OOS_DD | OOS@10bp | WF | cBTC | cDP | status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **density_pullback** | 428 | **+1.81** | 0.36 | 0.31 | +0.0060 | **+1.26** | 0.18 | **+1.07** | **6/6** | +0.06 | +1.00 | **ship✓** |
| **vol_expansion_ride** | 369 | **+1.76** | 0.24 | 0.24 | +0.0051 | +1.25 | 0.11 | +0.97 | 4/6 | −0.06 | +0.18 | **ship✓** |
| rsi_extreme_ride | 914 | +1.27 | 0.34 | 0.61 | +0.0042 | +0.97 | 0.45 | +0.71 | 5/6 | −0.18 | +0.16 | **demoted** (≈ null OOS) |
| random_hedge_volfilter | 518 | +0.98 | 0.36 | 0.27 | +0.0028 | +1.69 | 0.09 | +1.34 | 6/6 | −0.09 | +0.15 | **NULL floor** (seed0; ⚠ below) |
| **zigzag_bounce_ride** | 564 | +0.32 | 0.39 | 0.71 | +0.0029 | +1.05 | 0.38 | +0.86 | **6/6** | −0.08 | +0.17 | candidate |
| **density_multi_breakout** | 439 | +1.03 | 0.40 | 0.56 | +0.0063 | +0.32 | 0.42 | +0.20 | 5/6 | +0.03 | +0.68 | weak (cost) |
| random_hedge (null) | 684 | −0.15 | 0.37 | 0.70 | −0.0006 | +0.55 | 0.12 | +0.08 | 4/6 | +0.03 | +0.14 | null baseline |

## ⚠ Null-floor correction — the lockbox OOS is directional, so B&H is the wrong floor

`random_hedge_volfilter` is a **random-entry** control, yet it posts a huge lockbox OOS
(seed-0 +1.69). Diagnosis (20-seed × 3-window sweep): **(a)** seed-0 is a lucky draw — the
20-seed mean is **+0.91**, not +1.69; and **(b)** even that +0.91 is *not* skill — a hedged
pair + ride exit lets the trend-aligned leg run, so it beats B&H **85–100% of the time in
*bear* windows but only 30% when B&H rises**. The recent OOS windows are directional/down.

**Consequence: the honest null floor is the random hedge (lockbox 20-seed mean IS +0.77 /
OOS +0.91), not B&H (−0.16).** Edge = **lift over that null**:

| candidate | IS lift / null | OOS lift / null |
|---|---|---|
| density_pullback | **+1.04** | **+0.35** |
| vol_expansion_ride | **+0.99** | **+0.34** |
| rsi_extreme_ride | +0.51 | **+0.06** (≈ null) |
| zigzag_bounce_ride | **−0.45** (< null) | +0.13 |
| density_multi_breakout | +0.26 | **−0.60** (< null) |

So on this window only **density_pullback** and **vol_expansion_ride** carry real OOS entry
edge — and the two are now near-tied on IS lift (dp +1.04 vs ver +0.99 after the two-sided-burst
filter) and on OOS (+0.35 vs +0.34); density_pullback keeps a slim overall lead (highest raw IS
and 6/6 folds vs ver's 4/6). **rsi_extreme_ride is ≈ the
null**, and **zigzag_bounce_ride / density_multi_breakout are at or below it**. The plain
`OOS_sh` column above is inflated by the window's directionality — read the **lift-over-null**
before trusting any OOS Sharpe here.

\* `random_hedge_volfilter` (and the `random_hedge` null) are **seeded** (seed=0); their
single-seed lockbox numbers are rosier than the 8-seed mean — treat as indicative, not final.
All others are deterministic.

## Read at a glance

- **Read OOS as lift-over-null, not vs B&H** (the ⚠ section): the directional window gives a
  random hedge OOS +0.91, so several "candidates" barely clear it.
- **density_pullback** (recency=1.0 box, prompt limit_window=6) is the strongest on entry edge
  (lift over null **IS +1.04 / OOS +0.35**) AND the most balanced: highest IS (+1.81), **6/6** folds,
  cost-robust (OOS@10bp +1.07), and the only *shipped* one. (Dropping the 24-bar window's stale
  knife-catches nudged IS DD up slightly to 0.31 — the cost of window=6 over 12.)
- **vol_expansion_ride** is a near-tied second on entry edge (lift **IS +0.99 / OOS +0.34**)
  after the **two-sided-burst filter** (`skip_contra_extreme=1`): it cut ~30% of trades while
  raising IS (+1.76) and **nearly halving IS_DD to 0.24** (now below dp's 0.31), cost-robust
  (OOS@10bp +0.97) — but still only 4/6 folds (weak in raging bulls).
- **rsi_extreme_ride** is **≈ the null on OOS** (lift +0.06) despite a nice headline +0.97 — its
  OOS edge mostly evaporates against the right floor (DD developed via `max_slots=3`).
- **zigzag_bounce_ride** is **below the null on IS** (−0.45); **density_multi_breakout** is **below
  the null on OOS** (−0.60) and not cost-robust — both effectively no entry edge here.
- **DR is sub-0.5 for all** (trend-ride payoff). Per CLAUDE.md, DR/mean_r are diagnostics only.

## Caveats & regeneration

A lockbox snapshot, not a final verdict — the lockbox has been reused across ideas (erodes it),
so the **finalist still needs a fresh live-forward** (`paper_forward`) before real capital. Single
IS/OOS split + 6 coarse folds; ride-exit candidates share the same exit (correlations in `cDP`).
Regenerate any row with `python -m src.backtest.analysis.benchmark_table_row --strategy <name>`
(lockbox basis; validated to reproduce the committed rows). Seeded rows (`random_hedge*`) are
seed-0 and not reproduced by that deterministic script — see the ⚠ note.
