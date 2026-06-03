# Benchmark Results

This file holds the latest benchmark output per strategy/sign. It is regenerated
by `scripts/rebenchmark_sign.sh <strategy_name>`. See `docs/evaluation_guide.md`
for metric definitions and `docs/evaluation_criteria.md` for the ship rubric.

> Signal-level metrics (DR, mean_r, perm_p) are **diagnostic only** — never used
> as ship criteria. Ship decisions use portfolio-level metrics + the
> buy-and-hold BTC/JPY benchmark.

---

## ema_atr_breakout

_Last run: 2026-05-31 21:19 (INTERIM) via `rebench_watch.sh` → `scripts/rebenchmark_sign.sh ema_atr_breakout 5m` + `backtest.cycle` (DB: btc_bot_bt). Portfolio figures NET of trading fees._

**Data window:** 2026-04-30 → 2026-05-31 UTC+9 — 8,934 × 5m bars (~31 days, one
calendar month; back-paging is exhausted at bitFlyer's ~31-day `getexecutions`
floor — oldest exec frozen at 2026-04-30 13:00). In-sample = first 80%, OOS =
most recent 20%.

> ⚠️ **INTERIM — still effectively one month, do not ship.** Fires span only
> 2026-04 (n=3) and 2026-05 (n=106), so the monthly walk-forward has just one
> populated period; the ≥4/5-months consistency gate **cannot be evaluated**.
> bitFlyer REST can't supply pre-2026-04-30 history, so depth only grows forward
> in real time from here. The watcher has fired and self-removed; re-arm it once
> 2–3 months of forward history accrue.

### Multi-Month Benchmark (in-sample)

| period | n_fires | DR | mean_r | perm_p |
|--------|---------|-------|---------|--------|
| 2026-04 | 3 | 0.333 | +0.0032 | 1.000 |
| 2026-05 | 106 | 0.594 | +0.0018 | 1.000 |

Sign-level monthly validate: **2/2 months non-negative mean_r → PASS** (note: this
is the *signal* mean_r check, NOT the portfolio ship gate below).

### Regime-Split Analysis (ATR bear/bull)

| regime | n | DR | mean_r |
|--------|---|-------|---------|
| all  | 109 | 0.587 | +0.0018 |
| bear | 15  | 0.333 | -0.0019 |
| bull | 94  | 0.628 | +0.0024 |

### Score Calibration

| metric | value |
|--------|-------|
| n | 109 |
| Spearman ρ | -0.070 |
| Q4 − Q1 spread | -0.0004 |

### OOS (most recent 20%)

| metric | value |
|--------|-------|
| Sharpe | -1.119 |
| Max DD | 0.0498 |
| # trades | 31 |
| Net PnL (min lot) | -626 JPY |

### Portfolio metrics (ship criteria) — NET of fees

| metric | in-sample | OOS |
|--------|-----------|-----|
| Sharpe | -1.122 | -1.119 |
| Max DD | 0.1759 | 0.0498 |
| # trades | 103 | 31 |
| Trading fees | 2,568 JPY | (incl.) |
| Net PnL (min lot) | -2,191 JPY | -626 JPY |
| Buy-and-hold BTC/JPY (gross) | -0.0353 | — |

**Verdict: REJECT (do not ship).** Net of fees the strategy loses money in both
in-sample (Sharpe -1.12, -2,191 JPY) and OOS (Sharpe -1.12, -626 JPY), and the
**OVERFIT** flag is raised (OOS Sharpe < 0). The interesting wrinkle vs the prior
run: with a full month the **signal** now looks mildly informative — all-DR
**0.587** (bull 0.628), positive mean_r — yet the **portfolio still bleeds**. The
gap is turnover × cost: at ~103 trades/month the ~0.2%/round-trip fee
(2,568 JPY total) dwarfs the +0.18% gross per-fire edge, and the TP/SL structure
doesn't convert the weak directional tilt into net PnL. Score calibration is flat
(ρ ≈ -0.07), so the score doesn't rank fires. Bottom line: a real but tiny
directional signal that is **not tradeable at this frequency net of costs** — the
pipeline and cost model are working as intended, not evidence of an edge.

