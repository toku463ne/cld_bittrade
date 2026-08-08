# Candidate benchmark table

At-a-glance comparison of the multi-position strategy candidates, all on **one consistent
basis** — deterministic rows regenerated in a **uniform snapshot 2026-06-10** (the
dp / combo / dp-ETH rows re-regenerated **2026-06-11** after the `max_base_bars=64`
adoption), GMO_BTC_JPY 1h unless marked. Regenerate any row with
`python -m src.backtest.analysis.benchmark_table_row --strategy <name>`.

> **2026-06-20 — regenerated on HONEST FILLS (trail phantom-fill fix, commit 9bdbcd4).**
> The ride ratchet had been booking exits at a stale stop level the bar never traded at
> (the recalc-jump phantom fill, surfaced by the live dry-run). The fix cut every ride
> row's equity Sharpe 25–50%. **The main table below is now the honest basis** (deterministic
> rows re-run; seeded `random_hedge*` rows re-run at seed-0). Headline moves: combo_dp_ver
> OOS +1.66→**+0.91** (WF 6/6→**4/6**), density_pullback OOS +1.35→**+0.78**,
> density_pullback_xrp OOS +2.68→**+2.23** (6/6 held), vol_expansion_ride OOS +1.28→**+0.58**,
> rsi_extreme_ride OOS +0.97→**−0.63** (now negative). **The live BTC book was switched
> `combo_dp_ver` → `density_pullback`** (head-to-head in `portfolio.md`): combo's only lift
> over plain dp was the now-OOS-dead `vol_expansion_ride` leg. The ⚠ null-floor /
> lift-over-null section further down is **also reseeded on honest fills** — the random-hedge
> null collapsed (20-seed OOS +0.91→+0.25), which actually *raised* most candidates' lift even
> as their absolute Sharpes fell.

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

> **2026-06-28 — Kojiro trend book (`docs/books/kojiro.md`) sign-debate.** Three Stage-0
> probes (all read-only/uncommitted, lockbox untouched). (1) The **half-rise trailing-stop
> exit** REJECTED on `density_breakout`'s own 242 IS fires — ΔSharpe(half-rise − shipped
> no-trail) = −0.008, CI [−0.09,+0.06]; any trail loses to the shipped structural ride.
> (2) The **MA-stage entry** (大循環, SMA stages + native stage-flip exit) on raw returns is
> below B&H across 18 (1h/4h/1d × 3 MA-sets) configs. (3) **BUT** adding the book's full
> money-management chassis — **ATR-unit risk sizing + pyramiding (増し玉)** — to the daily
> 5/20/40 cell partly reverses (3) on IS (separate IS-only section below). Lesson: a trend
> book must be tested with its risk chassis, not component-wise on raw returns. The first two
> probes are a clean reject; the third is a **promising-but-unproven** diversifier candidate.

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
| **density_pullback** | 415 | **+1.52** | 0.35 | 0.41 | +0.0047 | **+0.78** | 0.19 | **+0.59** | 5/6 | +0.06 | +1.00 | **ship✓ — LIVE BTC book** |
| **combo_dp_ver** | 651 | **+1.62** | 0.31 | 0.50 | +0.0040 | **+0.91** | 0.22 | **+0.66** | 4/6 | +0.03 | +0.92\*\* | ship✓ — **superseded as BTC book** |
| **density_pullback_xrp**† | 342 | **+0.65** | 0.30 | 0.41 | +0.0025 | **+2.23** | 0.12 | **+2.13** | **6/6** | −0.03 | +0.96 | **candidate (fwd) — LIVE XRP book** |
| **density_pullback_eth**\*\*\* | 252 | **+0.93** | 0.25 | 0.34 | +0.0024 | **+1.03** | 0.07 | **+0.91** | 5/6 | −0.01 | +0.88 | candidate (fwd) — **dropped from portfolio** |
| **vol_expansion_ride** | 236 | **+0.82** | 0.24 | 0.22 | +0.0030 | +0.58 | 0.05 | +0.32 | 5/6 | −0.07 | +0.11 | **demoted** (OOS-weak post-fix) |
| **density_multi_breakout** | 439 | +1.03 | 0.40 | 0.56 | +0.0063 | +0.32 | 0.42 | +0.20 | 5/6 | +0.03 | +0.68 | weak (cost; ratchet-independent) |
| **zigzag_bounce_ride** | 564 | −0.04 | 0.36 | 0.87 | +0.0012 | +0.58 | 0.52 | +0.39 | 5/6 | +0.00 | +0.13 | below null (IS) |
| rsi_extreme_ride | 914 | +0.44 | 0.32 | 1.01 | +0.0008 | −0.63 | 0.53 | −0.90 | 4/6 | −0.11 | +0.21 | **rejected** (OOS < 0) |
| random_hedge_volfilter | 518 | +0.26 | 0.33 | 0.36 | +0.0008 | +1.02 | 0.09 | +0.65 | 5/6 | −0.10 | +0.17 | **NULL floor** (seed0; ⚠ below) |
| random_hedge (null) | 684 | −0.58 | 0.36 | 1.05 | −0.0013 | +0.40 | 0.12 | −0.08 | 2/6 | −0.06 | +0.13 | null baseline (seed0) |
| **kojiro_ma_stage**‡ | 61 | **+0.66** | 0.20 | 0.49 | +0.015 | — | — | — | — | — | — | **IS-only triage** — promising, OOS not spent |

