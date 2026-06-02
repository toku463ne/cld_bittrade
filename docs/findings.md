# Research Findings — what the deep-data backtests actually showed

A running log of empirical observations, newest first. This records *what we
learned* (including dead ends), so the same ground is not re-explored. Per-strategy
mechanics live in `docs/strategy/`; the numbers behind these claims are reproducible
via the probe scripts in `src/backtest/analysis/`.

---

## 2026-06-02 — No directional edge on deep data; the fee model was wrong

### Headline

On ~5 years of BTC/JPY history, **no directional entry we tested has a tradeable
edge** — trend-following, mean-reversion, and cross-venue lead-lag are all
net-negative, and remain negative even with **zero** trading cost. Separately, we
found and corrected a significant error: the simulator was charging the bitFlyer
**spot** fee on a **commission-free** venue, over-penalising every prior backtest
by ~5–10×. Correcting it improved the numbers but did **not** reveal a hidden edge.

### Data

Backtests moved from a thin ~1-month `FX_BTC_JPY` window to the full **GMO_BTC_JPY**
proxy history (2021-04-15 → 2026-06, imported to the `bt` DB at 1m/5m/15m/1h via
`src/data/import_gmo.py`). GMO is the deep-history stand-in; the live venue is
bitFlyer `FX_BTC_JPY`. The thin FX window had produced optimistic, sample-illusion
metrics (e.g. zigzag_bounce DR 0.58–0.62) that did not survive depth.

### The cost-model correction (important)

bitFlyer `FX_BTC_JPY` — now **bitFlyer Crypto CFD**, formerly Lightning FX, same
product code/API — has **0% trading commission**, verified from the official API
(`GET /v1/me/gettradingcommission` returns `commission: 0`). The simulator's
`DEFAULT_FEE_RATE = 0.001` (0.1%/side, 0.2% round-trip) was the bitFlyer **spot**
fee schedule, wrongly applied to the commission-free FX/CFD venue.

Corrected (`src/simulator/simulator.py`): `DEFAULT_FEE_RATE → 0.0002`, i.e.
**commission 0 + ~2 bp/side taker slippage** (half-spread). Real slippage is
~1–2 bp in calm markets and balloons to 10–20 bp in the volatile bursts where
signals fire, so the old flat 0.2% was a bad *constant* but a not-crazy *slippage
proxy for aggressive taking in fast markets*. Not modelled (situational):
**SWAP** (~0.04%/day, only if a position is held across the daily clearing) and
**SFD** (Special Fee for Deviation, only when the CFD price deviates ≥5% from
spot). A `fee_rate`/`--fee` knob now threads through `run_cycle` for cost sweeps.

### Results (deep GMO history, NET unless noted)

Cost sweep on `zigzag_bounce` 1h (`src/backtest/analysis/cost_sensitivity_rerun.py`):

| per-side cost | IS Sharpe | OOS Sharpe |
|---------------|-----------|------------|
| 0 bp (frictionless) | **−0.033** | +0.025 |
| 2 bp (realistic calm) | −0.046 | +0.009 |
| 5 bp | −0.066 | −0.015 |
| 10 bp (old, wrong) | −0.098 | −0.054 |

Even at **zero cost** the in-sample Sharpe is negative — the strategy is edgeless,
not fee-killed. DR on deep data = **0.511** (coin flip; was 0.58–0.62 on the thin
month), calibration Spearman ρ ≈ 0.03.

All directional hypotheses, frictionless (the decisive test):

| hypothesis | timeframe | best result (frictionless) | verdict |
|------------|-----------|----------------------------|---------|
| Mean-reversion (`zigzag_bounce`) | 1h | IS Sharpe −0.033 | no edge |
| Trend: HH/HL swing breakout | 1h | Sharpe −0.099 | no edge |
| Trend: HH/HL swing pullback | 1h | Sharpe −0.200 | no edge |
| Trend: sloped trendline / fan | 5m | ~0 gross | no edge (removed) |
| Cross-venue lead-lag (Binance→JP) | 1m | gross **+0.35 bp/trade** | negligible |

Trend-following was swept across 3 timeframes × 4 swing sizes × 2 exit styles
(symmetric ZS TP/SL and ATR trailing) — uniformly net-negative.

### Cross-venue lead-lag, specifically

Binance `BTCUSDT` vs GMO `BTC/JPY` are co-integrated **within the bar**:
contemporaneous return correlation **+0.96 (5m) / +0.92 (1m)**; the lead-1
correlation is **−0.002 (5m) / +0.026 (1m)**. There is a real but microscopic
~1-minute lead worth **~0.35 bp/trade gross** — far below any tradeable threshold
and impossible to capture against arbitrage bots from a REST/WS retail stack.
Probe: `src/backtest/analysis/cross_venue_leadlag_probe.py` (pulls Binance dumps
from data.binance.vision, aligns with GMO on UTC).

### Why this matters / interpretation

- **The fee was a red herring for the edge question.** Trend, mean-reversion, and
  cross-venue all have a *gross* edge at or below ~0. Removing the (overstated)
  fee makes the numbers less bad but does not manufacture alpha.
- **The trendline approach was abandoned for a principled reason:** a 2-point line
  has too many degrees of freedom — with distant anchors a sub-degree slope change
  flips bounce/break/no-touch. It was effectively curve-fitting; the probe confirmed
  ~0 gross edge. Code removed (`zigzag_trendline` sign/strategy); the generic
  two-anchor reference-line plumbing (`ref2_*`) + viz overlay were kept as reusable
  infra.
- **Mean-reversion is not special:** `zigzag_bounce` was the prior "best config,"
  but that rested entirely on the thin-month sample. On deep data DR is a coin flip.

### Method (so this is reproducible and trusted)

Each entry was evaluated with a **faithful composite-walk probe**: enter at
`open[fire+1]` (two-bar fill), walk the live exit bar-by-bar (SL/trail before TP,
pessimistic), report per-trade return NET of cost, in two views — *entry-quality*
(every fire walked independently) and *portfolio* (single-position, flat-only,
skip-while-busy). Probes live in `src/backtest/analysis/`:
`swing_structure_probe.py`, `cross_venue_leadlag_probe.py`,
`cost_sensitivity_rerun.py`, `trendline_fan_probe.py` (+ `trendline_fan_viz.py`).

### What remains open (not falsified)

The one path with a different P&L source is **maker / spread-capture**: with 0%
commission, a passive quoter *earns* the ~1–2 bp spread instead of paying it. That
is a **market-making** strategy (P&L = spread − adverse selection − inventory
risk), not a directional prediction — a gross-zero directional signal is not made
profitable by capturing the spread. Assessing it requires **forward order-book and
trade-tape collection** (no history exists) plus the live execution layer
(`src/execution/`). Untested. Other untested information sources: order-flow /
book imbalance, funding/basis positioning, liquidation-cascade reversion — all
likewise need forward microstructure data.

### Bottom line

A minimum-lot **taker** bot has **no demonstrated edge** on BTC/JPY across
trend-following, mean-reversion, and cross-venue lead-lag, even at correct
(commission-free) economics. Further tuning of these signals is fitting noise. A
positive result requires either a genuinely new information source (microstructure)
or a different economic model (maker spread-capture) — both gated on forward data
collection we have not yet started.
