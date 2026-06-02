# Research Findings — what the deep-data backtests actually showed

A running log of empirical observations, newest first. This records *what we
learned* (including dead ends), so the same ground is not re-explored. Per-strategy
mechanics live in `docs/strategy/`; the numbers behind these claims are reproducible
via the probe scripts in `src/backtest/analysis/`.

---

## 2026-06-02 (latest) — Maker / market-making pivot: closed (efficiently priced)

### Headline

The one direction with positive-expectancy *potential* — stop paying the spread,
**earn** it as a maker on commission-free FX_BTC_JPY. Tested on **1.36M real
bitFlyer tape executions** (33 days, w/ aggressor side, already in the bt DB).
**Closed: no retail-accessible edge.** The spread exactly compensates adverse
selection (efficient market); the only profitable maker variant is speed/queue
based, which a retail REST/WS bot cannot replicate.

### Step 1 — spread vs adverse selection (`maker_spread_probe.py`)

Effective spread ~**1.3 bp** (side-based) / 0.70 bp (Roll); adverse selection ~**0**
(slightly favorable, −0.02 to −0.07 bp) over horizons 5–500 trades. Encouraging —
spread > adverse unconditionally. But that's an upper bound: the 1.3 bp touch is
owned by latency-advantaged HFT; retail is back-of-queue.

### Step 2 — quote-distance fill sim (`maker_quote_distance_probe.py`)

Rest a limit at distance d from mid, fill on trade-through (limits fill at the
limit price — no gap bug), resolve a symmetric ±d first-passage barrier from
subsequent trades (win = reverts +d to mid before −d adverse). **Win rate ≈ 0.50
at EVERY distance** (1 bp → 50 bp): 0.496 / 0.498 / 0.499 / 0.499 / 0.503 / 0.502.
Net ≈ 0 (the d=30/50 positives are <1.5σ noise with 8–40% unresolved).

Flat 0.50 across three orders of magnitude is the **martingale signature**: from
the fill point the price is a random walk, so first-passage to ±d is 50/50 at every
scale. The maker's "free half-spread" is illusory — the fill is informative, and
the spread precisely compensates adverse selection (textbook efficient market).
Step 1 looked positive because it measured a tiny *unconditional drift*; step 2's
*first-passage barrier* (how a maker actually exits at target/stop) is the relevant
test, and it's flat.

### Why it's actually negative for retail, and the verdict

Those 0.50s are the **optimistic** trade-through fills. A retail bot is
back-of-queue and latency-behind, so it fills disproportionately on the adverse
side → win rate **below 0.50** → net **negative**. The HFT makers who profit do so
via speed/queue priority (cancel before adverse), structurally unavailable to a
REST/WS retail stack. There is no order book collected (only the tape), so a
queue-aware sim isn't even possible — but the martingale result makes it moot.

**Closed.** Combined with all directional results, the full honest tally:
**no retail-accessible edge on BTC/JPY** — across directional entries (every
timeframe, signal, and fill mechanic) AND market-making.

---

## 2026-06-02 (later) — Daily momentum: a lead that failed validation

### Headline

Tested whether a **daily** timeframe escapes the intraday dead-end (intraday
mean-reverts; daily momentum is a different, well-evidenced phenomenon). It
produced the project's **first positive gross edge** — but it **failed
validation**: the result is in-sample / regime-only, out-of-sample negative, not
statistically significant, and largely long-side beta. **Reject.**

### Does daily "clear the spread issue"? No — it swaps spread for SWAP carry.

On daily bars the bid/ask spread is negligible vs a 2–4% daily move. But a daily
strategy **holds for days**, paying the bitFlyer FX/CFD **SWAP point**
(~0.04%/day ≈ **4 bp/day**, a flat charge to open positions at the daily clearing).
Always-in-market that is ~14.6%/yr of carry. Daily does not remove cost; it
relocates it from a one-time spread to a per-day carry that, on multi-day holds,
**exceeds** the spread it removed. (SWAP rate is an estimate — verify before trust.)

### Signals (GMO daily, 5.1y, buy & hold = +67%)

`src/backtest/analysis/daily_momentum_probe.py` (signals) +
`daily_momentum_validate.py` (rigor). NET includes swap.

- **Time-series momentum** (sign of trailing L-day return, always in market):
  L=30 gross Sharpe **0.82** / net **0.55** (+151%); L=60 net 0.26; L=120 net 0.10.
