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
| **Status** | Implemented; benchmarked 1h = **REJECT** under its own fixed ZS exit. Default = ambiguous-wall matching (`wall_match`). See `src/backtest/benchmark.md`. **Note:** the bounce *direction* is salvageable — fed into the tuned ride exit it goes IS +0.89 / OOS +0.31, 4/6 folds; see [`zigzag_bounce_ride.md`](zigzag_bounce_ride.md). |

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
2. **Near an *outstanding* level:** within an **expanding window** — most recent
   `60` bars, else `120`, else `180` — the early peak must be within `tol_pct` of
   the nearest qualifying level:
   - the **same-type standout** (highest high for an early high / lowest low for
     an early low) — a normal resistance/support retest. **(default)**
   - optionally, **role-reversal** (`reverse_levels=True`): an opposite-type
     confirmed peak — a prior high as support, a prior low as resistance —
     requiring a prior **break** of the level unless `require_break=False`.

   **Defaults: `reverse_levels=False`** (same-type only). On the interim ~1-month
   1h sample, role reversal *regressed* (it shorts into broken supports during a
   selloff); both variants (with/without break) underperformed same-type. The
   options exist to **A/B once there is enough data** — the concept (polarity
   flip) is sound, the sample just didn't support it.

   - optionally, a **dominant level** (`dominant_window`, opt-in): the most
     extreme same-type confirmed peak over a long lookback (~1 week). Because it
     is the extreme it is by definition *unbroken* since it formed — the
     strongest standing support/resistance — so it is added as a candidate even
     when the expanding window already found nearer minor peaks. Without it, the
     expanding window stops at the first window with *any* same-type peak and a
     deep, long-standing floor/ceiling is never consulted if a shallow recent
     level exists (e.g. a clean retest of a weekly low gets matched to a minor
     low 175k away and misses). Nearest-in-price still wins among all candidates.
     With `dominant_reverse` the dominant block *also* adds opposite-type
     **broken** levels (role reversal at the dominant horizon — the dominant
     extreme itself can't be broken, so these are earlier, since-exceeded
     swings); `require_break` gates it, and it is independent of the near-window
     `reverse_levels`. It **regressed** on the interim sample (it references
     broken supports during the selloff and doubles max DD), so default off.

   Direction is still set by the early peak's own type (below).

   The **"near" band** defaults to a fixed `tol_pct × price`, but can be made
   **volatility-scaled** via `tol_leg_frac` (opt-in): `tol_leg_frac × EWA(recent
   zigzag legs)`, widening in volatile swings and tightening in quiet ones
   (falls back to `tol_pct` when there are no legs yet).

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
legs = winsorize_high(legs, k)          if winsorize_k is set  (cap high outliers)
band = ewa(legs, alpha)                 if len(legs) >= min_legs
     = entry_price × fallback_pct        otherwise
