# Strategy: `density_multi_breakout`

A **multi-position** promotion of [`density_breakout`](density_breakout.md): same
dense-band breakout entry, but it holds several overlapping positions and exits
each **into the next dense zone**. On hourly `GMO_BTC_JPY` it is the project's
first walk-forward-robust edge — a modest, **market-neutral-ish diversifier**
(positive in all 6 walk-forward folds; beats buy-and-hold when B&H is down,
trails it in strong bulls).

| | |
|---|---|
| **Name** | `density_multi_breakout` |
| **Class** | `src/strategy/density_multi_breakout.py` → `DensityMultiBreakoutStrategy` |
| **Simulator** | `src/simulator/multi_simulator.py` → `MultiSimulator` (≤ `max_slots`) |
| **Indicator** | `src/indicators/density.py` (`time_at_price_profile`, `value_area`) |
| **Default config** | `window=168, max_band_pct=0.03, max_slots=5, target_min_dist_frac=1.5` (walk-forward-robust + cost-robust) |
| **Default timeframe** | **1h** |
| **Status** | `ship=False` — clears Sharpe-vs-B&H but fails the ≥80%-periods consistency gate. IS eqSharpe **+0.90** / OOS **+0.84** vs B&H **+0.64**. See §5. |

---

## 1. Hypothesis

Price consolidates inside the ~1-week value-area box, breaks an edge, and trends
to the **next pre-existing congestion** before stalling. Because such moves
overlap in time, holding **several positions at once** captures more of them, and
the portfolio's value comes from **diversification across slots** — so it must be
judged by a time-based equity Sharpe, not per-trade Sharpe.

## 2. Entry (same as `density_breakout`, confirm_bars=1)

Value area over `[t-window, t-1]` (window=168). Fire iff the prior close was
inside a **tight** box (`band_height ≤ max_band_pct × price`, `max_band_pct=0.03`)
and this close breaks an edge: above the top → LONG, below the bottom → SHORT.
Two-bar fill (next bar's open). Up to `max_slots=5` concurrent, any direction.

## 3. Exit — "into the next dense", whichever first

Per-position `ExitConfig` + one dynamic hook:

- **Target** (`tp_abs`) — the heaviest *pre-existing* node at least
  `target_min_dist_frac × band_height` (1.5×) *beyond* the broken edge, from a
  336-bar profile at entry. The distance floor skips the box lip so the target is
  a real next congestion (~6 % of exits, median ~22 h / +3.4%) rather than a 1-bar
  scalp — this is the **cost-robust** setting (see §5).
- **Far-edge structural stop** (`sl_abs`) — beyond the *opposite* edge + a
  `sl_buffer=0.10` band-height buffer, so a pullback to the box does not stop out
  (~48 % of exits).
- **Time stop** — 120 bars ≈ 5 days (~41 %; with a distant target, most winners
  now ride to the time stop).
- **Stall** (`dynamic_exit`) — a fresh tight box forms at a new level with price
  inside it (the trend stalled into a new consolidation); minor (~3 %).

## 4. How it is benchmarked (the metric change)

`Strategy.max_slots > 1` routes `run_cycle` to the `MultiSimulator`, which records
a **mark-to-market equity curve** (realised + unrealised across the open book).
The headline metric is the **annualised equity Sharpe**; per-trade Sharpe is
reported as a diagnostic only (it is ~0.12, understating the edge). The viz
Backtest panel shows the equity Sharpe line for multi strategies.

### Pre-registered ship gate (multi variant)

```
SHIP if:
  (a) IS annualised EQUITY Sharpe ≥ buy-and-hold's own annualised Sharpe, AND
  (b) ≥ 80% of in-sample periods non-negative,
  AND not OVERFIT (OOS per-trade Sharpe < 0 or OOS DD > 2× IS DD).
```

> Do **not** judge by per-trade Sharpe / DR — overlapping slots make those the
> wrong yardstick. The portfolio metric is the equity-curve Sharpe vs B&H's own.

## 5. Results

**Official rebench (GMO 1h, ~5y), `target_min_dist_frac=1.5`:** IS equity Sharpe
**+0.90** / OOS **+0.84** (vs **B&H annualised Sharpe +0.64**); 460 IS / 148 OOS
trades; exit mix stop 48 % · time 41 % · target 6 % · stall 5 %; target exits
median ~22 h / +3.4%. **`ship=False`** — it *passes* (a) (eqSharpe IS +0.90 ≥ B&H
+0.64) but *fails* (b), the ≥80%-periods consistency gate (a lumpy trend-ride).

**Cost robustness (`density_multi_target_cost.py`).** The original lip target
(dist 0.0) had the highest calm-cost OOS (+1.36 @ 4 bp round-trip) but was the most
spread-fragile (IS +0.09 @ 40 bp). `target_min_dist_frac=1.5` is the chosen
default: positive IS *and* OOS even at a stressed 40 bp round-trip (IS +0.40 /
OOS +0.07), balanced at realistic cost (IS +0.90 / OOS +0.87 @ 4 bp). Dropping the
target entirely is worse (OOS dies at 40 bp), so a *distant* dense target helps.

**Walk-forward (6 folds, `src/backtest/analysis/density_multi_walkforward.py`):**
positive in **all 6 folds** at this config — the only cell that is, bull and bear.
The honest *anchored* walk-forward (re-select the grid cell on past data only) is
modest: **3/5 folds, mean test equity Sharpe +0.19**.

**Slot sweep (`density_multi_slotsweep.py`):** single-position is weak (3/6 folds);
4 and 5 slots both hit 6/6; beyond 6 saturates (rarely >~6 concurrent signals).
`unit` is Sharpe-invariant (scales only net JPY / JPY-drawdown; pinned at the
0.001 min lot until ship).

## 6. Character & caveats

A **diversifier**, not a BTC replacement: it earns when buy-and-hold is falling
(2022 bear, recent decline) and trails it in raging bulls. Caveats: the headline
config was chosen after seeing all folds (though it is the original ~1-week
window, not a mined corner); a single IS/OOS split plus 6 coarse folds, not a
dense walk-forward; the OOS edge leans partly on the short side. The "closer
dense for more entries" intuition (shorter windows) did **not** survive
walk-forward. Research lineage: `density_multi_probe.py` →
`density_multi_walkforward.py` → `density_multi_slotsweep.py`.
EOF
