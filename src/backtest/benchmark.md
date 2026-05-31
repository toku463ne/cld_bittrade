# Benchmark Results

This file holds the latest benchmark output per strategy/sign. It is regenerated
by `scripts/rebenchmark_sign.sh <strategy_name>`. See `docs/evaluation_guide.md`
for metric definitions and `docs/evaluation_criteria.md` for the ship rubric.

> Signal-level metrics (DR, mean_r, perm_p) are **diagnostic only** — never used
> as ship criteria. Ship decisions use portfolio-level metrics + the
> buy-and-hold BTC/JPY benchmark.

---

## ema_atr_breakout

_Last run: 2026-05-31 11:40 (INTERIM) via `scripts/rebenchmark_sign.sh ema_atr_breakout 5m` (DB: btc_bot_bt). Portfolio figures NET of trading fees._

**Data window:** 2026-05-18 → 2026-05-31 UTC+9 — 3,608 × 5m bars from ~494k raw
executions (~12.6 days). In-sample = first 80%, OOS = most recent 20%.

> ⚠️ **INTERIM — single calendar month, do not ship on this.** All fires fall in
> one month (2026-05), so the monthly walk-forward has only ONE period: the
> ≥4/5-months consistency gate **cannot be evaluated** here. n=44 fires
> in-sample is still small. The durable cron watcher (`rebench_watch.sh`) will
> re-run automatically once history reaches ~45+ days (2–3 months) for a verdict
> that can actually exercise the consistency gate.

### Multi-Month Benchmark (in-sample)

| period | n_fires | DR | mean_r | perm_p |
|--------|---------|------|---------|--------|
| 2026-05 | 44 | 0.500 | 0.00051 | 1.000 |

### Regime-Split Analysis (ATR bear/bull)

| regime | n | DR | mean_r |
|--------|---|-------|---------|
| all  | 44 | 0.500 | 0.0005 |
| bear | 6  | 0.500 | 0.0003 |
| bull | 38 | 0.500 | 0.0006 |

### Score Calibration

| metric | value |
|--------|-------|
| n | 44 |
| Spearman ρ | +0.063 |
| Q4 − Q1 spread | ~0.0000 |

### OOS (most recent 20%)

| period | n_fires | DR | mean_r | perm_p |
|--------|---------|-------|----------|--------|
| 2026-05 | 11 | 0.545 | 0.00095 | 1.000 |

### Portfolio metrics (ship criteria) — NET of fees

| metric | in-sample | OOS |
|--------|-----------|-----|
| Sharpe | -1.071 | -1.649 |
| Max DD | 0.0719 | 0.0206 |
| # trades | 42 | 11 |
| Trading fees | 1,023 JPY | ~268 JPY |
| Net PnL (min lot) | -868 JPY | -271 JPY |
| Buy-and-hold BTC/JPY (gross) | -0.0368 | — |

**Verdict: REJECT (do not ship).** Net of fees the strategy loses money in both
in-sample (Sharpe -1.07) and OOS (Sharpe -1.65), and the **OVERFIT** flag is
raised (OOS Sharpe < 0). Signal-level DR is exactly **0.500** in-sample (a coin
flip — no directional edge) with `perm_p = 1.0` (timing uninformative) and flat
score calibration (ρ ≈ +0.06, Q4−Q1 ≈ 0). The gross per-fire edge is ~+0.05%,
which the ~0.2%/round-trip fee erases entirely (1,023 JPY of fees on 42 trades
turned a roughly break-even gross signal into a clear net loss). This is the
expected outcome for an EMA-cross+ATR baseline on a short window; it confirms the
pipeline and the cost model are working, not that the strategy has an edge.

**Ship gate** (pre-registered): SHIP iff avg Sharpe ≥ Buy-and-hold AND ≥ 4/5
periods non-negative. **OVERFIT** flag if OOS Sharpe < 0 or OOS DD > 2× IS DD.
