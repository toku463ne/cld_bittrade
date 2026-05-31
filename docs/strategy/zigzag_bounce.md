# Strategy: `zigzag_bounce`

Trades bounces off recent established swing levels on **hourly** `FX_BTC_JPY`
bars, using a zigzag peak detector for the levels and a ZS-adaptive (zigzag-leg)
TP/SL exit.

| | |
|---|---|
| **Name** | `zigzag_bounce` |
| **Registry** | `src/strategy/registry.py` |
| **Strategy class** | `src/strategy/zigzag_bounce.py` → `ZigzagBounceStrategy` |
| **Detector (sign)** | `src/signs/zigzag_bounce.py` → `ZigzagBounceSign` |
| **Indicator** | `src/indicators/zigzag.py` → `detect_peaks`, `Peak`, `confirmed_leg_sizes` |
| **Exit** | `src/exit/zs_tp_sl.py` → `ZsTpSl` (via `src/exit/base.py`) |
| **Default timeframe** | **1h** |
| **Status** | Implemented; **not yet benchmarked** (needs more 1h history) |

> Ported from `cld_trade_advisor` (`src/indicators/zigzag.py`, `src/exit/base.py`,
> `src/exit/zs_tp_sl.py`) and adapted: the reference was stock/long-only; this
> version is product-agnostic and trades both directions.

---

## 1. Hypothesis

Price tends to **bounce near recent, established swing levels** (prior swing
highs act as resistance, prior swing lows as support). We want to act *as the
turn forms*, not after it's confirmed.

A **confirmed** zigzag peak needs `size` bars on each side — knowable only
`size` bars later. An **early** peak needs only `mid_size` bars on the right, so
it's knowable `mid_size` bars after it forms. The bet: an early peak will mature
into a confirmed peak (a real top/bottom) **when it sits near a recent confirmed
peak of the same type**.

---

## 2. Zigzag indicator (`src/indicators/zigzag.py`)

`detect_peaks(highs, lows, size, middle_size)` returns `Peak(bar_index,
direction, price)`:

| direction | meaning |
|-----------|---------|
| `2` | confirmed high (max of `size` bars each side) |
| `-2` | confirmed low |
| `1` | early high (max of `size` left + `middle_size` right) |
| `-1` | early low |

`confirmed_leg_sizes(peaks)` returns the absolute price moves between
consecutive **confirmed** peaks — the "ZS" series the exit uses.

This is distinct from `src/backtest/zigzag.py` (which measures per-fire
outcomes for the benchmark).

---

## 3. Entry logic (`ZigzagBounceSign`)

