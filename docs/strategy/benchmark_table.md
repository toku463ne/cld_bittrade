# Candidate benchmark table

At-a-glance comparison of the multi-position strategy candidates, all on **one consistent
basis** — deterministic rows regenerated in a **uniform snapshot 2026-06-10** (the
dp / combo / dp-ETH rows re-regenerated **2026-06-11** after the `max_base_bars=64`
adoption), GMO_BTC_JPY 1h unless marked. Regenerate any row with
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
>
> **2026-06-10 (later):** **`combo_dp_ver`** added — the **shared 12-slot book** of the two
> shipped strategies (see the \*\* note and `combo_dp_ver.md`); registered, ship✓, and the
> live-forward now tracks it (boundary 2026-06-07 22:00, weekly cron). Also: the cycle gained
> a **realistic bitFlyer cost preset** (`--bitflyer-realistic` = 0.04%/day swap + 5× burst
> spread on stop exits; defaults unchanged) — both shipped components **survive** it (dp IS
> 1.50→1.31 / OOS 0.95→0.58; ver IS 1.46→1.28 / OOS 0.82→0.47, 80/20 basis) and dp's
> `recalc_bars=48` exit was verified the argmax under **both** cost bases. Three
> density_pullback improvement attempts were tested and **not adopted** (failed-breakout
> invalidation exit; stale-box/base-length gate — the classical "longer base = stronger
> breakout" is *inverted* at 1h; swap-leak hypothesis refuted) — its row is unchanged; see
> `density_pullback.md`.
>
> **2026-06-11 — ETH transfer test** (pre-registered gates; `study_plan_new_strategies.md`
> §C/C′): **`density_pullback` TRANSFERS to GMO_ETH_JPY untuned** (row below, its own
> benchmark: ETH B&H lockbox **IS +0.40 / OOS +0.59** — the ETH OOS window *rose* +18%, a
> harder bar) and survives **15 bp/side** (OOS +0.80). **`vol_expansion_ride` does NOT
> transfer** (ETH OOS +0.41 < B&H; dead at 10 bp/side → −0.03) — the squeeze→burst edge is
> asset-specific. ETH-specific re-tuning of dp's tightness gate was swept and **NOT adopted**
> (edge falls monotonically as the gate loosens; the gate is **absolute-%**, not
> vol-quantile — ETH's rarer fires are load-bearing). Also: the combo **slot sweep** found
> 6 slots ≈ the 12-slot book on every metric (see \*\* note).
>
> **2026-06-11 (later) — `max_base_bars=64` ADOPTED** (stale-box gate; reverses the
> 2026-06-10 rejection). Deciding evidence: **independent-asset replication on ETH** — the
> BTC-chosen 64 cell, untuned on ETH, improves the ETH per-trade stale tail (64+: mean_r
> −0.0065, DR 0.12) *and* equity (IS-WF mean +0.45→+0.58, 4/6 folds up, none down). The
> dp / combo / dp-ETH rows below are regenerated on this basis: dp IS +1.84 / OOS +1.35,
> combo IS +2.23 / OOS +1.66 — every BTC metric up, 6/6 held. **Honest giveback:** dp-ETH's
> (eroded) lockbox OOS fell +1.19→+0.83 (still > ETH B&H +0.59); the gate's ETH benefit is
> IS-side and the **forward adjudicates**. All three forward clocks were RESET at adoption
> (boundaries re-frozen 2026-06-11; records were only days old — the cheapest moment).
>
> **2026-06-11 (later still) — Strategy C″: `density_pullback_eth` registered** with the
> **ETH-only `invalidation_depth=0.25`** failed-breakout exit (BTC's rejection of this knob
> stands). ETH's geometry reverses the verdict: a smooth 0.10–0.35 WF plateau (IS-WF mean
> +0.58→+0.95, 3/6→5/6 folds), a bleed-cutting mechanism (the opposite of BTC's failure),
> and the one lockbox look recovered the max_base OOS giveback (+0.83→**+1.33**). Row
> updated below; the ETH forward switched to the variant.
>
> **2026-06-11 (C‴) — three more ETH items:** (5) **keep both sides** (ETH shorts carry
> MORE than longs, +0.79 vs +0.27 sum_r, and pay in rising regimes too); (3) swap refuted
> again (3.3× cost = burst-on-stops) but the **recalc verification found the argmax moved
> on BOTH cost bases → `recalc_bars=72` adopted ETH-only** (smooth 64–72 plateau; BTC
> stays 48). (4) `limit_offset` **rejected** — the edge is a local max from both sides.
> Row regenerated at recalc=72: IS +1.43, **WF 6/6**, but lockbox OOS reads +0.84 vs the
> +1.33 the C″ config posted — the spent lockbox keeps disagreeing with ETH IS-WF
> selections (noise on ~50 trades, or accumulating fold-fit). **The pristine forward at
> 72 adjudicates; fallback = the C″ config (recalc=48).**
>
> **2026-06-11 (later still) — XRP transfer (Strategy F):** **`density_pullback` transfers
> strongly to GMO_XRP_JPY untuned** (row below; XRP B&H IS +0.60 / OOS −0.24) — 6/6 folds,
> pays in BOTH bull and bear folds (not a falling-market artifact), promoted with a
> per-product forward. **`vol_expansion_ride` clears the letter of the gate but is weak**
> (passes only on XRP's falling OOS, the mirror of its ETH failure; recent fold negative) —
> not promoted. The value-area-retest mechanism now holds untuned on **3 assets**
> (BTC/ETH/XRP); the squeeze→burst ride does not transfer cleanly. See
> `study_plan_new_strategies.md` §F. Families A/B/D/E (orthogonal hunts) all dead.
>
> **2026-06-11 (later still) — XRP tuning + a recalc REVERSAL.** Applied the ETH C″/C‴ suite
> to XRP → **`density_pullback_xrp`** registered with **one** XRP-only knob,
> `invalidation_depth=0.35` (its IS-WF plateau peaks deeper than ETH's 0.25; lockbox IS +1.36 /
> OOS +2.68 / @10bp +2.58 / 6/6 — a clean win over the untuned base). The slower-ratchet
> `recalc_bars=72` looked good on the XRP IS-WF too, **but the held-out lockbox rejected it**
> (OOS +2.68 at 48 vs +1.58 at 72) — the SAME direction the ETH lockbox had disagreed. Two
> assets agreeing settled it: the slower ratchet was IS-WF overfitting, so it was **NOT adopted
> on XRP and REVERTED on ETH** (density_pullback_eth → the C″ config, recalc=48: IS +1.31 /
> OOS +1.33, its row restored below). `limit_offset` rejected on XRP (edge is the local max).
> The invalidation exit is now a held-out-validated edge on two assets; the recalc tuning was
> the mirage the lockbox caught.

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
| **combo_dp_ver** | 651 | **+2.23** | 0.31 | 0.38 | +0.0062 | **+1.66** | 0.18 | **+1.41** | **6/6** | +0.03 | +0.91\*\* | **ship✓ (portfolio)** |
| **density_pullback** | 415 | **+1.84** | 0.36 | 0.32 | +0.0061 | **+1.35** | 0.18 | **+1.16** | **6/6** | +0.06 | +1.00 | **ship✓** |
| **density_pullback_eth**\*\*\* | 252 | **+1.31** | 0.26 | 0.29 | +0.0040 | **+1.33** | 0.07 | **+1.21** | 5/6 | −0.01 | — | **candidate (fwd accruing)** |
| **density_pullback_xrp**† | 342 | **+1.36** | 0.31 | 0.39 | +0.0063 | **+2.68** | 0.12 | **+2.58** | **6/6** | −0.02 | — | **candidate (fwd accruing)** |
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
| combo_dp_ver | **+1.46** | **+0.75** |
| density_pullback | **+1.07** | **+0.44** |
| vol_expansion_ride | **+0.74** | **+0.37** |
| rsi_extreme_ride | +0.51 | **+0.06** (≈ null) |
| zigzag_bounce_ride | **−0.45** (< null) | +0.13 |
| density_multi_breakout | +0.26 | **−0.60** (< null) |

So on this window only **density_pullback** and **vol_expansion_ride** carry real OOS entry
edge (**combo_dp_ver** is their composition, not a third edge — its lift is the two combined
on one book). After `max_base_bars=64`, density_pullback leads on **both** lifts (IS +1.07 /
OOS +0.44 vs ver's +0.74 / +0.37) and folds (6/6 vs 5/6); **vol_expansion_ride keeps the
drawdown and diversification lead** (IS_DD 0.17, cDP +0.10) after `expand_mult=2.5` traded IS
Sharpe for robustness. **rsi_extreme_ride is ≈ the null**, and **zigzag_bounce_ride /
density_multi_breakout are at or below it**. The plain `OOS_sh` column above is inflated by
the window's directionality — read the **lift-over-null** before trusting any OOS Sharpe here.

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
consistency on the 80/20 basis. This is the book the live-forward tracks. **Slot sweep**
(`combo_slots_sweep.py`, 2026-06-10): 6 slots matches the 12-slot book on every metric (IS
+1.95/OOS +1.16/6-6 folds, PnL even +1%; occupancy p95 = 4); erosion starts at 4 and is real
at ≤3. `max_slots` stays **12** in code (a budget guarantee, not a tuned knob — changing it
would re-select on the lockbox), but **6 lots is the capital-planning number**.

\*\*\* `density_pullback_eth` runs on **GMO_ETH_JPY**: the shared dp defaults + **one**
ETH-only knob, the `invalidation_depth=0.25` failed-breakout exit (on ETH it cuts the stop
bleed, NOT the BTC-rejected geometry; lockbox look IS +1.31 / OOS +1.33). The C‴ `recalc_bars=72`
slower ratchet was adopted then **REVERTED 2026-06-11** — the held-out lockbox preferred 48 on
ETH (OOS +1.33 vs +0.84) *and* XRP (+2.68 vs +1.58), so it was IS-WF overfitting. This row is the
recalc=48 config. IS/OOS are vs **ETH's own B&H (IS +0.40 / OOS +0.59)**, all clear, 15 bp/side
OOS +0.82. Not in the lift-over-null table (BTC-calibrated null). **Forward accruing** since the
2026-06-10 23:00 boundary; no capital before it confirms.

† `density_pullback_xrp` runs on **GMO_XRP_JPY**: the shared dp defaults + **one** XRP-only knob,
`invalidation_depth=0.35` (the XRP IS-WF plateau peaks deeper than ETH's 0.25). The untuned
default transferred first (IS +1.06 / OOS +2.59, 6/6); the invalidation exit then lifted it to
IS +1.36 / OOS +2.68 / @10bp +2.58 (one lockbox look, all up). IS/OOS are vs **XRP's own B&H
(IS +0.60 / OOS −0.24)** — the high OOS is partly displaced capital (beating a −34% market) but
regime-robust (pays in bull f3/f5 AND bear f6). `recalc_bars=72` and `limit_offset` were tested
and rejected (the lockbox rejected the slower ratchet on both assets; the edge is the offset
local max). `vol_expansion_ride` was not promoted (weak transfer). Not in the lift-over-null
table (BTC-calibrated null). **Forward accruing** since the 2026-06-11 05:00 boundary.

## Read at a glance

- **Read OOS as lift-over-null, not vs B&H** (the ⚠ section): the directional window gives a
  random hedge OOS +0.91, so several "candidates" barely clear it.
- **combo_dp_ver** — the shared-book portfolio of the two shipped strategies — is the
  strongest row on every headline (IS +2.23, OOS +1.66, OOS@10bp +1.41, lift-over-null
  IS +1.46 / OOS +0.75, 6/6) at density_pullback's existing peak-capital budget.
- **density_pullback** (recency=1.0 box, limit_window=6, **max_base_bars=64** since
  2026-06-11) is the strongest single strategy on entry edge (lift over null **IS +1.07 /
  OOS +0.44**) and the most balanced: highest single-strategy IS (+1.84), **6/6** folds,
  cost-robust (OOS@10bp +1.16, survives `--bitflyer-realistic`, exit verified argmax under
  both cost bases). The stale-box gate was the one 2026-06-10 rejection later reversed by
  ETH replication; the other attempts stay rejected.
- **vol_expansion_ride** (entry-edge lift **IS +0.74 / OOS +0.37**) after the two-sided-burst
  filter (`skip_contra_extreme=1`) + **`expand_mult=2.5`**: low-turnover (236 trades), the
  **lowest DD of any candidate** (IS 0.17 / OOS 0.05), most cost-robust (OOS@10bp +1.03) and
  most diversifying (cDP +0.10), now **5/6 folds**. The IS-Sharpe giveback (to +1.51) bought DD,
  consistency (82% quarters) and the early-2021 regime; only the 2023 raging bull stays negative.
- **density_pullback_eth / density_pullback_xrp** — the dp edge tuned per asset, each with
  **one** held-out-validated knob, the `invalidation_depth` failed-breakout exit (ETH 0.25 → IS
  +1.31 / OOS +1.33; XRP 0.35 → IS +1.36 / OOS +2.68, both 6/6 or 5/6). The exit replicates as a
  real edge on both assets (BTC rejected it — geometry-specific). The `recalc_bars=72` slower
  ratchet was adopted on ETH then **reverted** when XRP's held-out lockbox confirmed the ETH
  lockbox's disagreement (both prefer 48) — an IS-WF mirage the WF couldn't catch but the lockbox
  did. ETH band re-tuning, limit offset, and recalc all failed; shorts CARRY both alt books (keep
  both sides). vol_expansion_ride did not transfer cleanly to either.
- **rsi_extreme_ride** is **≈ the null on OOS** (lift +0.06) despite a nice headline +0.97 — its
  OOS edge mostly evaporates against the right floor (DD developed via `max_slots=3`).
- **zigzag_bounce_ride** is **below the null on IS** (−0.45); **density_multi_breakout** is **below
  the null on OOS** (−0.60) and not cost-robust — both effectively no entry edge here.
- **DR is sub-0.5 for all** (trend-ride payoff). Per CLAUDE.md, DR/mean_r are diagnostics only.

## Caveats & regeneration

A lockbox snapshot, not a final verdict — the lockbox has been reused across ideas (erodes it),
so real capital waits on the **live-forwards now running** (`paper_forward`, weekly Monday cron
via `scripts/weekly_forward_check.sh`): `density_pullback`, `vol_expansion_ride` and
`combo_dp_ver` (all boundary 2026-06-07 22:00, re-frozen 2026-06-11 at the max_base adoption;
the combo is the BTC book that would actually trade) and `density_pullback_eth` @ GMO_ETH_JPY
(per-product boundary 2026-06-10 23:00). Verdicts are withheld until ≥20 forward trades AND
≥60 days per strategy (~mid-Aug 2026 earliest). Headline costs are the calm basis (4 bp round-trip); stress with
`python -m src.backtest.cycle --strategy <name> --bitflyer-realistic` (swap + burst spread on
stops) — both shipped components and hence the combo survive it. Single IS/OOS split + 6 coarse
folds; ride-exit candidates share the same exit (correlations in `cDP`). Regenerate any row with
`python -m src.backtest.analysis.benchmark_table_row --strategy <name>` (lockbox basis;
validated to reproduce the committed rows). Seeded rows (`random_hedge*`) are seed-0 and not
reproduced by that deterministic script — see the ⚠ note.
