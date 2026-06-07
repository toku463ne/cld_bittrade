# Study plan — 2 new diversifying strategies

Goal: add **two** new strategies for the research-reserve sleeve (the 50% of capital
held as BTC until validated). Each must independently clear **three** gates before it
gets reserve capital — pre-registered here *before* results (eval §6):

1. **Ship gate** — annualised **equity Sharpe ≥ buy-and-hold's own in BOTH IS and OOS**
   (`src/backtest/cycle.py`), AND the **relative quarterly-consistency** gate
   (non-neg fraction ≥ B&H's). [CLAUDE.md § Ship criteria]
2. **Forward confirmation** — registered in `src/backtest/paper_forward.py`, run weekly,
   must read **CONFIRMED** (forward equity Sharpe ≥ B&H over post-lockbox bars) before
   sizing past the 0.001 lot.
3. **Diversification gate** — **|correlation| to density_pullback AND to BTC ≲ 0.30**
   (bar-return correlation). This is the whole point of the sleeve: a high-Sharpe
   strategy correlated 0.7 with what we already hold adds risk, not diversification.
   (Measured matrix: `density_multi_breakout` is **0.68** with density_pullback →
   already excluded as a "new" strategy; it is the same density edge.)

> **Rule:** change one variable at a time (eval §6.6); never iterate against the
> walk-forward; record every gate threshold in this doc before running.

---

## Shared per-strategy workflow (each stage can KILL)

| Stage | Action | Kill criterion (pre-registered) |
|---|---|---|
| **0. Data** | Import + cache the asset(s) (`import_gmo --symbol … --product …`). | — |
| **1. Edge probe** | Measure the raw edge where *n is large* (5m/15m, 100k+ bars), net of a **realistic** GMO cost (0.04%/day funding + a stressed spread). | No bucket separates winners from losers *net of cost* in **both** an early and late split → KILL. |
| **2. Build** | `signs/<name>.py` + `strategy/<name>.py` (inherit base), register. | — |
| **3. Ship gate** | `run_cycle` on the traded timeframe (1h default). | Equity Sharpe < B&H in IS *or* OOS → not shippable. |
| **4. Robustness** | Walk-forward (fixed config across 6 folds), cost-sensitivity sweep, one-knob sanity. | < 4/6 folds positive, or edge dies at stressed cost → demote. |
| **5. Correlation** | Bar-return corr vs density_pullback + BTC. | \|corr\| > ~0.30 to either → reject (not a diversifier). |
| **6. Forward** | Add to `paper_forward`; accrue. | Not CONFIRMED → stays at 0.001 lot, no reserve capital. |

Capital is gated **sequentially** (validate → size → next), even though research can run
in parallel.

---

## Strategy A — "trade BCH referring BTC" (cross-asset)

**Why it fits:** a second asset (BCH) related to BTC is structurally different from our
density breakout/bounce family, and a *ratio* or *relative* signal tends to be
market-neutral → naturally low BTC-correlation (the diversification we want).

**Prior art / caution:** `cross_venue_leadlag_probe.py` already found cross-*venue*
lead-lag net-negative (REJECTED). Cross-*asset* (BCH vs BTC, same venue) is different,
but the same lesson applies: **lead-lag edges decay fast and are usually arbitraged at
1h** — so Stage 1 must test it net of cost and probably at 5m/15m, and BCH's **worse
liquidity / wider spread** makes the cost bar *higher* than BTC.

**Stage 0 — data (one-liner, no code change):**
```
uv run --env-file .env.bt python -m src.data.import_gmo \
    --symbol BCH_JPY --product GMO_BCH_JPY --from 2021-04-15 --to <today> --timeframe all
```
Then `load_cache(tf, product="GMO_BCH_JPY")` alongside `GMO_BTC_JPY`.

**Stage 1 — edge probe** (`src/backtest/analysis/bch_btc_probe.py`, to build): align BCH
& BTC bars on timestamp and measure **three** hypotheses, pre-registering the kill bar
for each (DR/return separation must survive ~0.04%/day funding + a stressed BCH spread,
in both an early and a late split):

- **A1 lead-lag** — cross-correlation of BTC returns vs *future* BCH returns at lags
  1…N bars. Edge = BCH under-reacts to a BTC move and catches up. Probe on 5m/15m.
  *Expect decay; likely KILL at 1h.*
- **A2 ratio mean-reversion (pairs)** — `log(BCH/BTC)` z-score over a rolling window;
  measure the **half-life** of reversion and the return to fading |z|>k. Market-neutral
  (long BCH / short BTC, or vice-versa). **Recommended primary** — lowest expected BTC
  correlation, plays to a statistical-arb edge rather than a speed race.
- **A3 BTC-regime filter** — does conditioning BCH entries on a BTC regime (trend/vol)
  add edge? A weaker, fallback framing.

**Design sketch (if A2 survives):** a `BchRatioSign` fires when `|z(log(BCH/BTC))| > k`;
the strategy trades BCH (and hedges with BTC for true neutrality, or trades BCH
outright if the ratio edge transmits) with a **mean-reversion exit** (TP at z→0, stop at
z→±k₂, time stop). Note this needs a *different* exit from the ride framework (which
targets continuation, not reversion) — define it fresh. Both legs need the GMO leverage
product (to short) → funding on both.

**A-specific kill criteria:** ratio half-life ≫ tradeable horizon; reversion edge <
round-trip cost on BCH; or corr to BTC/density_pullback > 0.30.

---

## Strategy B — Dynamic Range-Detected Grid Trading

**Why it fits:** it is the **mechanical complement of density_pullback** — same tight-box
regime detector, opposite payoff. density_pullback trades the *break OUT* of the box; the
grid trades the *oscillation INSIDE* it. When the box holds the grid wins (and the
pullback's breakout entries stop out small); when the box breaks the grid flattens (and
the pullback rides). So it should be **low-/negatively-correlated** with density_pullback
(the diversification we want) while reusing one detector. Family is also distinct from
Strategy A (ratio pairs).

**Concept (range fade, not always-on grid):** detect a range → lay a capped grid of
resting limits inside it → harvest oscillation → flatten on breakout or at the trade cap.

**Design (reuse-first):**

- **1. Range detection** — reuse the density **value-area tight box** (`band_height ≤
  max_band_pct × price` over a window) as both the trigger *and* the bounds, **confirmed**
  by low ATR(14) (trailing-percentile) and/or high **Choppiness Index** (`_chop_series`,
  high = sideways). Fire a range episode only when box-tight AND (low-vol or choppy).
- **2. Grid params** — bounds = the detected box `[lo, hi]`; `n` levels evenly spaced,
  **step = (hi−lo)/(n+1)**, with `n` scaled to band height; per-level size = min lot.
- **3. Trade cap = n levels** — one position per level → **max exposure = n × lot**,
  bounded by construction (the core risk control).
- **4. Exit (three triggers)** — per-level **take-profit** (close a fill at the next grid
  line, the profit engine); **breakout / box-invalidation** (close beyond `lo/hi` + buffer,
  or the box stops being tight) → **flatten all**; **time / max-fill backstop**.
- **Harness reuse:** a grid is a stack of resting limits → emit it via the
  `Signal.limit_price`/`limit_expiry_bars` support already in `MultiSimulator`; minimal
  new code. Multi-position book is already there.

**The risk to respect (short-gamma):** grids make many small wins while the range holds
and one big loss on the breakout (accumulated inventory on the wrong side) — "pennies in
front of a steamroller." The cap + flatten-on-breakout keep the tail finite, but the edge
is not free. **Two strategy-specific pre-registered kill criteria** (beyond the shared
gates):

- **B-kill-1 (cost/turnover):** grids fire many fills; the Stage-1 probe must show the
  net-of-cost oscillation capture > the breakout loss × breakout frequency, at realistic
  GMO cost (0.04%/day funding + a stressed spread). If the edge dies on cost → KILL. This
  is tested **first**.
- **B-kill-2 (tail / DD):** because a short-gamma payoff flatters the Sharpe ship gate,
  gate it **additionally on the breakout-loss distribution and max-DD**, and require it to
  survive the worst breakout regimes (2022 crash, 2024 bull) — not Sharpe alone.

---

## Sequencing & current status

- **Now:** density_pullback at 0.001 lot accruing its forward record; reserve in BTC.
  BCH 1h import (Strategy A Stage 0) running.
- **A:** Stage 0 (import BCH) → Stage 1 probe (A2 ratio reversion primary) → go/no-go.
  *In progress.*
- **B (Dynamic Range-Detected Grid):** chosen. Follows A; reuses the density box detector
  + the limit-order harness. Expected low/negative correlation to density_pullback (its
  mechanical complement) — that correlation is itself a Stage-5 confirmation, not an
  assumption.
- Capital only flows to a strategy after Stages 1–6 pass; each scaled in steps as its
  forward Sharpe accrues (certainty-asymmetry discipline — backtest ≠ realized).

## Pre-registration log (fill BEFORE running each stage)
- A1 lead-lag kill threshold: _TBD before probe_
- **A2 reversion (pre-registered 2026-06-07, before results)** — PASS Stage 1 iff ALL hold:
  (i) AR(1) **half-life of `log(BCH/BTC)` < 96 bars** (4 days — reverts within a tradeable
  horizon); (ii) the **hedged-spread** reversion trade (enter at `|z|≥k`, exit on `z`-cross-0
  or `max_hold`) has **mean net return > 0 in BOTH the early and late half**, net of 2-leg
  cost = 0.04%/day funding/leg + **15 bp/leg round-trip** spread; (iii) **|corr(Δlog-ratio,
  Δlog-BTC)| < 0.30** (the spread is genuinely BTC-neutral); (iv) the edge holds across a
  **majority** of `k∈{1.5,2.0,2.5} × window∈{120,168,336}` cells, not one mined corner.
  Diagnostics also reported: DR, n, the outright-BCH (1-leg) variant as a fallback. Miss any
  of (i)–(iv) → KILL A2 (fall back to A1 or A3).
- B family chosen: **Dynamic Range-Detected Grid Trading** (range fade inside the density
  tight box; capped grid of resting limits; flatten on breakout).
- B-kill-1 (cost/turnover) threshold: _TBD before probe_
- B-kill-2 (breakout-tail / max-DD) threshold: _TBD before probe_
- Per-strategy ship/consistency/correlation thresholds: as in the gates table above.
