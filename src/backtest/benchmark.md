# Benchmark Results

This file holds the latest benchmark output per strategy/sign. It is regenerated
by `scripts/rebenchmark_sign.sh <strategy_name>`. See `docs/evaluation_guide.md`
for metric definitions and `docs/evaluation_criteria.md` for the ship rubric.

> Signal-level metrics (DR, mean_r, perm_p) are **diagnostic only** — never used
> as ship criteria. Ship decisions use portfolio-level metrics + the
> buy-and-hold BTC/JPY benchmark.

---

## ema_atr_breakout

_Last run: 2026-05-31 21:19 (INTERIM) via `rebench_watch.sh` → `scripts/rebenchmark_sign.sh ema_atr_breakout 5m` + `backtest.cycle` (DB: btc_bot_bt). Portfolio figures NET of trading fees._

**Data window:** 2026-04-30 → 2026-05-31 UTC+9 — 8,934 × 5m bars (~31 days, one
calendar month; back-paging is exhausted at bitFlyer's ~31-day `getexecutions`
floor — oldest exec frozen at 2026-04-30 13:00). In-sample = first 80%, OOS =
most recent 20%.

> ⚠️ **INTERIM — still effectively one month, do not ship.** Fires span only
> 2026-04 (n=3) and 2026-05 (n=106), so the monthly walk-forward has just one
> populated period; the ≥4/5-months consistency gate **cannot be evaluated**.
> bitFlyer REST can't supply pre-2026-04-30 history, so depth only grows forward
> in real time from here. The watcher has fired and self-removed; re-arm it once
> 2–3 months of forward history accrue.

### Multi-Month Benchmark (in-sample)

| period | n_fires | DR | mean_r | perm_p |
|--------|---------|-------|---------|--------|
| 2026-04 | 3 | 0.333 | +0.0032 | 1.000 |
| 2026-05 | 106 | 0.594 | +0.0018 | 1.000 |

Sign-level monthly validate: **2/2 months non-negative mean_r → PASS** (note: this
is the *signal* mean_r check, NOT the portfolio ship gate below).

### Regime-Split Analysis (ATR bear/bull)

| regime | n | DR | mean_r |
|--------|---|-------|---------|
| all  | 109 | 0.587 | +0.0018 |
| bear | 15  | 0.333 | -0.0019 |
| bull | 94  | 0.628 | +0.0024 |

### Score Calibration

| metric | value |
|--------|-------|
| n | 109 |
| Spearman ρ | -0.070 |
| Q4 − Q1 spread | -0.0004 |

### OOS (most recent 20%)

| metric | value |
|--------|-------|
| Sharpe | -1.119 |
| Max DD | 0.0498 |
| # trades | 31 |
| Net PnL (min lot) | -626 JPY |

### Portfolio metrics (ship criteria) — NET of fees

| metric | in-sample | OOS |
|--------|-----------|-----|
| Sharpe | -1.122 | -1.119 |
| Max DD | 0.1759 | 0.0498 |
| # trades | 103 | 31 |
| Trading fees | 2,568 JPY | (incl.) |
| Net PnL (min lot) | -2,191 JPY | -626 JPY |
| Buy-and-hold BTC/JPY (gross) | -0.0353 | — |

**Verdict: REJECT (do not ship).** Net of fees the strategy loses money in both
in-sample (Sharpe -1.12, -2,191 JPY) and OOS (Sharpe -1.12, -626 JPY), and the
**OVERFIT** flag is raised (OOS Sharpe < 0). The interesting wrinkle vs the prior
run: with a full month the **signal** now looks mildly informative — all-DR
**0.587** (bull 0.628), positive mean_r — yet the **portfolio still bleeds**. The
gap is turnover × cost: at ~103 trades/month the ~0.2%/round-trip fee
(2,568 JPY total) dwarfs the +0.18% gross per-fire edge, and the TP/SL structure
doesn't convert the weak directional tilt into net PnL. Score calibration is flat
(ρ ≈ -0.07), so the score doesn't rank fires. Bottom line: a real but tiny
directional signal that is **not tradeable at this frequency net of costs** — the
pipeline and cost model are working as intended, not evidence of an edge.

**Ship gate** (pre-registered): SHIP iff avg Sharpe ≥ Buy-and-hold AND ≥ 4/5
periods non-negative. **OVERFIT** flag if OOS Sharpe < 0 or OOS DD > 2× IS DD.

---

## zigzag_bounce

_Last run: 2026-05-31 23:35 (INTERIM) via `scripts/rebenchmark_sign.sh zigzag_bounce 1h` + `backtest.cycle`. **Defaults: ambiguous-wall matching** (`wall_match=True`, `wall_window=120` ≈ 5d — match the early peak to the nearest-in-price confirmed wall, so a ≤tol overshoot-and-revert fires) **+ no-chase filter** (`reject_past_peak=True` — skip a fire whose entry already broke past the most recent opposite-type swing peak). Same-type level matching. Exit: tp 1.0 / sl 1.0 / max_bars 48. Portfolio NET of fees._

**Data window:** 2026-04-30 → 2026-05-31 UTC+9 — 750 × 1h bars (~31 days, one
calendar month). In-sample = first 80%, OOS = most recent 20%.