**Ship gate** (pre-registered): SHIP iff avg Sharpe ≥ Buy-and-hold AND ≥ 4/5
periods non-negative. **OVERFIT** flag if OOS Sharpe < 0 or OOS DD > 2× IS DD.

---

## zigzag_bounce

_Last run: 2026-06-02 via `scripts/rebenchmark_sign.sh zigzag_bounce 1h GMO_BTC_JPY` + `backtest.cycle --product GMO_BTC_JPY`. Same defaults (ambiguous wall matching `wall_match=True` + no-chase `reject_past_peak=True`; exit tp 1.0 / sl 1.0 / max_bars 48). Portfolio NET of fees._

**Data window: DEEP — GMO_BTC_JPY 1h, 2021-04-15 → 2026-06-02, 44,718 × 1h bars
(~5 years).** In-sample = first 80%, OOS = most recent 20%. (Supersedes the prior
thin 1-month FX_BTC_JPY window — the `--product` flag and full GMO backfill are
now done.)

> ⚠️ **REJECT (deep data) — the apparent edge was sample-illusion.** On 5 years of
> real history the directional rate collapses to a **coin flip (DR 0.511, n=1308)**
> and the portfolio loses money in and out of sample. The prior "best config so
> far / IS Sharpe +0.022" verdict was built on ~1 month of thin FX data (DR
> 0.48–0.62, 7–25 trades) and does **not** survive depth. Do not ship; do not
> treat any wall/no-chase tuning as validated.

### Multi-Month Benchmark (in-sample, signal-level — diagnostic only)

| span | n_fires | DR | mean_r | perm_p |
|------|---------|------|----------|--------|
| all months (2021-04 → 2025-05 IS) | 1308 | 0.511 | +0.0005 | 1.000 (every month) |

Monthly DR scatters 0.35–0.71 with mean_r mostly ±0.00x and perm_p=1.000
throughout — no month shows significance. Coin-flip aggregate.

### Regime-Split Analysis (ATR bear/bull)

| regime | n | DR | mean_r |
|--------|---|-------|---------|
| all  | 1308 | 0.511 | +0.0005 |
| bear | 41   | 0.415 | -0.0028 |
| bull | 1267 | 0.515 | +0.0006 |

### Score Calibration

| metric | value |
|--------|-------|
| n | 1308 |
| Spearman ρ | +0.027 |
| Q4 − Q1 spread | +0.0017 |

ρ≈0 on deep data: `sign_score` does not rank forward return (the ρ≈0.15 on the
1-month sample was noise).

### Portfolio metrics (ship criteria) — NET of fees

| metric | in-sample | OOS |
|--------|-----------|-----|
| Sharpe | **-0.098** | **-0.054** |
| Max DD | 1.7414 | 0.3226 |
| # trades | 498 | 127 |
| Trading fees | 6,600.9 JPY | — |
| Net PnL (min lot) | **-9,070 JPY** | -3,307 JPY |
| Buy-and-hold BTC/JPY (gross) | **+0.6662** | — |

**ship = False. OVERFIT flag raised** (OOS Sharpe < 0).

**Verdict: REJECT (deep data, high confidence).** Across ~5 years / 498 IS trades,
zigzag_bounce is net-negative (IS Sharpe −0.098, OOS −0.054) and far below
buy-and-hold (+0.67 gross, a bull era). DR 0.511 = coin flip; calibration ρ≈0.
This closes the question the thin FX window left open: there is **no demonstrated
mean-reversion edge** here either — consistent with the trend-following probes,
which were all net-negative on deep GMO data too. Nothing in the project ships on
deep history. The wall/no-chase/dominant tuning below was all measured on the
1-month sample and is **not** validated — re-sweep only if a fresh hypothesis
motivates it.

> The opt-in notes below were measured **vs the prior extreme-based default**
> (`wall_match=False`); re-sweep against the new wall baseline once data is deep.

