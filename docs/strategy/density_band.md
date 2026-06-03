# Strategy: `density_band`

Trades **rebounds off the dense band** (a time-at-price value area) on **hourly**
`GMO_BTC_JPY` bars. The dense band is the price region where price has spent most
of its time over the trailing ~1 week; price returning to that band from outside
tends to bounce off the near edge rather than cut straight through.

| | |
|---|---|
| **Name** | `density_band` |
| **Registry** | `src/strategy/registry.py`, `src/signs/registry.py` |
| **Strategy class** | `src/strategy/density_band.py` → `DensityBandStrategy` |
| **Detector (sign)** | `src/signs/density_band.py` → `DensityBandSign` |
| **Indicator** | `src/indicators/density.py` → `time_at_price_profile`, `value_area` |
| **Exit** | Band-relative TP/SL (per-trade `ExitConfig`, in the strategy) |
| **Default timeframe** | **1h** |
| **Status** | Implemented; benchmarked 1h GMO (~5y) = **REJECT**. DR=0.475 (sub-coin-flip), IS Sharpe=−0.06 vs B&H 0.67, `ship=False`. See §7 / `src/backtest/benchmark.md`. |

---

## 1. Hypothesis

Over a trailing window (~1 week = **168 × 1h bars**) price spends most of its
time inside a **dense band** — the market-profile *value area* built from a
**time-at-price** histogram. Being **above** vs **below** that band are different
"stages": crossing the dense band takes energy, so when price returns to the band
from the outside it tends to **rebound off the near edge** instead of punching
through.

- price was **above** the band → descends to **touch the top edge** → **LONG**
- price was **below** the band → rises to **touch the bottom edge** → **SHORT**

The band is recomputed every bar from the trailing window, so it drifts as the
distribution of recent prices changes.

This is the user's original idea: *"take statistics of last one week about which
price range has high density … if the price touches the dense band, trigger an
entry expecting a rebound; above and below the band are different stages, so it
needs energy to break."*

---

## 2. Density indicator (`src/indicators/density.py`)

- `time_at_price_profile(highs, lows, n_bins)` → `(centers, weights)`. Each bar
  contributes **total weight 1.0**, spread across the bins its `[low, high]`
  range overlaps in proportion to the overlap (so a wide-range bar does not
  dominate merely by being wide — it is *time spent at each price*). A zero-range
  bar deposits its full weight in the single containing bin.
- `value_area(centers, weights, coverage=0.70)` → `(poc, band_lo, band_hi)`.
  Standard market-profile construction: start at the **Point-of-Control** (the
  busiest bin) and expand outward, each step toward the heavier adjacent side,
  until `coverage` (default 70%) of the total time is enclosed.

---

## 3. Detector (`src/signs/density_band.py`)

Per bar `t` (only bars `≤ t` used — no look-ahead):

1. Build the profile over `[t-window, t-1]` (the current bar is **excluded** so
   the touching bar cannot move the band it touches). Get `[band_lo, band_hi]`.
2. **Stage** from the prior close: `close[t-1] > band_hi` = above-stage;
   `< band_lo` = below-stage; inside → no fire.
3. **Touch** on bar `t`:
   - LONG: above-stage AND `band_hi - tol ≤ low[t] ≤ band_hi + tol`, not pierced
     more than `pierce_frac` of the band height below the top edge.
   - SHORT: below-stage AND `band_lo - tol ≤ high[t] ≤ band_lo + tol`, mirror.

`tol = tol_pct × edge_price`. `score = 1 − gap/tol`. `ref/ref2` carry the near
and far band edges + timestamp so the viz can draw the band box.

**Parameters** (defaults): `window=168`, `n_bins=48`, `coverage=0.70`,
`tol_pct=0.002`, `pierce_frac=1.0`.

---

## 4. Exit (band-relative, per-trade)

- **TP** = `tp_mult × band_height` back toward where price came from.
- **SL** = just **beyond the far edge** (`sl_buffer × band_height` past it) — the
  rebound thesis is invalidated if price escapes through the band.
- **Time stop** = `max_bars` (default 48 = ~2 days on 1h).

---

## 5. Open items / known divergences

- **Entry mechanic.** The intended live entry is a *touch/stop order at a level a
  little inside the band* (a little above band-center for a long), not a market
  fill at the bar close. The detector fires at the touch bar's **close** (the
  framework's reference price) so the *directional* edge can be measured first.
  Honoring the exact level entry needs **simulator support for level/stop
  entries** (today the simulator only fills at the next bar's open — the two-bar
  rule). Tracked as a follow-up; only worth building if the directional DR shows
  edge.
- **Wide bands in trending weeks.** When the trailing week trends, the 70% value
  area is wide and the "band" is less meaningful (the idea is strongest in
  ranging weeks, like the congestion box the user drew). A regime filter
  (e.g. only trade when band height < X% of price) is a candidate refinement.

---

## 6. Pre-registered ship gate (set BEFORE seeing results)

Per `CLAUDE.md` / `docs/evaluation_criteria.md`, ship **only** if, on the deep 1h
`GMO_BTC_JPY` history:

```
SHIP density_band if:
  (a) avg annualized Sharpe ≥ Buy-and-hold BTC/JPY (NOT cash), AND
  (b) ≥ 4/5 of the most recent monthly walk-forward periods have non-negative
      portfolio return,
  AND it is not flagged OVERFIT (OOS Sharpe < 0 or OOS DD > 2× in-sample DD).
```

Signal-level DR / mean_r / perm_p are **diagnostic only**, never ship criteria.
Do not change this gate after seeing results.

---

## 7. Benchmark results — **REJECT**

First run (2026-06-03, 1h GMO_BTC_JPY, 44,718 bars ~5y, IS=80%/OOS=20%):

- **Signal-level (diagnostic):** in-sample DR=**0.475** (below coin-flip),
  mean_r=−0.0005, perm_p=1.000 every month; bull DR=0.479 / bear DR=0.398; score
  uncalibrated (spearman_rho=−0.0065). Monthly DR swings 0.29–0.70 with no
  persistence. The bounce direction is, if anything, slightly anti-predictive.
- **Portfolio (ship gate):** IS Sharpe=**−0.061** (DD 1.59, 443 trades, net
  −4,305 JPY); OOS Sharpe=0.001 (113 trades, net +262 JPY); buy-and-hold
  Sharpe=**0.666**. → **`ship=False` — REJECT.**

The pre-registered gate (§6) is failed decisively. Because DR < 0.5 holds across
the full 5-year sample and in both regimes, the untested **level-entry** lever
(§5) is unlikely to rescue a sub-coin-flip directional call, so simulator
level-entry support was not built. Full tables in `src/backtest/benchmark.md`.

This is consistent with the prior deep-data finding that mean-reversion / bounce
hypotheses on GMO 1h have no edge — a fresh, structurally different hypothesis is
needed.