## ⚠ Null-floor correction — the lockbox OOS is directional, so B&H is the wrong floor

> **Honest-fill basis (2026-06-20), reseeded.** The 20-seed null and the lift table below are
> now recomputed on the realisable trail fill. The phantom fill had inflated the **null floor
> even more than the candidates** (it relies entirely on the ride exit), so reseeding *raised*
> most candidates' relative edge even as their absolute Sharpes fell.

`random_hedge_volfilter` is a **random-entry** control, yet on the old phantom fills it posted
a huge lockbox OOS (seed-0 +1.69). Diagnosis (20-seed sweep): **(a)** seed-0 was a lucky draw —
the **honest 20-seed mean is IS +0.10 / OOS +0.25** (pre-fix it read +0.77 / +0.91); and
**(b)** even that is *not* skill — a hedged pair + ride exit lets the trend-aligned leg run, so
it beats B&H far more often in *bear* windows than when B&H rises, and the recent OOS window is
directional/down.

**Consequence: the honest null floor is the random hedge (lockbox 20-seed mean IS +0.10 /
OOS +0.25), not B&H (−0.16).** Edge = **lift over that null**:

| candidate | IS lift / null | OOS lift / null |
|---|---|---|
| combo_dp_ver | **+1.52** | **+0.66** |
| density_pullback | **+1.42** | **+0.53** |
| vol_expansion_ride | **+0.72** | **+0.33** |
| density_multi_breakout | +0.93 | +0.07 (≈ null) |
| zigzag_bounce_ride | **−0.14** (< null) | +0.33 |
| rsi_extreme_ride | +0.34 | **−0.88** (≪ null) |

So on this window **density_pullback** and **vol_expansion_ride** still carry real OOS entry
edge (**combo_dp_ver** is their composition, not a third edge — its lift is the two combined on
one book). density_pullback leads on **both** lifts (IS +1.42 / OOS +0.53 vs ver's +0.72 /
+0.33) and folds (5/6 vs 5/6) — and is the live BTC book. **rsi_extreme_ride is now well below
the null on OOS** (−0.88), confirming its rejection; **density_multi_breakout** sits ≈ at the
null (it's ratchet-independent, so the null collapsing lifted its *relative* standing without
any real edge); **zigzag_bounce_ride** clears the null on OOS but not IS. The plain `OOS_sh`
column above is inflated by the window's directionality — read the **lift-over-null** before
trusting any OOS Sharpe here.

\* `random_hedge_volfilter` (and the `random_hedge` null) are **seeded** (seed=0); their
single-seed lockbox numbers are rosier than the multi-seed mean — treat as indicative, not
final. Their rows are regenerated at seed-0 on the honest-fill basis (2026-06-20), and the
⚠ lift table's null floor is the honest 20-seed mean (regenerate with
`python -m src.backtest.analysis.null_floor_sweep`). All other rows are deterministic.