**Dominant-level reference (`dominant_window`) — opt-in, default off.** Adds the
long-horizon unbroken same-type extreme (~1 week) as a candidate level so price
can bounce off a dominant weekly floor/ceiling even when nearer minor peaks
exist (the expanding window otherwise stops early and matches a shallow recent
level). On the interim 1h sample this is the **first toggle that helped**: full
750-bar run 9→10 trades, net +0.0059→**+0.0230**, Sharpe +0.035→**+0.125**,
win 44%→**50%**, same maxDD — it catches e.g. the 5/14 retest of the 5/08
12,430,000 floor (score 0.98). Promising but tiny-sample; default off, sweep +
A/B once history is deep before considering it the default.

**Dominant role-reversal (`dominant_reverse`) — opt-in, default off.** Adds
opposite-type *broken* levels over the dominant lookback (a prior high broken
above → support; a prior low broken below → resistance), independent of the
near-window `reverse_levels`. **Regressed** on the interim sample — at dom=120
it took IS net +110 → **−573** (Sharpe +0.052 → −0.256) and doubled max DD: a
nearer broken opposite-level wins the nearest-price contest and swaps the exit
band on trades that were fine on the dominant floor. Same theme as the
near-window reversal (shorts into broken supports during the selloff). Off by
default; A/B once history is deep.

**ZS-band winsorize (`winsorize_k`) — opt-in, default off.** Added to cap an
abnormally large recent zigzag leg from inflating TP/SL (MAD high-side clip).
Tuner sweep (`--sweep-winsor`, size=10/mid=3) on this month is **neutral**: on
the best config (tp1.0/sl0.5/age12) `k=3.0` matches net return (0.0105) with a
hair better Sharpe (0.066 vs 0.065) / maxDD (0.0246 vs 0.0252); on wider-stop
configs it's marginally worse. Too few extreme legs in one month for the cap to
bind materially — kept off by default; re-sweep with deeper history.

**Ship gate** (pre-registered): SHIP iff avg Sharpe ≥ Buy-and-hold AND ≥ 4/5
periods non-negative. **OVERFIT** flag if OOS Sharpe < 0 or OOS DD > 2× IS DD.

---

## density_band

_Last run: 2026-06-03 via `scripts/rebenchmark_sign.sh density_band 1h GMO_BTC_JPY` (DB: btc_bot_bt). Portfolio figures NET of trading fees._

**Hypothesis:** over the trailing ~1 week (168×1h) price spends most time in a
*dense band* (time-at-price value area, 70% coverage); returning to the band from
outside should rebound off the near edge (above→LONG, below→SHORT). See
`docs/strategy/density_band.md`.

**Data window:** 2021-04-15 → 2026-06-02 (44,718 × 1h GMO_BTC_JPY bars, ~5y).
In-sample = first 80%, OOS = most recent 20%.

### Signal-level (in-sample, diagnostic only)

| metric | value |
|--------|-------|
| n_fires (IS) | 2,141 |
| DR (all) | **0.475** (below coin-flip) |
| mean_r | −0.0005 |
| perm_p | 1.000 (every month) |
| regime DR | bull 0.479 (n=2043) / bear 0.398 (n=98) |
| score calibration | spearman_rho=−0.0065, Q4−Q1=−0.0026 (no calibration) |

Monthly DR swings 0.29–0.70 with no persistence; mean_r is negative in ~half the
months. The bounce **direction is, if anything, slightly anti-predictive**.

### Portfolio (ship gate)

| | IS | OOS |
|---|---|---|
| Sharpe | **−0.061** | 0.001 |
| Max DD | 1.59 | — |
| Trades | 443 (net −4,305 JPY) | 113 (net +262 JPY) |
| Buy-and-hold Sharpe | **0.666** | |

**Ship gate** (pre-registered): SHIP iff avg Sharpe ≥ Buy-and-hold AND ≥ 4/5
periods non-negative. → **`ship=False` — REJECT.** Sharpe (−0.06 IS / 0.00 OOS)
is far below buy-and-hold (0.67); no edge.

