# Benchmark Results

This file holds the latest benchmark output per strategy/sign. It is regenerated
by `scripts/rebenchmark_sign.sh <strategy_name>`. See `docs/evaluation_guide.md`
for metric definitions and `docs/evaluation_criteria.md` for the ship rubric.

> Signal-level metrics (DR, mean_r, perm_p) are **diagnostic only** — never used
> as ship criteria. Ship decisions use portfolio-level metrics + the
> buy-and-hold BTC/JPY benchmark.

---

## ema_atr_breakout

_No benchmark has been run yet. Populate by running:_

```
scripts/rebenchmark_sign.sh ema_atr_breakout
```

### Multi-Month Benchmark (in-sample)

| period | n_fires | DR | mean_r | perm_p |
|--------|---------|----|--------|--------|
| _pending_ | | | | |

### Regime-Split Analysis (ATR bear/bull)

| regime | n | DR | mean_r |
|--------|---|----|--------|
| all  | _pending_ | | |
| bear | _pending_ | | |
| bull | _pending_ | | |

### Score Calibration

| metric | value |
|--------|-------|
| n | _pending_ |
| Spearman ρ | |
| Q4 − Q1 spread | |

### OOS (most recent 20%)

| period | n_fires | DR | mean_r | perm_p |
|--------|---------|----|--------|--------|
| _pending_ | | | | |

### Portfolio metrics (ship criteria)

| metric | in-sample | OOS |
|--------|-----------|-----|
| Sharpe | _pending_ | |
| Sortino | | |
| Max DD | | |
| Win rate | | |
| Profit factor | | |
| Total return | | |
| Buy-and-hold BTC/JPY | | |

**Ship gate** (pre-registered): SHIP iff avg Sharpe ≥ Buy-and-hold AND ≥ 4/5
periods non-negative. **OVERFIT** flag if OOS Sharpe < 0 or OOS DD > 2× IS DD.
