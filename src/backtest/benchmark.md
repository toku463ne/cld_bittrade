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

_Last run: 2026-05-31 21:19 (INTERIM) via `rebench_watch.sh` → `scripts/rebenchmark_sign.sh zigzag_bounce 1h` + `backtest.cycle` (watcher fired on stall and self-removed). **Default = same-type level matching** (`reverse_levels=False`). Exit: tp 1.0 / sl 1.0 / max_bars 48, `winsorize_k=None` (off). Portfolio NET of fees. Numbers unchanged from the 20:04 / 21:10 runs — back-paging stalled at 2026-04-30 so the data window did not grow._

**Data window:** 2026-04-30 → 2026-05-31 UTC+9 — 750 × 1h bars (~31 days, one
calendar month). In-sample = first 80%, OOS = most recent 20%.

> ⚠️ **INTERIM — no edge; default reverted to same-type.** As data grew the
> same-type DR slipped 0.467 → **0.412** and IS Sharpe +0.115 → **−0.105**, i.e.
> the earlier slight positive was small-sample luck. S/R **role reversal** was
> tested and *regressed* on this window (DR 0.389 no-break / 0.417 break-check,
> IS net down to −500 JPY) — so it's kept as an **opt-in** (`reverse_levels` /
> `require_break`) to A/B once history is deep, not the default.

### Multi-Month Benchmark (in-sample)

| period | n_fires | DR | mean_r | perm_p |
|--------|---------|------|----------|--------|
| 2026-05 | 17 | 0.412 | -0.00405 | 1.000 |

### Regime-Split Analysis (ATR bear/bull)

| regime | n | DR | mean_r |
|--------|---|-------|---------|
| all  | 17 | 0.412 | -0.0041 |
| bear | 3  | 0.333 | -0.0126 |
| bull | 14 | 0.429 | -0.0022 |

### Score Calibration

| metric | value |
|--------|-------|
| n | 17 |
| Spearman ρ | +0.488 |
| Q4 − Q1 spread | +0.0219 |

### OOS (most recent 20%)

| period | n_fires | DR | mean_r | perm_p |
|--------|---------|-------|----------|--------|
| 2026-05 | 5 | 0.800 | +0.00967 | 1.000 |

### Portfolio metrics (ship criteria) — NET of fees

| metric | in-sample | OOS |
|--------|-----------|-----|
| Sharpe | -0.105 | 0.000 (0 trades) |
| Max DD | 0.0190 | — |
| # trades | 7 | 0 |
| Trading fees | 175.9 JPY | — |
| Net PnL (min lot) | -183 JPY | — |
| Buy-and-hold BTC/JPY (gross) | -0.0311 | — |

**Verdict: REJECT (interim).** Default same-type matching: in-sample DR 0.412
(< coin flip), `perm_p` 1.0, net −183 JPY / Sharpe −0.105; per-month validation
FAILs. No directional edge demonstrated. The one persistently-positive signal is
**score calibration** (ρ rising 0.26 → 0.49 across runs, Q4−Q1 +0.022) — the
score ranks fires even though the base DR is sub-0.5; a flag to watch, not
trade. Role-reversal options exist but underperformed here. Re-evaluate (and
A/B the options) once months of 1h history exist.

**ZS-band winsorize (`winsorize_k`) — opt-in, default off.** Added to cap an
abnormally large recent zigzag leg from inflating TP/SL (MAD high-side clip).
Tuner sweep (`--sweep-winsor`, size=10/mid=3) on this month is **neutral**: on
the best config (tp1.0/sl0.5/age12) `k=3.0` matches net return (0.0105) with a
hair better Sharpe (0.066 vs 0.065) / maxDD (0.0246 vs 0.0252); on wider-stop
configs it's marginally worse. Too few extreme legs in one month for the cap to
bind materially — kept off by default; re-sweep with deeper history.

**Ship gate** (pre-registered): SHIP iff avg Sharpe ≥ Buy-and-hold AND ≥ 4/5
periods non-negative. **OVERFIT** flag if OOS Sharpe < 0 or OOS DD > 2× IS DD.
