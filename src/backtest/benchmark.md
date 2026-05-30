# Benchmark Results

This file holds the latest benchmark output per strategy/sign. It is regenerated
by `scripts/rebenchmark_sign.sh <strategy_name>`. See `docs/evaluation_guide.md`
for metric definitions and `docs/evaluation_criteria.md` for the ship rubric.

> Signal-level metrics (DR, mean_r, perm_p) are **diagnostic only** — never used
> as ship criteria. Ship decisions use portfolio-level metrics + the
> buy-and-hold BTC/JPY benchmark.

---

## ema_atr_breakout

_Last run: 2026-05-31 via `scripts/rebenchmark_sign.sh ema_atr_breakout 1m` (DB: btc_bot_bt)._

**Data window:** 2026-05-29 20:52 → 2026-05-31 07:29 UTC+9 — 1,975 × 1m bars
from 40,000 raw executions (~34.6h). In-sample = first 80%, OOS = most recent 20%.

> ⚠️ **Sample far too small to ship on.** All fires fall in a single calendar
> month (~35h of data), so there is effectively one walk-forward period and
> n≈22 fires in-sample. Treat every number below as a smoke-test of the
> pipeline, not evidence about the strategy. Real evaluation needs months of
> history (accumulate via `src/data/history.py`).

### Multi-Month Benchmark (in-sample)

| period | n_fires | DR | mean_r | perm_p |
|--------|---------|------|---------|--------|
| 2026-05 | 22 | 0.545 | 0.00059 | 1.000 |

### Regime-Split Analysis (ATR bear/bull)

| regime | n | DR | mean_r |
|--------|---|-------|---------|
| all  | 22 | 0.545 | 0.0006 |
| bear | 1  | 0.000 | -0.0040 |
| bull | 21 | 0.571 | 0.0008 |

### Score Calibration

| metric | value |
|--------|-------|
| n | 22 |
| Spearman ρ | -0.199 |
| Q4 − Q1 spread | -0.0001 |

### OOS (most recent 20%)

| period | n_fires | DR | mean_r | perm_p |
|--------|---------|-------|----------|--------|
| 2026-05 | 8 | 0.250 | -0.00083 | 1.000 |

### Portfolio metrics (ship criteria)

| metric | in-sample | OOS |
|--------|-----------|-----|
| Sharpe | -0.145 | 0.413 |
| Max DD | 0.0037 | — |
| # trades | 22 | 8 |
| Net PnL (min lot) | -20.7 JPY | +14.3 JPY |
| Buy-and-hold BTC/JPY | +0.0064 | — |

**Verdict: REJECT (do not ship).** In-sample Sharpe -0.145 < buy-and-hold
(+0.0064); the strategy loses money in-sample over this window. Signal-level DR
54.5% (in-sample) collapses to 25% OOS with `perm_p = 1.0` (timing not
informative) and negative score calibration (ρ = -0.199) — all consistent with
noise at n≈22. The positive OOS Sharpe is on 8 trades and not meaningful.

**Ship gate** (pre-registered): SHIP iff avg Sharpe ≥ Buy-and-hold AND ≥ 4/5
periods non-negative. **OVERFIT** flag if OOS Sharpe < 0 or OOS DD > 2× IS DD.
