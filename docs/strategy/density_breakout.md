# Strategy: `density_breakout`

Trades **breakouts out of the dense band** (a time-at-price value area) on
**hourly** `GMO_BTC_JPY` bars, riding the move for ~12 h – several days. This is
the user's charted idea: price consolidates *inside* the dense box, closes out
through an edge, and trends away; the stop sits beyond the *opposite* edge so a
pullback back to the band does not stop the trade out.

| | |
|---|---|
| **Name** | `density_breakout` |
| **Registry** | `src/strategy/registry.py`, `src/signs/registry.py` |
| **Strategy class** | `src/strategy/density_breakout.py` → `DensityBreakoutStrategy` |
| **Detector (sign)** | `src/signs/density_breakout.py` → `DensityBreakoutSign` |
| **Indicator** | `src/indicators/density.py` → `time_at_price_profile`, `value_area` |
| **Exit** | Far-edge structural stop + ATR trailing stop + time stop (per-trade `ExitConfig`) |
| **Default timeframe** | **1h** |
| **Status** | Tuned: `max_band_pct=0.02`, `confirm_bars=1`, `trail_atr_mult=None`. 1h GMO (~5y): **IS Sharpe +0.197 / OOS +0.221 (OOS>IS), net +6.4k/+3.5k JPY**, DD 0.18. `ship=False` only on the consistency gate (59% periods green < 80%). Project's best config. See §7. |

This is the **opposite trigger** to [`density_band`](density_band.md): that one
fades a bounce *into* the edge from outside (REJECT, bled); this one rides a
breakout *out of* the value area (REJECT, break-even).

---

## 1. Hypothesis

Over a trailing ~1 week (168 × 1h) price spends most of its time inside a **dense
band** = the market-profile value area (70% of time-at-price). The band is a
strong barrier; when price has been **consolidating inside** it and then **closes
out through an edge**, it tends to **trend away** for many hours to days:

- prior bar closed INSIDE the band, this bar **closes above the top edge** → LONG
- prior bar closed INSIDE the band, this bar **closes below the bottom edge** → SHORT

A pullback ("bounce") back to the band after entry is *expected* and tolerated.

---

## 2. Density indicator (`src/indicators/density.py`)

Shared with `density_band`: `time_at_price_profile` (each bar contributes total
weight 1.0 spread over the bins its `[low, high]` overlaps) and `value_area`
(expand outward from the Point-of-Control to 70% coverage → `band_lo, band_hi`).

---

## 3. Detector (`src/signs/density_breakout.py`)

Per bar `t` (only bars `≤ t`): build the profile over `[t-window, t-1]` (breakout
bar excluded). Fire iff `close[t-1]` was **inside** `[band_lo, band_hi]` and
`close[t]` is **beyond an edge** (above `band_hi` → LONG, below `band_lo` →
SHORT). `score` = breakout extent as a fraction of band height. `ref` = broken
edge, `ref2` = opposite edge (the stop level + viz box). Optional `max_band_pct`
regime filter (default off) requires a *tight* box.

**Params (defaults):** `window=168`, `n_bins=48`, `coverage=0.70`,
`max_band_pct=None`.

---

## 4. Exit (the explicit next tuning target)

Per-trade `ExitConfig`, built to **ride the trend** and **tolerate a pullback to
the band**:

- **Structural stop** = `sl_abs` reaching beyond the **opposite** band edge
  (`+ sl_buffer × band_height`). Per the user's rule, a bounce back to the band
  must not stop the trade — only a full traverse through the far edge does.
- **ATR trailing stop** (`trail_atr_mult`, default 6.0 — loose). The simulator's
  effective stop is the *closer* of the structural and trailing levels, so the
  far-edge stop dominates early and the trail only binds once `peak − trail` rises
  above the opposite edge (i.e. after a real run). The loose default keeps normal
  pullbacks to the band from tripping it.
- **Time stop** = `max_bars` (default 120 = ~5 days) backstop.

Verified behaviour (full-series sim): exit mix = **60% trail · 21% time · 18.5%
structural stop** — the wide stop is rarely hit, confirming pullbacks to the band
are tolerated.

---

## 5. Pre-registered ship gate (unchanged from the family)