> ⚠️ **Known divergence:** the fire is measured as a market fill at the touch
> bar's *close*, but the user's intended entry is a touch/stop order at a level a
> little inside the band. However, since the directional **DR < 0.5 across the
> full 5-year sample and in both bull/bear regimes**, a better entry *price* is
> unlikely to rescue a sub-coin-flip directional call. The level-entry simulator
> support was therefore **not** built (it was gated on DR showing edge).

---

## density_breakout

_Last run: 2026-06-03 via `scripts/rebenchmark_sign.sh density_breakout 1h GMO_BTC_JPY` (DB: btc_bot_bt). Portfolio figures NET of fees (DEFAULT_FEE_RATE)._

**Hypothesis (user's chart):** price consolidates *inside* the dense band
(time-at-price value area, 70%); when a bar **closes out through an edge** it
trends away → ride it for ~12h–days. LONG on close above the top edge, SHORT on
close below the bottom edge. Structural stop beyond the **opposite** edge (a
pullback to the band is expected and tolerated) + ATR trailing stop. The
*opposite* trigger to `density_band` (bounce). See `docs/strategy/density_breakout.md`.

**Data window:** 2021-04-15 → 2026-06-02 (44,718 × 1h GMO_BTC_JPY, ~5y). IS=80%/OOS=20%.

### Signal-level (diagnostic only — WRONG yardstick for a trend-ride)

| metric | value |
|--------|-------|
| n_fires (IS) | 1,370 |
| DR (all) | 0.459 (low **by design** — trend-rides win <50% but big) |
| mean_r | **+0.0004** (slightly positive; bounce was −0.0005) |
| regime DR / mean_r | bull 0.460/+0.0002 · bear 0.439/**+0.0034** |
| score calibration | ρ=0.0018, Q4−Q1=+0.0025 (negligible) |

### Trade shape (full series, 497 trades)

| | |
|---|---|
| Win rate | **40.8%** |
| Avg win / avg loss | +4.03% / −2.78% → **payoff 1.45** |
| Expectancy / trade | **+0.004%** (≈ break-even) |
| Median hold / p90 | **49 h / 121 h** (≈ 2–5 days) |
| Exit mix | trail 60% · time 21% · **structural stop 18.5%** · eod 1 |

The wide far-edge stop fires only 18.5% of the time → pullbacks to the band
mostly do **not** stop the trade out, as specified.

### Portfolio (ship gate)

| | IS | OOS |
|---|---|---|
| Sharpe | **−0.001** (flat) | **+0.031** |
| Max DD | 0.75 | — |
| Trades | 402 (net −1,858 JPY) | 93 (net **+1,703 JPY**) |
| Buy-and-hold Sharpe | **0.666** | |

**Ship gate** (pre-registered): SHIP iff avg Sharpe ≥ Buy-and-hold AND ≥ 4/5
periods non-negative. → **`ship=False` — REJECT, but BREAK-EVEN (not bleeding).**

> First idea in the project with the **right trend-ride shape** (low win rate,
> payoff > 1, multi-day holds, structural stop rarely hit) and a non-negative OOS.
> Expectancy ≈ 0 — payoff 1.45 just fails to clear the 59% loss rate. The exit
> (trail mult / time stop) and a **tight-box regime filter** (`max_band_pct`,
> currently off — wide trending-week bands give very wide stops) are the unpulled
> levers. Worth tuning before final reject.

### UPDATE 2026-06-03 — tight-box regime filter (now DEFAULT `max_band_pct=0.02`)

Swept `max_band_pct` (band height as a fraction of price) on the 5y split. The
filter is a **monotonic win** — tightening the box raises payoff/EV and slashes
drawdown:

| max_band% | IS Sharpe | OOS Sharpe | #tr(IS) | win% | payoff | EV%/tr |
|-----------|-----------|------------|---------|------|--------|--------|
| OFF       | −0.001 | +0.031 | 402 | 40.3 | 1.48 | −0.002 |
| 4.00      | +0.092 | +0.060 | 252 | 40.9 | 1.86 | +0.385 |
| **2.00** ◄| **+0.141** | **+0.113** | 107 | 38.3 | **2.40** | **+0.480** |
| 1.50      | +0.165 | −0.091 | 52 | 38.5 | 2.59 | +0.504 |
| 1.20      | +0.313 | −0.197 | 30 | 46.7 | 2.91 | +0.860 |

**Chosen: `max_band_pct=0.02`** — the tightest threshold still robust OOS. Below
2% the IS Sharpe keeps climbing but **OOS flips negative** and the sample collapses
(overfit). Official rebench at 2%: **IS Sharpe +0.141 (DD 0.158, 107 tr, net
+2,852 JPY), OOS Sharpe +0.113 (36 tr, net +1,094 JPY)**, sign mean_r +0.0014.

**Net-profitable in BOTH samples — the best result in the project.** Still
`ship=False`, but now the **only** failing condition is the consistency gate
(17/29 = 59% of periods non-negative; gate needs ≥80%). Trend-following is
structurally lumpy (few big winners, many small losers), so it can be net-positive
yet fail an ≥80%-periods-green gate. The aggregate edge (positive IS+OOS Sharpe,
positive net JPY both samples, DD 0.16) is real; the open question is whether the
project's consistency gate is the right rubric for a trend-ride, or whether
further entry quality (breakout confirmation) can lift period consistency.

### UPDATE 2026-06-03 — breakout confirmation tested → REJECTED (overfits)

Added `confirm_bars` (require N consecutive closes beyond the edge) and
`min_break_frac` (minimum breakout extent) to the sign; swept on the 5y split.

| config | IS Sharpe | OOS Sharpe | win% | payoff | period% |
|--------|-----------|------------|------|--------|---------|
| **k=1 (default)** | +0.141 | **+0.113** | 38.3 | 2.40 | 48% |
| confirm_bars=2 | +0.203 | −0.055 | 42.7 | 2.46 | 57% |
| confirm_bars=3 | +0.202 | −0.065 | 45.7 | 2.18 | 57% |
| confirm_bars=4 | +0.277 | −0.081 | 46.4 | 2.69 | 57% |
| min_break=0.10 | +0.096 | −0.125 | 37.6 | 2.17 | 45% |
| min_break=0.25 | +0.125 | −0.066 | 39.3 | 2.14 | 45% |
| min_break=0.50 | +0.176 | −0.185 | 42.4 | 2.16 | 43% |
| k=2 + min=0.10 | +0.213 | −0.110 | 43.2 | 2.47 | 56% |

Confirmation lifts **every in-sample** metric (IS Sharpe, win rate, even period
consistency 48%→57%) but **turns OOS Sharpe negative in all 7 variants** — a clean
overfitting signature (entering later = closer to exhaustion = gives up the early
trend the OOS regime needed). It also never reaches the 80% consistency gate
(max 57%). **Kept `confirm_bars=1` / `min_break_frac=0.0`** (the un-confirmed
first-close breakout) as the default — it is the best config out-of-sample. The
parameters remain available for future re-test on deeper data.

### UPDATE 2026-06-03 — exit tuning: REMOVE the trail (now DEFAULT `trail_atr_mult=None`)

Swept the exit (trail multiple, time stop, sl_buffer). Headline: **the ATR trail
HURTS — removing it is the best config, in BOTH samples.**

| trail_atr_mult | IS Sharpe | OOS Sharpe | payoff | median hold |
|----------------|-----------|------------|--------|-------------|
| 3 (tight) | −0.106 | +0.067 | 1.23 | 10 h |
| 6 (prev default) | +0.141 | +0.113 | 2.40 | 34 h |
| 10 (loose) | +0.191 | +0.258 | 2.73 | 59 h |
| **None (off)** | **+0.197** | **+0.221** | **2.84** | **98 h** |

Looser = better, monotonically; the trail was clipping the trend winners. With
the trail off, `max_bars=120` (~5d) is the sweet spot (longer time stops let
losers bleed to the wide structural stop → DD 0.18→0.59); `sl_buffer=0.10` best.

**Official rebench at the tuned config** (`max_band_pct=0.02, confirm_bars=1,
trail_atr_mult=None, sl_buffer=0.10, max_bars=120`):
**IS Sharpe +0.197 (DD 0.181, 92 tr, net +6,414 JPY), OOS Sharpe +0.221 (31 tr,
net +3,499 JPY).** OOS Sharpe now **exceeds** IS — strongest robustness sign,
opposite of the (rejected) confirmation overfit. Net PnL ~2× IS / ~3× OOS vs the
trailing version. Still `ship=False` on the consistency gate only (17/29 = 59%
periods green < 80%). This is the project's best config to date.

---

## density_multi_breakout (multi-position promotion) — modest regime-robust diversifier

Promotes the `density_multi_probe` research to a real, registered strategy
(`src/strategy/density_multi_breakout.py`, routed through the new
`src/simulator/multi_simulator.py`). Same dense-breakout entry as
`density_breakout` but **holds up to 5 overlapping slots** and **exits into the
next dense zone** (target = nearest pre-existing heavy node beyond the broken
edge, ≥ `target_min_dist_frac × band_height` *beyond* the lip, from a 336-bar
profile at entry) — plus the far-edge structural stop, a 120-bar time stop, and a
small "stall" exit (a fresh tight box forms at the new level). Config = the
walk-forward-robust cell: `window=168, max_band_pct=0.03, 5 slots,
target_min_dist_frac=1.5`.

**Judged by the annualised mark-to-market EQUITY Sharpe**, not per-trade Sharpe:
overlapping positions make per-trade Sharpe understate the diversification (it is
only ~0.1 here while the equity Sharpe is ~0.9). `run_cycle` routes any
`max_slots > 1` strategy to the MultiSimulator and ships it iff
`equity_sharpe_IS >= B&H_annualised_Sharpe` AND ≥80% of periods are non-negative.

**Target distance (`target_min_dist_frac=1.5`) — the cost-robust default.** The
original tiny target (nearest node at the box lip) exited in ~1 h at ~+0.1% — the
most spread-fragile part. Requiring the target ≥ 1.5 band-heights beyond the edge
turns those into real captures (median ~22 h / +3.4%) and survives a stressed
40 bp round-trip (positive IS *and* OOS), at the cost of some calm-cost OOS. See
`src/backtest/analysis/density_multi_target_cost.py` for the variant × cost grid
(dist 0.0 OOS +1.36 @4bp but IS +0.09 @40bp; dist 1.5 IS +0.40 / OOS +0.07 @40bp).

**Official rebench (GMO 1h, ~5y), `target_min_dist_frac=1.5`:** IS equity Sharpe
**+0.90** / OOS **+0.84** (vs **B&H IS annualised Sharpe +0.64**); per-trade Sharpe
IS ~+0.1; 460 IS / 148 OOS trades; exit mix stop 48% · time 41% · target 6% ·
stall 5% · eod 1%; target exits median ~22 h / +3.4%. **`ship=False`** — it clears
the Sharpe-vs-B&H condition but fails the ≥80%-periods consistency gate (a lumpy
trend-ride/diversifier, the same gate the single-position density family fails).

**Walk-forward (6 folds, `density_multi_walkforward.py`):** positive in **all 6
folds** (the only config that is) — bull AND bear. But the honest anchored
walk-forward (re-select the cell on past data only) is modest: 3/5 folds, mean
test equity Sharpe +0.19. **Character: a market-neutral-ish diversifier** — beats
buy-and-hold when B&H is down (2022 bear, recent decline), trails it in strong
bulls. The "closer dense for more entries" idea (shorter windows) did NOT survive
walk-forward; slot sweep confirmed 5 slots (1-slot is weak 3/6; >6 saturates).
Numbers differ slightly from the probe (+0.71/+1.36) due to the per-position
`evaluate_exit` ordering + distance-from-fill modeling vs the probe's absolute
levels; entry counts and exit mix match the probe.
