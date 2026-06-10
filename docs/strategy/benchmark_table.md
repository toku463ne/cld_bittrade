# Candidate benchmark table

At-a-glance comparison of the multi-position strategy candidates, all on **one consistent
basis** — every deterministic row regenerated in a **uniform snapshot 2026-06-10**,
GMO_BTC_JPY 1h. Regenerate any row with
`python -m src.backtest.analysis.benchmark_table_row --strategy <name>`.

> **2026-06-08:** `density_pullback` retuned — (1) **log recency-weighted** value-area
> box (`recency=1.0`, walk-forward-robust: +ve in all 6 folds, beats B&H 5/6 vs 4/6);
> (2) **`limit_window` 24→6** — at ~1 day the retest limit caught delayed reversals
> crashing back through the edge (falling-knife fills), not prompt retests; 6 is the
> swept balance (best IS Sharpe, 6/6 folds, OOS held, ~47 stale trades dropped). Its
> row below is recomputed.
>
> **2026-06-10:** `vol_expansion_ride` gained the **two-sided-burst filter**
> (`skip_contra_extreme=1`, now default) — skip an entry whose squeeze→2×ATR burst bar
> made an extreme *against* the ride side over the prior bar (a directionless/outside
> expansion). Selected inside-sample on the 6 WF folds (per-trade lift +ve 6/6). Its row
> below is recomputed: drops ~30% of trades (526→369) yet **IS Sharpe +1.56→+1.76**,
> **IS_DD nearly halves 0.41→0.24**, DR/mean_r up, OOS ~flat. See `vol_expansion_ride.md` §5.
> Then **`expand_mult` 2.0→2.5** (squeeze×expand sweep, §7): a smooth 5/6-fold choice that
> rescues the early-2021 regime, cutting turnover further (369→**236**) and DD (IS 0.24→**0.17**,
> OOS 0.11→**0.05**) and lifting OOS (+1.25→**+1.28**) for a ~0.2 IS-Sharpe giveback
> (+1.76→**+1.51**). The row below is this final state.

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
| **combo_dp_ver** | 664 | **+2.20** | 0.31 | 0.38 | +0.0061 | **+1.57** | 0.18 | **+1.32** | **6/6** | +0.03 | +0.91\*\* | **ship✓ (portfolio)** |
| **density_pullback** | 428 | **+1.81** | 0.36 | 0.31 | +0.0060 | **+1.26** | 0.18 | **+1.07** | **6/6** | +0.06 | +1.00 | **ship✓** |
| **vol_expansion_ride** | 236 | **+1.51** | 0.25 | 0.17 | +0.0063 | +1.28 | 0.05 | +1.03 | 5/6 | −0.06 | +0.10 | **ship✓** |
| rsi_extreme_ride | 914 | +1.27 | 0.34 | 0.61 | +0.0042 | +0.97 | 0.45 | +0.71 | 5/6 | −0.11 | +0.21 | **demoted** (≈ null OOS) |
| random_hedge_volfilter | 518 | +0.98 | 0.36 | 0.27 | +0.0028 | +1.69 | 0.09 | +1.34 | 6/6 | −0.09 | +0.15 | **NULL floor** (seed0; ⚠ below) |
| **zigzag_bounce_ride** | 564 | +0.32 | 0.39 | 0.71 | +0.0029 | +1.05 | 0.38 | +0.86 | 5/6 | +0.00 | +0.13 | candidate |
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
| combo_dp_ver | **+1.43** | **+0.66** |
| density_pullback | **+1.04** | **+0.35** |
| vol_expansion_ride | **+0.74** | **+0.37** |
| rsi_extreme_ride | +0.51 | **+0.06** (≈ null) |
| zigzag_bounce_ride | **−0.45** (< null) | +0.13 |
| density_multi_breakout | +0.26 | **−0.60** (< null) |

So on this window only **density_pullback** and **vol_expansion_ride** carry real OOS entry
edge. density_pullback leads on raw entry edge (IS lift +1.04 vs ver +0.74) and folds (6/6 vs
5/6), but **vol_expansion_ride now leads on OOS lift (+0.37 vs +0.35), drawdown and
diversification** after `expand_mult=2.5` traded IS Sharpe for robustness. **rsi_extreme_ride is
≈ the null**, and **zigzag_bounce_ride / density_multi_breakout are at or below it**. The plain
`OOS_sh` column above is inflated by the window's directionality — read the **lift-over-null**
before trusting any OOS Sharpe here.

\* `random_hedge_volfilter` (and the `random_hedge` null) are **seeded** (seed=0); their
single-seed lockbox numbers are rosier than the 8-seed mean — treat as indicative, not final.
All others are deterministic and were regenerated in the 2026-06-10 uniform snapshot; the two
seeded rows are **not** reproduced by `benchmark_table_row`, so their values (incl. `cBTC`/`cDP`)
carry over from the prior snapshot — the only non-uniform rows in the table.

\*\* `combo_dp_ver` is the **shared 12-slot book** of density_pullback + vol_expansion_ride
(2026-06-10, `docs/strategy/combo_dp_ver.md`) — a portfolio composition, not a new edge; its
cDP is trivially high because dp is ~⅔ of its trades. Same peak capital as dp alone (combined
occupancy peaks at 11/12, **zero** historical slot contention); the components' weak WF folds
are complementary (dp's 2022-bear ↔ ver's 2023-bull), giving 6/6 folds and 94% quarterly
consistency on the 80/20 basis. This is the book the live-forward tracks.

## Read at a glance

- **Read OOS as lift-over-null, not vs B&H** (the ⚠ section): the directional window gives a
  random hedge OOS +0.91, so several "candidates" barely clear it.
- **combo_dp_ver** — the shared-book portfolio of the two shipped strategies — is the
  strongest row on every headline (IS +2.20, OOS +1.57, OOS@10bp +1.32, lift-over-null
  IS +1.43 / OOS +0.66, 6/6) at density_pullback's existing peak-capital budget.
- **density_pullback** (recency=1.0 box, prompt limit_window=6) is the strongest on entry edge
  (lift over null **IS +1.04 / OOS +0.35**) AND the most balanced: highest IS (+1.81), **6/6** folds,
  cost-robust (OOS@10bp +1.07), and the only *shipped* one. (Dropping the 24-bar window's stale
  knife-catches nudged IS DD up slightly to 0.31 — the cost of window=6 over 12.)
- **vol_expansion_ride** (entry-edge lift **IS +0.74 / OOS +0.37**) after the two-sided-burst
  filter (`skip_contra_extreme=1`) + **`expand_mult=2.5`**: low-turnover (236 trades), the
  **lowest DD of any candidate** (IS 0.17 / OOS 0.05), most cost-robust (OOS@10bp +1.03) and
  most diversifying (cDP +0.10), now **5/6 folds**. The IS-Sharpe giveback (to +1.51) bought DD,
  consistency (82% quarters) and the early-2021 regime; only the 2023 raging bull stays negative.
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