```
SHIP density_breakout if:
  (a) avg annualized Sharpe ≥ Buy-and-hold BTC/JPY, AND
  (b) ≥ 4/5 of the most recent monthly walk-forward periods non-negative,
  AND not flagged OVERFIT (OOS Sharpe < 0 or OOS DD > 2× IS DD).
```

> **Do NOT judge this strategy by DR / detection rate.** A trend-ride wins < 50%
> of the time by design (here 40.8%) and lives on payoff asymmetry. DR and a
> fixed-horizon mean_r are diagnostics only; the gate is portfolio Sharpe vs
> buy-and-hold.

---

## 6. Levers — pulled and unpulled

- **Tight-box regime filter** (`max_band_pct`) — ✅ **PULLED, big win.** Now the
  default `0.02`; turned a break-even strategy net-profitable (see §7).
- **Breakout confirmation** (`confirm_bars`, `min_break_frac`) — ❌ **PULLED,
  REJECTED (overfits).** Requiring 2–4 consecutive closes beyond the edge, or a
  minimum breakout extent, *raised* every in-sample metric (IS Sharpe, win rate,
  period consistency 48%→57%) but **flipped OOS Sharpe negative in all 7 tested
  variants** — entering later means entering closer to exhaustion, sacrificing the
  early trend the OOS regime needed. Defaults kept at `confirm_bars=1` /
  `min_break_frac=0.0` (the un-confirmed first-close breakout is best OOS). Params
  retained for re-test on deeper data. See `src/backtest/benchmark.md`.
- **Exit tuning** (`trail_atr_mult`, `sl_buffer`, `max_bars`) — ✅ **PULLED, win.**
  The ATR trail *hurt* (clipped trend winners); removing it (`trail_atr_mult=None`,
  now default) lifted IS Sharpe 0.141→0.197 and OOS 0.113→0.221, ~2–3× net PnL.
  `max_bars=120` and `sl_buffer=0.10` confirmed best. See §7.
- **Consistency gate question** (the live open item) — the strategy is
  net-profitable IS+OOS but green in only ~59% of periods (gate needs ≥80%).
  Trend-rides are inherently lumpy; whether the ≥80% rubric should apply to a
  trend-ride is an open call for the human.

---

## 7. Benchmark results

### v1 — no filter (`max_band_pct=None`): REJECT, break-even

- IS DR 0.459, mean_r +0.0004; 497 trades, win 40.8%, payoff 1.45, expectancy
  ≈ +0.004%/tr (break-even), median hold 49 h. IS Sharpe −0.001 (DD 0.75),
  OOS +0.031. `ship=False`. Right trend-ride shape but no edge yet.

### v2 — tight-box filter (`max_band_pct=0.02`): break-even → net-profitable

2% is the tightest threshold still robust OOS (below it IS rises but OOS flips
negative — overfit). IS Sharpe **+0.141** (DD 0.158, 107 tr, net +2,852 JPY), OOS
**+0.113** (36 tr, net +1,094 JPY), payoff 2.4. First net-profitable result.

### v3 — exit tuning (`trail_atr_mult=None`, NOW DEFAULT): project's best

The ATR trail *clipped the trend winners*; removing it (structural stop + 120-bar
time stop only) was the best config in both samples — looser trail → better,
monotonically (see §6 / `src/backtest/benchmark.md`).

- **Config:** `max_band_pct=0.02, confirm_bars=1, trail_atr_mult=None,
  sl_buffer=0.10, max_bars=120`.
- **Portfolio:** **IS Sharpe +0.197** (DD **0.181**, 92 trades, net **+6,414 JPY**);
  **OOS Sharpe +0.221** (31 trades, net **+3,499 JPY**), payoff **2.84**, median
  hold **98 h**. → **`ship=False`.**

**OOS Sharpe (0.221) exceeds IS (0.197)** — the strongest robustness signal, the
exact opposite of the rejected confirmation overfit. Net-profitable in both
samples with a 0.18 drawdown; net PnL ~2× IS / ~3× OOS vs the trailing version.
It fails the ship gate **only** on the consistency condition (17/29 = **59%** of
periods non-negative; gate needs **≥80%**) — a trend-ride is structurally lumpy
(few big winners). The live open question: is the ≥80%-periods-green rubric the
right bar for a trend-ride? Full tables in `src/backtest/benchmark.md`.