Evaluated on the close of the current bar `T` (a **right-edge, real-time**
check — *not* the indicator's mid-series early classification):

1. **Early peak at `T − mid_size`:** that bar is the extreme over its window
   `[T − mid_size − size, T]` (`size` bars left + the `mid_size` bars now on its
   right). High → early high; low → early low. (A bar that is *both* — a flat
   window — is rejected as ambiguous.)
2. **Near the *outstanding* confirmed peak of the same type:** the outstanding
   peak is the most extreme same-type confirmed peak (highest confirmed high /
   lowest confirmed low) within an **expanding window** — try the most recent
   `60` bars; if it contains no same-type confirmed peak, expand to `120`, then
   `180`. The early peak must be within `tol_pct` of that outstanding peak.
   (Bouncing off the standout level, not merely the nearest minor peak.)

Direction:

- early **high** near the outstanding confirmed **high** (resistance) → **SHORT**
- early **low** near the outstanding confirmed **low** (support) → **LONG**

Score `= 1 − dist/tol_pct` (closer to the level → higher confidence).

**Causality:** every decision at bar `T` uses only bars `≤ T`. The early-peak
check looks `mid_size` bars back; the recent confirmed peaks already have their
`size` bars of right-context *within the trailing window*, so they are known at
`T`. No look-ahead — the benchmark's `detect()` and the strategy's `on_bar()`
share the same window evaluation, so they cannot drift.

---

## 4. Exit: ZS-adaptive TP/SL (`ZsTpSl`)

The band is an **exponentially weighted average of recent zigzag leg sizes**
(`confirmed_leg_sizes`, oldest-first, newest weighted by `alpha`):

```
band = ewa(legs, alpha)                 if len(legs) >= min_legs
     = entry_price × fallback_pct        otherwise
TP distance = tp_mult × band            SL distance = sl_mult × band
```

The rule produces a per-trade `ExitConfig(tp_abs, sl_abs, time_stop_bars)` at
entry; the strategy attaches it to the `Signal` (`exit_config`), and the
simulator applies it bar-by-bar via `src/exit/rules.py` (so TP/SL are placed
correctly for both long and short, SL checked before TP, fees deducted).

Because the band scales with the market's own swing size, stops widen in volatile
regimes and tighten in quiet ones.

---

## 5. Parameters

| Param | Default | Meaning |
|-------|---------|---------|
| `size` | 10 | Confirmed-peak half-window |
| `mid_size` | 3 | Early-peak right-window |
| `windows` | (60,120,180) | Expanding lookback (bars) for the outstanding peak |
| `tol_pct` | 0.005 | Max distance (fraction) of early peak to the level |
| `tp_mult` | 1.0 | TP = `tp_mult × band` |
| `sl_mult` | 0.6 | SL = `sl_mult × band` |
| `alpha` | 0.3 | EWA smoothing (≈2-leg half-life) |
| `min_legs` | 3 | Legs needed before trusting the EWA band |
| `fallback_pct` | 0.01 | Fallback band (fraction of price) |
| `max_bars` | 24 | Time stop (≈1 day @ 1h) |

The strategy's internal buffer/warmup equal the sign's trailing window
(`max(windows) + 2·size + mid_size + 5`) so per-bar and benchmark evaluation match.

---

## 6. Execution notes

- **Per-bar (causal) path only** — the strategy does *not* implement the
  vectorised `precompute()` fast path, because a single full-series zigzag would
  use future bars to confirm peaks (look-ahead). It runs `on_bar` over a bounded
  trailing window, which is fine for hourly bar counts but slow on 1m/5m.
- Two-bar fill, single position, minimum lot 0.001 BTC, fees deducted — same as
  the rest of the framework.

---

## 7. Code map

```
src/indicators/zigzag.py        detect_peaks / Peak / confirmed_leg_sizes
src/exit/base.py                ExitRule ABC + ExitContext
src/exit/zs_tp_sl.py            ZsTpSl -> per-trade ExitConfig (tp_abs/sl_abs)
src/signs/zigzag_bounce.py      ZigzagBounceSign (causal bounce detection)
src/strategy/zigzag_bounce.py   ZigzagBounceStrategy (delegates + ZS exit)
```

---

## 8. Evaluation

```bash
uv run --env-file .env.bt python -m src.backtest.cycle --strategy zigzag_bounce --timeframe 1h
scripts/rebenchmark_sign.sh zigzag_bounce 1h      # full per-fire pipeline
```

Ship gate and OVERFIT flag are the same pre-registered rules as every strategy
(see `docs/evaluation_criteria.md`): SHIP iff avg Sharpe ≥ buy-and-hold (gross)
and ≥ 4/5 periods non-negative.

**Status:** implemented and runs end-to-end (e.g. 522 × 1h bars → 18 fires,
both directions), but the available 1h history is far too short for a
trustworthy verdict — the per-period consistency gate can't be exercised yet.
Re-benchmark once the collector has accumulated more hourly history.

---

## 9. Known limitations & failure modes

- **Look-ahead is the central risk for this style** — handled by the strict
  causal evaluation; do not "optimise" it into a full-series zigzag.
- **Catching a falling knife:** an early peak near support can keep going; the
  ZS stop (`sl_mult × band`) caps the loss, but a run of failed bounces in a
  trend will bleed via fees + stops.
- **Level staleness:** the expanding `windows` bound how old the outstanding
  level may be; too large and stale levels trigger, too small and real S/R is
  missed.
- **Sparse fires on short history** — confirmed peaks need `2·size` bars, so 1h
  data accrues levels slowly.

---

## 10. Change log

| Date | Change |
|------|--------|
| 2026-05-31 | Initial implementation (zigzag indicator, ZS TP/SL exit, strategy). Runs on 1h; not yet benchmarked. |
