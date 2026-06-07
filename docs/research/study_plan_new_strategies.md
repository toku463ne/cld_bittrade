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

## Strategy B — pick a DIFFERENT family (decision pending)

B must be low-correlation to **both** density_pullback **and** Strategy A. If A is a
pairs/ratio strat, B should *not* be another pair (two ratio strats co-move). Shortlist:

| candidate | family | diversification odds | data/effort |
|---|---|---|---|
| **B1 Seasonality / time-of-day** | calendar | high (orthogonal to price structure) | light (have data) |
| **B2 Volatility-regime breakout** | realized-vol expansion | medium (vol ≠ direction) | light |
| **B3 ETH/BTC ratio pair** | cross-asset ratio | **low vs A** (same family) → avoid if A is A2 | medium |
| **B4 Order-flow / microstructure** | tick imbalance | high | heavy (needs tick data) |

**Recommendation:** if A = ratio pairs (A2), make **B = B1 seasonality** or **B2 vol-regime**
— genuinely orthogonal families, both data-light. Decision to confirm before Stage 1.

---

## Sequencing & current status

- **Now:** density_pullback at 0.001 lot accruing its forward record; reserve in BTC.
- **A:** Stage 0 (import BCH) → Stage 1 probe → go/no-go. *Start here.*
- **B:** confirm the family choice, then same workflow.
- Capital only flows to a strategy after Stages 1–6 pass; each scaled in steps as its
  forward Sharpe accrues (certainty-asymmetry discipline — backtest ≠ realized).

## Pre-registration log (fill BEFORE running each stage)
- A1 lead-lag kill threshold: _TBD before probe_
- A2 reversion edge vs cost threshold: _TBD before probe_
- B family chosen: _TBD_
- Per-strategy ship/consistency/correlation thresholds: as in the gates table above.