> ⚠️ **INTERIM — REJECT; the two defaults below were chosen by judgment, not by
> passing the gate.** (1) **Wall matching** (`wall_match`) is the best selection
> on this one month vs the prior extreme-based one (IS net −183→+125, Sharpe
> −0.105→+0.060, fires 17→25, DR 0.412→0.480). (2) **No-chase** (`reject_past_peak`)
> drops entries that already ran past the recent swing peak (e.g. the 5/11 long
> that filled +2.45% above its support and stopped out); it *slightly* lowers
> this month's net via a single-position cascade (a downstream winner gets
> reshuffled out) but enforces a sound entry rule and improves max DD. Both still
> leave the strategy **REJECT** (OOS 0 trades, per-month validate FAILs,
> calibration weak ρ≈0.15). Set `wall_match=False` / `reject_past_peak=False` for
> the prior behavior.

### Multi-Month Benchmark (in-sample)

| period | n_fires | DR | mean_r | perm_p |
|--------|---------|------|----------|--------|
| 2026-05 | 23 | 0.478 | -0.00050 | 1.000 |

### Regime-Split Analysis (ATR bear/bull)

| regime | n | DR | mean_r |
|--------|---|-------|---------|
| all  | 23 | 0.478 | -0.0005 |
| bear | 2  | 0.500 | -0.0101 |
| bull | 21 | 0.476 | +0.0005 |

### Score Calibration

| metric | value |
|--------|-------|
| n | 23 |
| Spearman ρ | +0.150 |
| Q4 − Q1 spread | +0.0060 |

### OOS (most recent 20%)

Portfolio OOS produced **0 trades** — the out-of-sample leg of the ship gate is
unexercisable on this one-month window.

### Portfolio metrics (ship criteria) — NET of fees

| metric | in-sample | OOS |
|--------|-----------|-----|
| Sharpe | +0.022 | 0.000 (0 trades) |
| Max DD | 0.0152 | — |
| # trades | 7 | 0 |
| Trading fees | 175.7 JPY | — |
| Net PnL (min lot) | +40 JPY | — |
| Buy-and-hold BTC/JPY (gross) | -0.0311 | — |

**Verdict: REJECT (interim) — best config so far, made the default.** vs the
prior extreme-based selection, wall matching flips the in-sample portfolio
positive and catches overshoot-and-revert bounces it missed (e.g. the 5/15 short
off the 12.92M wall, TP); the no-chase filter then drops entries that ran past
the recent swing peak (e.g. the 5/11 chase long), trimming net slightly this
month (single-position cascade artifact) but improving max DD (0.0190→**0.0152**)
and enforcing a sound rule. Net: IS Sharpe **+0.022**, net **+40 JPY**. **Still
REJECT**: OOS 0 trades (gate unexercisable), per-month validate FAILs, mean_r
−0.0005 net of fees, calibration weak (ρ≈0.15). A config that *trades* a touch
better this one month, not a demonstrated edge. Re-validate once forward history
gives the consistency gate and an OOS something to test.

> The opt-in notes below were measured **vs the prior extreme-based default**
> (`wall_match=False`); re-sweep against the new wall baseline once data is deep.

**Dominant-level reference (`dominant_window`) — opt-in, default off.** Adds the
long-horizon unbroken same-type extreme (~1 week) as a candidate level so price
can bounce off a dominant weekly floor/ceiling even when nearer minor peaks
exist (the expanding window otherwise stops early and matches a shallow recent
level). On the interim 1h sample this is the **first toggle that helped**: full
750-bar run 9→10 trades, net +0.0059→**+0.0230**, Sharpe +0.035→**+0.125**,
win 44%→**50%**, same maxDD — it catches e.g. the 5/14 retest of the 5/08
12,430,000 floor (score 0.98). Promising but tiny-sample; default off, sweep +
A/B once history is deep before considering it the default.

**Dominant role-reversal (`dominant_reverse`) — opt-in, default off.** Adds
opposite-type *broken* levels over the dominant lookback (a prior high broken
above → support; a prior low broken below → resistance), independent of the
near-window `reverse_levels`. **Regressed** on the interim sample — at dom=120
it took IS net +110 → **−573** (Sharpe +0.052 → −0.256) and doubled max DD: a
nearer broken opposite-level wins the nearest-price contest and swaps the exit
band on trades that were fine on the dominant floor. Same theme as the
near-window reversal (shorts into broken supports during the selloff). Off by
default; A/B once history is deep.

**ZS-band winsorize (`winsorize_k`) — opt-in, default off.** Added to cap an
abnormally large recent zigzag leg from inflating TP/SL (MAD high-side clip).
Tuner sweep (`--sweep-winsor`, size=10/mid=3) on this month is **neutral**: on
the best config (tp1.0/sl0.5/age12) `k=3.0` matches net return (0.0105) with a
hair better Sharpe (0.066 vs 0.065) / maxDD (0.0246 vs 0.0252); on wider-stop
configs it's marginally worse. Too few extreme legs in one month for the cap to
bind materially — kept off by default; re-sweep with deeper history.

**Ship gate** (pre-registered): SHIP iff avg Sharpe ≥ Buy-and-hold AND ≥ 4/5
periods non-negative. **OVERFIT** flag if OOS Sharpe < 0 or OOS DD > 2× IS DD.