TP distance = tp_mult × band            SL distance = sl_mult × band
```

Because the newest leg carries the most weight (`alpha < 0.5`), a single
abnormally large recent leg dominates a plain EWA and blows up TP/SL. The
opt-in `winsorize_k` clips any leg above `median + k·1.4826·MAD` (high side
only — small legs aren't the problem) down to that cap *before* the EWA, so
the band stays representative of the typical swing (e.g. legs
`[2.1,1.8,2.4,2.0,1.9,9.5]` → band `4.27 → 2.30` at `k=3`). Skipped when there
are <3 legs or the MAD is zero (degenerate spread).

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
| `dominant_window` | `None` | If set, also reference the same-type extreme over this long lookback (~168 ≈ 1 week @ 1h) — a long-standing, unbroken floor/ceiling — even when nearer minor peaks exist. `None` = off. |
| `dominant_reverse` | `False` | If set (with `dominant_window`), also add opposite-type *broken* levels over the dominant lookback (a prior high broken above → support; a prior low broken below → resistance). `require_break` gates it. Independent of `reverse_levels`. Regressed on the interim sample — A/B once data is deep. |
| `wall_match` | **`True`** | "Ambiguous wall" model (**default**): match the early peak to the **nearest-in-price** confirmed same-type peak within `wall_window` (a ±`tol` wall), instead of the expanding-window extreme — so a ≤`tol` overshoot-and-revert fires against the wall it pierced. Set `False` for the original extreme-based selection. |
| `wall_window` | **`120`** | Lookback (bars, ≈5d @ 1h) for `wall_match`. The full 180 regressed on the interim sample; ~120 (5d) was net positive — hence the default. |
| `reject_past_peak` | **`True`** | No-chase filter (**default**): skip a fire whose entry (fire-bar close) already broke past the most recent confirmed **opposite-type** swing peak — long: close above the last swing high; short: below the last swing low. Avoids chasing through the recent peak after the `mid_size` lag let price run. Set `False` to allow chased entries. |
| `tol_pct` | 0.005 | Max distance (fraction) of early peak to the level |
| `tp_mult` | 1.0 | TP = `tp_mult × band` |
| `sl_mult` | 1.0 | SL = `sl_mult × band` |
| `alpha` | 0.3 | EWA smoothing (≈2-leg half-life) |
| `min_legs` | 3 | Legs needed before trusting the EWA band |
| `fallback_pct` | 0.01 | Fallback band (fraction of price) |
| `max_bars` | 48 | Time stop / "trade age" (≈2 days @ 1h) |
| `winsorize_k` | `None` | If set, cap legs above `median + k·1.4826·MAD` before the EWA (`≈3` ≈ 3σ). Robust outlier rejection on the **high side only** — keeps an abnormally large recent leg from inflating the band. `None` = off. |

The strategy's internal buffer/warmup equal the sign's trailing window
(`max(windows) + 2·size + mid_size + 5`) so per-bar and benchmark evaluation match.

> **Provisional, small-sample tune** (re-tune with more 1h history;
> `src/backtest/analysis/tune_zigzag_bounce.py` sweeps size/mid/tp/sl/max_bars,
> incl. `--size/--mid` to focus one config):
> - `max_bars` **48** (≈2 days @ 1h): the previous 24-bar stop cut bounces off
>   early (most exits were losing time-stops); 48 improved results broadly.
> - `sl_mult` **1.0** (was 0.6): on size=10/mid=3 the tighter 0.6 stop was
>   ~break-even while a wider 1.0 stop was best — a tight stop gets knocked out on
>   noise before the bounce plays out. (6-trade sample; the *direction* of the
>   finding is more trustworthy than the magnitude.)

The Backtest tab visualises each entry on hover: TP/SL segments over the trade's
lifetime, an "exit" marker, and a dotted connector to the **outstanding peak**
the bounce referenced.

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
| 2026-05-31 | Add opt-in `winsorize_k` (MAD high-side leg clipping) to the ZS band so a single abnormal leg can't inflate TP/SL. Default off. |
| 2026-05-31 | Add opt-in `dominant_window` (reference the long-horizon unbroken same-type extreme as an extra candidate) so bounces off a dominant weekly floor/ceiling fire even when nearer minor peaks exist. Default off; on the interim 1h sample it improved net/Sharpe/win-rate (e.g. catches the 5/14 retest of the 5/08 floor). |
| 2026-05-31 | Add opt-in `dominant_reverse` (opposite-type broken levels over the dominant lookback — role reversal at the dominant horizon, independent of `reverse_levels`). Default off; regressed on the interim sample (net +110→−573 at dom=120, DD doubled). |
| 2026-05-31 | Add opt-in `wall_match` / `wall_window` ("ambiguous ±tol wall": match the nearest-in-price confirmed peak, so a ≤tol overshoot-and-revert fires against the pierced wall). Default off; full 180 regressed, ~120 (5d) net positive (≈ dominant_window=120). |
| 2026-05-31 | Register `zigzag_bounce_wall` variant (`wall_match`, `wall_window=120`) so the wall bounces (e.g. the 5/15 12.92M-resistance rejection, TP) are selectable in the viz dropdown / benchmark runner. Exploratory — IS Sharpe +0.06, `ship=False`. |
| 2026-05-31 | **Make `wall_match`/`wall_window=120` the default** (best config on the interim month: IS net −183→+125, Sharpe −0.105→+0.060, DR 0.412→0.480). Folded the `zigzag_bounce_wall` variant into the default and removed it. Still REJECT (OOS 0 trades, calibration ρ 0.49→0.13) — a judgment call on in-sample evidence, to re-validate once forward history exists. |
| 2026-05-31 | Add **`reject_past_peak` (default on)**: skip entries that already broke past the most recent opposite-type swing peak (no-chase; e.g. the 5/11 long that filled +2.45% above support and stopped out). Trims this month's net slightly (single-position cascade) but improves max DD (0.0190→0.0152). Still REJECT. |