\*\* `combo_dp_ver` is the **shared 12-slot book** of density_pullback + vol_expansion_ride
(2026-06-10, `docs/strategy/combo_dp_ver.md`) — a portfolio composition, not a new edge; its
cDP is trivially high because dp is ~⅔ of its trades. Same peak capital as dp alone (combined
occupancy peaks at 11/12, **zero** historical slot contention); the components' weak WF folds
are complementary (dp's 2022-bear ↔ ver's 2023-bull), giving 6/6 folds and 94% quarterly
consistency on the 80/20 basis. This is the book the live-forward tracks. **Slot sweep**
(`combo_slots_sweep.py`, 2026-06-10): 6 slots matches the 12-slot book on every metric (IS
+1.95/OOS +1.16/6-6 folds — *pre-fix; honest = +1.62/+0.91/4-6 in the table above*; PnL even
+1%; occupancy p95 = 4); erosion starts at 4 and is real
at ≤3. `max_slots` stays **12** in code (a budget guarantee, not a tuned knob — changing it
would re-select on the lockbox), but **6 lots is the capital-planning number**.

\*\*\* `density_pullback_eth` runs on **GMO_ETH_JPY**: the shared dp defaults + **one**
ETH-only knob, the `invalidation_depth=0.25` failed-breakout exit (on ETH it cuts the stop
bleed, NOT the BTC-rejected geometry; lockbox look IS +1.31 / OOS +1.33 — *pre-fix; honest =
+0.93 / +1.03 in the table above*). The C‴ `recalc_bars=72`
slower ratchet was adopted then **REVERTED 2026-06-11** — the held-out lockbox preferred 48 on
ETH (OOS +1.33 vs +0.84) *and* XRP (+2.68 vs +1.58), so it was IS-WF overfitting. This row is the
recalc=48 config. IS/OOS are vs **ETH's own B&H (IS +0.40 / OOS +0.59)**, all clear, 15 bp/side
OOS +0.82. Not in the lift-over-null table (BTC-calibrated null). **Forward accruing** since the
2026-06-10 23:00 boundary; no capital before it confirms.