- **Donchian breakout** (Turtle): 55/20 gross +76% / net +31% (Sharpe 0.09, n=23);
  20/10 net-negative.

### Why it fails validation (TSMOM-30, the strongest)

| test | result |
|------|--------|
| Full-sample net Sharpe | +0.55, **t = 1.23** (insignificant; ~2 needed) |
| IS net (2021–2025) | Sharpe +0.66, +153% |
| **OOS net** (2025-05→2026-06) | **Sharpe −0.06, −2%** |
| Per-year net ≥ 0 | **3/6 years** (ship gate ≈ 4/5) |
| Long vs short contribution | long **+187%** / short +37% |

The edge lives entirely in strong-trend years (2021/2023/2024); the choppier
held-out year is flat-negative → trips the project's own **OVERFIT** flag. There is
*some* genuine crisis-alpha (2022: strat −10% vs B&H **−73%** — it shorted the
crash), but it is not persistent and most of the gross is just being long in a bull
market. Donchian 55/20 also flips OOS-negative (IS +48% → OOS −17%).

### The structural reason it can't be confirmed here

Time-series momentum is real, but its statistical power comes from **breadth** —
CTAs run it across *dozens* of markets at once, and the diversification makes the
Sharpe reliable. On a **single BTC/JPY instrument over ~5 years** (≈5 independent
trend regimes) it is inherently underpowered; you cannot reach significance, and
OOS here it is negative. Cross-market breadth is out of scope for this
single-instrument bot.

### Verdict

Least-dead idea of the project (real theory, positive gross, genuine 2022
crash-avoidance) but **not shippable**: OOS-negative, fails per-year consistency,
insignificant, mostly beta. Does not change the overall conclusion below.

### Addendum — daily *bounce* (mean-reversion at levels) is anti-predictive

Also tested the mirror idea — does price *bounce* at prior daily zigzag levels (a
daily zigzag_bounce, motivating a maker limit-at-the-level entry)?
`src/backtest/analysis/daily_bounce_signal_probe.py` (signal DR/EV only — does not
model limit fills). Across every tolerance (0.5–2%) and horizon (3–10 d), **DR is
0.31–0.51 and mean_r is negative** (−0.9% to −3.3%/event); the long side fails even
*with* the +67% up-drift as a tailwind. So daily levels **break through more than
they hold** — the exact mirror of the momentum result (daily *continues*, it does
not *fade*). This kills the daily-bounce signal and makes the maker-limit-entry
refinement moot: a better fill can't rescue a worse-than-random direction (and
adverse selection on resting limits would make the real fills worse than this
already-negative OHLC estimate).

And the **stop/breakout** entry (trade the *break* of the level, not the fade)?
`src/backtest/analysis/level_reaction_probe.py` on 1h: across tol 0.3–1% and
horizon 6–24 bars, **fade DR ≈ 0.50–0.52** (mildly −EV) and **breakout DR ≈
0.45–0.48** (below chance). Breakout `mean_r` turns faintly positive only at long
horizons (the momentum tail) but is tiny, sub-threshold, and optimistic (a stop
fills beyond the level). So on 1h the level is **directionally empty both ways** —
fade fails, breakout fails — and no entry mechanic (early-peak, limit, or stop)
can fill into a signal with no edge. Levels don't predict, period.

And the **confirmed-bounce stop** (reach the level, arm a stop just beyond it,
enter only if price reverses back through the trigger — filtering breakdowns)?
`src/backtest/analysis/confirmed_bounce_stop_probe.py` on 1h: with realistic
gap-aware fills, a small trigger (0.5%) is **identical to the plain fade** (DR ~0.51,
−EV — ~all touches "confirm" so it filters nothing), and a *large* trigger (2–3%)
that genuinely filters breakdowns makes DR **worse** (0.45–0.47): you enter after
the easy bounce, at a worse price, into the exhaustion. The breakdown-filter
intuition backfires because the level signal is empty — confirming a reversal just
gets you in late on a non-edge.

> **Fill-realism lesson (important).** The *first* run of this probe showed DR 0.65 /
> mean_r **+0.43%** — a huge fake edge from a **fill bug**: it credited the stop fill
> at the trigger price even when the bar gapped *above* it, handing the long a
> fantasy entry near the low. The `conf% = 100%` tell flagged it; filling at the
> gapped open instead erased the edge entirely. A naive stop-fill backtest will
> *manufacture* alpha — model the gap, or you will ship noise.

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
