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

_Last run: 2026-05-31 23:22 (INTERIM) via `scripts/rebenchmark_sign.sh zigzag_bounce 1h` + `backtest.cycle`. **Default is now ambiguous-wall matching** (`wall_match=True`, `wall_window=120` ≈ 5d): match the early peak to the nearest-in-price confirmed peak (a ±tol wall), so a ≤tol overshoot-and-revert fires against the wall it pierced. Same-type level matching (`reverse_levels=False`). Exit: tp 1.0 / sl 1.0 / max_bars 48, `winsorize_k=None`. Portfolio NET of fees._

**Data window:** 2026-04-30 → 2026-05-31 UTC+9 — 750 × 1h bars (~31 days, one
calendar month). In-sample = first 80%, OOS = most recent 20%.

> ⚠️ **INTERIM — REJECT; wall is the default by judgment, not by passing the
> gate.** Wall matching was made the default because it is the **best config on
> this one month** (vs the prior extreme-based selection: IS net −183→**+125**,
> Sharpe −0.105→**+0.060**, fires 17→**25**, DR 0.412→**0.480**). But it is still
> REJECT (OOS 0 trades, per-month validate FAILs) and **calibration regressed**
> (ρ 0.49→**0.13**). Chosen on in-sample evidence alone — re-validate once
> forward history exercises the consistency gate. Set `wall_match=False` for the
> original extreme-based selection.

### Multi-Month Benchmark (in-sample)

| period | n_fires | DR | mean_r | perm_p |
|--------|---------|------|----------|--------|
| 2026-05 | 25 | 0.480 | -0.00090 | 1.000 |

### Regime-Split Analysis (ATR bear/bull)

| regime | n | DR | mean_r |
|--------|---|-------|---------|
| all  | 25 | 0.480 | -0.0009 |
| bear | 4  | 0.500 | -0.0081 |
| bull | 21 | 0.476 | +0.0005 |

### Score Calibration

| metric | value |
|--------|-------|
| n | 25 |
| Spearman ρ | +0.130 |
| Q4 − Q1 spread | +0.0047 |

### OOS (most recent 20%)

Portfolio OOS produced **0 trades** — the out-of-sample leg of the ship gate is
unexercisable on this one-month window.

### Portfolio metrics (ship criteria) — NET of fees

| metric | in-sample | OOS |
|--------|-----------|-----|
| Sharpe | +0.060 | 0.000 (0 trades) |
| Max DD | 0.0190 | — |
| # trades | 8 | 0 |
| Trading fees | 201.7 JPY | — |
| Net PnL (min lot) | +125 JPY | — |
| Buy-and-hold BTC/JPY (gross) | -0.0311 | — |

**Verdict: REJECT (interim) — best config so far, made the default.** Wall
matching flips the in-sample portfolio positive (net **+125** / Sharpe
**+0.060**, same maxDD) and lifts fires (17→25) and per-fire DR (0.412→0.480),
catching overshoot-and-revert bounces the prior extreme selection missed (e.g.
the 5/15 short off the 12.92M wall, TP). **Still REJECT**: OOS 0 trades (gate
unexercisable), per-month validate FAILs, mean_r still −0.0009 net of fees, and
**calibration regressed** (ρ 0.49→0.13 — the extra fires are lower-quality; the
score no longer ranks them). A config that *trades* a bit better this one month,
not a demonstrated edge. Re-validate once forward history gives the consistency
gate and an OOS something to test.

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