† `density_pullback_xrp` runs on **GMO_XRP_JPY**: the shared dp defaults + **one** XRP-only knob,
`invalidation_depth=0.35` (the XRP IS-WF plateau peaks deeper than ETH's 0.25). The untuned
default transferred first (IS +1.06 / OOS +2.59, 6/6); the invalidation exit then lifted it to
IS +1.36 / OOS +2.68 / @10bp +2.58 (one lockbox look, all up) — *pre-fix; honest = IS +0.65 /
OOS +2.23 / @10bp +2.13 in the table above*. IS/OOS are vs **XRP's own B&H
(IS +0.60 / OOS −0.24)** — the high OOS is partly displaced capital (beating a −34% market) but
regime-robust (pays in bull f3/f5 AND bear f6). `recalc_bars=72` and `limit_offset` were tested
and rejected (the lockbox rejected the slower ratchet on both assets; the edge is the offset
local max). `vol_expansion_ride` was not promoted (weak transfer). Not in the lift-over-null
table (BTC-calibrated null). **Forward accruing** since the 2026-06-11 05:00 boundary.

‡ **`kojiro_ma_stage`** (the row above) is a **different basis — do not compare its cells
row-for-row with the multi-position rows.** Single-position, **GMO_BTC_JPY daily** (resampled
from 1h), 大循環 Stage-1 long / Stage-4 short + native stage-flip exit + book pyramiding
(`pyr-1.0N`, max 4 units, 2N agg-stop), **ATR-unit risk sizing** (1 unit = 1% capital per
1 ATR). Only **`n`, `IS_sh`, `DR`** are directly comparable; `IS_DD`/`mean_r` are on the
ATR-unit capital basis (mean_r = +0.015 *of capital* per trade, not a raw price return);
**OOS / WF / cBTC / cDP are blank because the lockbox OOS is deliberately UNTOUCHED** (this
is an idea-stage triage per eval_criteria §6.5.1, not a ship row). Not regenerated by
`benchmark_table_row.py`; regenerate with `python -m src.backtest.analysis.kojiro_pyramid_stage0`.
Full breakdown (arms, per-year, caveats) below. Basis 2026-06-28.

## Kojiro daily MA-stage (book trend engine) — detail behind the ‡ row

> **Different basis — do not compare row-for-row with the table above.** Single-position,
> **GMO_BTC_JPY daily** (resampled from 1h), **ATR-unit risk sizing** (1 unit = 1% capital
> per 1 ATR), **IS-only** (the lockbox OOS is deliberately UNTOUCHED — this is an
> idea-stage triage, not a ship row). Not regenerated by `benchmark_table_row.py`;
> regenerate with `python -m src.backtest.analysis.kojiro_pyramid_stage0`. Basis 2026-06-28.

Entry = 大循環 Stage 1 (SMA5>20>40, all rising) long / Stage 4 short; exit = native
stage-flip OR the book's 2N aggregate stop; pyramiding adds 1 unit per ATR-increment advance
(max 4 units), aggregate stop ratchets to 2N below the latest fill. **IS = pre-2025-04-01,
daily B&H eqSharpe +0.554** over the same window.

| arm | trades | avg units | win% | annRet% | **IS eqSharpe** | vs B&H +0.554 |
|---|---|---|---|---|---|---|
| baseline (1 unit, ATR-sized) | 54 | 1.00 | 0.35 | 6.4 | **+0.577** | ≈ parity |
| pyr-0.5N (base spacing) | 58 | 2.79 | 0.22 | 19.5 | +0.517 | below |
| **pyr-1.0N (low-risk spacing)** | 61 | 2.15 | 0.20 | **22.9** | **+0.662** | above |

Per-calendar-year capital return % (pyr-1.0N, 1% risk/unit) — the trend-following signature:

| year | strat | B&H |
|---|---|---|
| 2022 | **+3.0** | **−73.3** |
| 2023 | +22.2 | +111.4 |
| 2024 | +72.6 | +104.7 |
| 2025 (Q1 stub) | −10.5 | −15.1 |

**Read (honest):** the headline lift over raw returns is **ATR-unit sizing**, not pyramiding
(raw daily 5/20/40 eqSharpe was +0.259; risk-normalising lifts it to +0.577 ≈ B&H).
Pyramiding does what the book claims — **~3× the return (6.4→22.9%/yr) at ~flat Sharpe** —
and only the low-risk **1.0N** spacing helps (0.5N over-adds and hurts). The cell is positive
**every full year incl. the 2022 −73% crash**, so on IS it plausibly clears *both* ship-gate
legs (eqSharpe ≥ B&H; per-year non-neg 4/4 ≥ B&H 3/4) — a genuine bear-protective
diversifier. **CAVEATS:** n ≈ 54–61 on daily → Sharpe SE ≈ 0.13, so +0.66 vs +0.55 is
**within noise** (parity, not a proven beat); **IS-ONLY** (OOS lockbox is the decisive,
not-yet-run test); single book-canonical cell. Verdict: **promising-but-unproven candidate**,
not a confirmed edge. Next step (not run, user-deferred): one-shot idea-stage OOS lockbox
(eval_criteria §6.5.1) on this exact config.

## Book-derived feature bias audit (2026-06-28) — re-tests of previously-rejected book signs

> **Signal-level Stage-0 probes, NOT equity-vs-B&H ship rows.** After the Kojiro half-rise
> reject was found **density-anchored + tested component-wise on raw returns** (it under-tested
> the book), the same two-bias check — *(1) density-anchoring* (a book feature bolted onto
> `density_breakout`, where it's redundant by construction) and *(2) wrong timeframe / no full
> money-management chassis* — was applied to the other rejected book families. Read these as
> "did correcting the bias surface a tradeable sign?" Metrics are **lift over the regime/breakout
> matched random null** and **per-trade Sharpe**, IS-only, lockbox untouched. All probes
> read-only/uncommitted.

| book / feature | original reject (1h) | bias-correcting move | corrected result | verdict |
|---|---|---|---|---|
| **Kojiro MA-stage** | raw-return eqSharpe < B&H | + **ATR-unit sizing + pyramiding**, **daily** | IS eqSharpe **+0.66 ≈ B&H +0.55**, +ve every full yr incl. 2022 | **real bias** → ‡ candidate row above (OOS unspent) |
| **VPA hi-vol continuation** | 1h net **−0.15** (lift_z>1 but neg base rate) | **daily** (continuation → higher TF) | long net **+0.07..+0.11**, lift_z 1.19, base rate still −0.11 | **partial bias** — flips net-+ve but marginal, fails gate |
| **Brooks false-breakout fade** | 1h net −0.16..−0.25 (lift_z>1) | **5m/15m** (fade → Brooks-native *lower* TF) | 5m lift_z **≤0**, net −0.13..−0.15 (n=10k-34k) | **NO bias** — worse intraday, robustly dead |

**VPA hi-vol continuation on DAILY** (`vpa_continuation_daily_stage0.py`; null_sh = the daily
"buy any up-bar + ride" base rate, vs 1h's **−0.19**):

| arm / thr | n | per-trade Sharpe | lift_z vs null | base rate (null_sh) |
|---|---|---|---|---|
| long 1.2 | 52 | +0.073 | **1.19** | −0.114 |
| long 2.0 | 16 | +0.114 | 0.84 | −0.163 |
| short 1.5 | 30 | +0.191 | 2.10 | −0.270 |

The long continuation **flips from 1h net-negative (−0.15) to daily net-positive** (so the
1h-only rejection *was* timeframe-fragile), but the daily base rate stays negative (−0.11), so
the VPA edge only lifts it to ~breakeven. **No long cell clears G1(Sharpe≥0.10)+G2(lift_z≥1)+G3(n≥30)
together**; the lone full-pass cell (short 1.5) is a non-robust 1-of-3 fluke. Marginal, not shippable.

**Brooks false-breakout fade across timeframes** (`false_breakout_fade_stage0.py FB_EXIT=scalp`,
`FB_TF=5m|15m|1h`; lift_z = reclaim selection vs breakout-matched null — the fade's *only*
redeeming quality at 1h):

| TF | net Sharpe (arms) | lift_z vs null | base rate |
|---|---|---|---|
| 1h | −0.16..−0.25 | **>+1** (up to +2.9) | −0.05..−0.23 |
| 15m | −0.04..−0.11 | mostly ≤0 (one +1.1 amid −1.7/−0.8) | −0.04..−0.10 |
| 5m | −0.13..−0.15 | **mostly ≤0** (−1.9, −2.0; n=10k-34k) | −0.13 |

Brooks' native habitat is the 5-min chart, and a fade is *anti-trend* (so the bias-correcting
move is *down*, not up like the continuation families). At 5m the reclaim's marginal 1h
information **drowns in intraday noise** (lift_z collapses to ≤0) and the base rate is negative
at every scale (BTC up-drifts at all TF). The rejection is **robust and stronger** intraday — no
timeframe rescues fading an up-drifting asset. (`high2_low2` continuation not separately re-run —
its higher-TF correction is covered by the Kojiro daily MA-stage finding: with-trend continuation
*entries* carry no selection edge on daily either, lift_z<1.)

**Net:** of the three book families re-audited, only **Kojiro** carried a material bias (→ the ‡
candidate); **VPA** was timeframe-fragile but lands marginal; **Brooks** is robustly dead. The
bias check is a genuine two-way test — it confirmed one kill while reopening another.

## Read at a glance

- **Read OOS as lift-over-null, not vs B&H** (the ⚠ section): the directional window gives a
  random hedge 20-seed OOS ~+0.25 (honest), the floor for entry edge.
- **density_pullback** (recency=1.0 box, limit_window=6, **max_base_bars=64**) is the **live
  BTC book** (swapped in 2026-06-20) and the strongest *single-mechanism* strategy on honest
  fills: IS **+1.52**, OOS **+0.78**, OOS@10bp **+0.59**, **5/6** folds, cDP +1.00. It clears
  its own B&H in both lockbox splits and is one mechanism — preferred over `combo_dp_ver` for
  the BTC slot (head-to-head in `portfolio.md`).
- **combo_dp_ver** (shared dp + vol_expansion book) still posts the highest BTC OOS (**+0.91**)
  but **only because the dp leg carries it** — its lift over plain dp is the `vol_expansion_ride`
  leg, now OOS-dead. WF dropped to **4/6** and IS_DD rose to 0.50 (the lumpy 2024-loaded path).
  **Superseded as the BTC book**; kept here as the composition reference.
- **vol_expansion_ride** is **demoted** on honest fills: IS +0.82, OOS **+0.58**, OOS@10bp
  **+0.32** (was +1.03), and in the 80/20 cycle its OOS equity Sharpe collapses to ~0 with an
  OVERFIT flag. It keeps the lowest DD (IS 0.22 / OOS 0.05) and best diversification (cDP +0.11),
  but its standalone forward edge is no longer credible.
- **density_pullback_xrp** (LIVE XRP book; `invalidation_depth=0.35`) is the **standout OOS** —
  IS +0.65 / OOS **+2.23** / @10bp +2.13 / **6/6**, vs XRP's own B&H (IS +0.60 / OOS −0.24); the
  high OOS is partly displaced capital (beating a falling market) but regime-robust (pays bull
  and bear folds). **density_pullback_eth** (`invalidation_depth=0.25`) holds IS +0.93 / OOS
  +1.03 / 5/6 vs ETH B&H, but is **dropped from the portfolio** (yearly-redundant with BTC and
  fails the 80/20 quarterly-consistency gate post-fix). `vol_expansion_ride` does not transfer
  to either alt.
- **Multi-asset combination** — see `docs/strategy/portfolio.md`. **ETH is yearly-redundant with
  BTC** (corr **+0.99**), while **XRP is the only diversifier** (corr ~0.5) and the steadiest
  book. Recommended robust split on honest fills: **BTC 45% `density_pullback` / XRP 55%
  `density_pullback_xrp`, ETH dropped**, each at its capital-efficient slot count (dp 6 / xrp 6 —
  PnL saturates there). Positive every full year, **ySharpe 1.29** (was 1.68 pre-fix) — and all
  books are still forward-ACCRUING, so this is a backtest construction, not a sizing decision.
- **rsi_extreme_ride** is **rejected** — OOS goes **negative** on honest fills (OOS −0.63,
  @10bp −0.90); the headline OOS was phantom-fill.
- **zigzag_bounce_ride** is **below the null on IS** (now IS −0.04); **density_multi_breakout**
  (ratchet-independent, unchanged) is weak on OOS (+0.32) and not cost-robust — neither carries
  entry edge here.
- **DR is sub-0.5 for all** (trend-ride payoff). Per CLAUDE.md, DR/mean_r are diagnostics only.

## Caveats & regeneration

A lockbox snapshot, not a final verdict — the lockbox has been reused across ideas (erodes it),
so real capital waits on the **live-forwards now running** (`paper_forward`, weekly Monday cron
via `scripts/weekly_forward_check.sh`): `density_pullback`, `vol_expansion_ride` and
`combo_dp_ver` (all boundary 2026-06-07 22:00, re-frozen 2026-06-11 at the max_base adoption;
since 2026-06-20 **`density_pullback` — not `combo_dp_ver` — is the BTC book that would actually
trade**), `density_pullback_eth` @ GMO_ETH_JPY
(per-product boundary 2026-06-10 23:00) and `density_pullback_xrp` @ GMO_XRP_JPY (boundary
2026-06-11 05:00). Verdicts are withheld until ≥20 forward trades AND ≥60 days per strategy
(~mid-Aug 2026 earliest). Headline costs are the calm basis (4 bp round-trip); stress with
`python -m src.backtest.cycle --strategy <name> --bitflyer-realistic` (swap + burst spread on
stops) — both shipped components and hence the combo survive it. Single IS/OOS split + 6 coarse
folds; ride-exit candidates share the same exit (correlations in `cDP`). Regenerate any row with
`python -m src.backtest.analysis.benchmark_table_row --strategy <name>` (lockbox basis;
validated to reproduce the committed rows). Seeded rows (`random_hedge*`) are seed-0 and not
reproduced by that deterministic script — see the ⚠ note.
