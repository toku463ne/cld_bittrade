# Strategy: `ema_atr_breakout`

EMA(9/21) crossover gated by an ATR(14) volatility filter, for `FX_BTC_JPY`
scalping on bitFlyer Lightning. This is the framework's reference strategy.

| | |
|---|---|
| **Name** | `ema_atr_breakout` |
| **Registry** | `src/strategy/registry.py` |
| **Strategy class** | `src/strategy/ema_atr_breakout.py` → `EmaAtrBreakoutStrategy` |
| **Detector (sign)** | `src/signs/ema_atr_breakout.py` → `EmaAtrBreakoutSign` |
| **Exit rules** | `src/exit/rules.py` |
| **Default timeframe** | 5m (also runs 1m / 15m / 1h) |
| **Status** | **REJECT (interim)** — see [Evaluation](#evaluation) |

---

## 1. Hypothesis

A fast/slow EMA crossover marks a short-term momentum shift. On its own a cross
is noisy and whipsaws in quiet markets, so we **gate it on volatility**: only act
when ATR(14) is above its own recent average, i.e. when there is enough range for
a scalp to clear costs before mean-reverting. Direction comes from the cross;
the ATR filter is a regime gate, not a directional signal.

> This is a deliberately simple, well-understood baseline. Its job is to
> exercise the whole pipeline (signal → simulator → costs → benchmark) and to be
> the **A-arm** that any future strategy must beat. It is *not* expected to have
> a durable edge.

---

## 2. Entry logic

Evaluated on the close of each bar `T` (`EmaAtrBreakoutSign.detect`):

- **Long** when **both** hold:
  1. `EMA(9)` crosses **above** `EMA(21)` (`prev_diff ≤ 0` and `diff > 0`, where
     `diff = EMA(9) − EMA(21)`).
  2. `ATR(14) > ATR_avg(20)` — the 20-bar simple average of ATR (the volatility
     filter is "active").
- **Short** when:
  1. `EMA(9)` crosses **below** `EMA(21)` (`prev_diff ≥ 0` and `diff < 0`).
  2. `ATR(14) > ATR_avg(20)`.

All indicators ignore the warmup region (values stored as `0.0` are treated as
"not ready"; see `src/indicators/`). The strategy buffers bars internally and
needs `warmup = 40` bars before it will emit a signal.

### Score

Each fire carries a confidence `score ∈ [0, 1]` blending cross strength and
volatility excess:

```
sep        = |EMA(9) − EMA(21)| / close          # EMA separation, fractional
vol_excess = ATR(14) / ATR_avg(20) − 1           # how far ATR exceeds its avg
score      = clip( 0.5 · (sep / 0.002) + 0.5 · min(1, vol_excess), 0, 1 )
```

`sep = 0.2%` saturates the first term. Score is a **ranking** input only; it is
not used as a ship criterion (see `docs/evaluation_criteria.md` §5.5).

---

## 3. Exit rules

Returned by `EmaAtrBreakoutStrategy.get_exit_rules()` as an `ExitConfig`, applied
bar-by-bar in `src/exit/rules.py` against the ATR **at the signal bar**
(`entry_atr`):

| Rule | Value | Level (long / short) |
|------|-------|----------------------|
| Take-profit | `1.5 × ATR` | `entry + 1.5·ATR` / `entry − 1.5·ATR` |
| Stop-loss | `0.8 × ATR` | `entry − 0.8·ATR` / `entry + 0.8·ATR` |
| Time stop | `5 bars` | force-exit at bar close once `bars_held ≥ 5` |

Reward:risk ≈ **1.875 : 1**. No trailing stop by default (`trail_atr_mult` unset).

**Intra-bar convention:** within one bar the stop-loss is checked **before** the
take-profit (pessimistic — we cannot know which printed first), so a bar that
spans both levels is booked as a stop-out. Fills are assumed exactly at the
trigger level (no slippage beyond fees).

---

## 4. Execution model

- **Two-bar fill rule:** a signal fires at the close of bar `T` and is filled at
  the **open of bar `T+1`** (consistent in simulator and mock). See
  `src/simulator/simulator.py`.
- **Single position:** one position at a time; no pyramiding.
- **Position size:** minimum lot **0.001 BTC** (no increase until the strategy
  passes the full benchmark pipeline — see CLAUDE.md).
- **Trading costs:** every round-trip deducts
  `entry_price × lot × fee_rate × 2`, `fee_rate = 0.001` (0.10% worst-case taker
  tier). All reported Sharpe / return / DD figures are **net of fees**; the
  buy-and-hold benchmark is **gross**. See `docs/evaluation_guide.md` §4.

---

## 5. Parameters

All configurable via the constructor (`EmaAtrBreakoutStrategy.__init__`):

| Param | Default | Meaning |
|-------|---------|---------|
| `fast` | 9 | Fast EMA span |
| `slow` | 21 | Slow EMA span |
| `atr_period` | 14 | ATR lookback |
| `atr_avg_period` | 20 | ATR-average window (volatility filter) |
| `tp_atr_mult` | 1.5 | Take-profit = mult × entry ATR |
| `sl_atr_mult` | 0.8 | Stop-loss = mult × entry ATR |
| `time_stop_bars` | 5 | Force exit after N bars |

`required_indicators`: `ema_9`, `ema_21`, `atr_14`, `atr_avg_20`.

---

## 6. Code map

```
src/strategy/ema_atr_breakout.py   EmaAtrBreakoutStrategy (on_bar, get_exit_rules)
src/signs/ema_atr_breakout.py      EmaAtrBreakoutSign (detect → FireEvent[])
src/exit/rules.py                  evaluate_exit (TP/SL/trail/time)
src/indicators/{ema,atr}.py        EMA, ATR, ATR-average
src/simulator/simulator.py         two-bar-fill simulator + cost model
src/backtest/                      benchmark pipeline + metrics
```

The strategy **delegates entry detection to the sign** so the per-fire benchmark
and the live entries cannot drift apart (failure-mode §5.3 in
`docs/evaluation_criteria.md`).

---

## 7. Evaluation

### How to run

```bash
# Backtest cycle (portfolio metrics, net of fees)
uv run --env-file .env.bt python -m src.backtest.cycle --strategy ema_atr_breakout --timeframe 5m

# Full per-fire benchmark pipeline (multi-month + regime + calibration + OOS)
scripts/rebenchmark_sign.sh ema_atr_breakout 5m
```

Latest results live in `src/backtest/benchmark.md`. A cron watcher
(`scripts/rebench_watch.sh`) re-runs the pipeline automatically once enough
history (~45 days) has accumulated in `btc_bot_bt`.

### Ship gate (pre-registered)

```
SHIP iff:
  (a) avg Sharpe ≥ Buy-and-hold BTC/JPY (gross), AND
  (b) ≥ 4/5 months non-negative
OVERFIT flag if OOS Sharpe < 0 OR OOS DD > 2× in-sample DD.
```

### Current status — **REJECT (interim)**

Interim 5m run over ~12.6 days (single calendar month, 2026-05; see
`benchmark.md` for the live numbers):

- Net-of-fees Sharpe negative in-sample **and** OOS; **OVERFIT** flagged.
- Signal DR ≈ **0.50** in-sample (coin flip), `perm_p = 1.0` (timing
  uninformative), flat score calibration.
- The ~+0.05% gross per-fire edge is **erased by the ~0.2%/round-trip fee**.

This is consistent with a vanilla EMA-cross+ATR baseline having no real edge on a
short window. The verdict is **not** yet trustworthy as a ship/reject decision:
the sample spans one month, so the ≥4/5-months consistency gate cannot be
exercised. A multi-month verdict requires deeper history.

---

## 8. Known limitations & failure modes

- **Single-period sample (current):** ~one month of data → no walk-forward
  consistency test. Treat current numbers as a pipeline smoke-test.
- **Cost-sensitive / high churn:** with R:R 1.875:1 but coin-flip direction, the
  flat 0.2% round-trip fee dominates; turnover is the main P&L drain.
- **Volatility-regime dependence:** the ATR gate concentrates fires in
  higher-volatility windows; check `bear_DR` vs `bull_DR` in the regime split
  before drawing conclusions (failure-mode §5.2).
- **No slippage modelled** beyond fees — live fills on stops may be worse.

---

## 9. Change log

| Date | Change |
|------|--------|
| 2026-05-31 | Initial implementation; trading-cost model added; interim 5m benchmark → REJECT (single-month sample). |
