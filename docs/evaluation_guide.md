# Evaluation Guide — concepts and mathematics

A from-first-principles explanation of how we evaluate signs and
strategies in this codebase. Read this before `docs/evaluation_criteria.md` (which is the decision rubric — "ship if DR ≥ X") — this guide explains *what those numbers mean and why we trust them*.

> **Note**: This file is adapted from
> [cld_trade_advisor/docs/evaluation_guide.md](https://github.com/toku463ne/cld_trade_advisor/blob/main/docs/evaluation_guide.md)
> for BTC/JPY scalping. Key adaptations: zigzag window uses the selected
> timeframe (not daily bars); walk-forward uses monthly periods (not fiscal
> years); regime split uses BTC ATR regime (not N225); the only traded
> instrument is FX_BTC_JPY.

---

## 0. The problem we're solving

We have detectors that fire on BTC/JPY bars ("sign **fires**" — events). We
want to know:

1. **Does the sign predict price direction?** (per-fire question)
2. **If it does, does using it actually make trading money?** (strategy question)

These are not the same question. A sign can be a great predictor and a
terrible strategy contributor (because it duplicates other signals, or
fires at bad times, or the strategy doesn't pick it). The pipeline
below answers both, in order.

---

## 1. Anatomy of a fire and its outcome

When a detector "fires" on bar T for product FX_BTC_JPY, we record:

- `fired_at` = datetime of bar T
- `product` = FX_BTC_JPY (the only traded instrument)
- `score` ∈ [0, 1] = the detector's confidence (sign-specific formula)

To measure outcome we look **ahead** in the bar series. Specifically,
we find the next confirmed zigzag peak within ~30 bars **on the selected
timeframe** and ask: **did the next major swing go UP or DOWN from the fire?**

- `trend_dir = +1` if next peak is HIGH (price went up) — long wins
- `trend_dir = -1` if next peak is LOW (price went down) — short wins
- `magnitude` = abs(peak_price − entry_price) / entry_price
- `signed_return = trend_dir × magnitude` (this is the "what would a
  long trade have returned" number)

**Why zigzag and not "price 10 bars later"?** Fixed-horizon returns
mix noise with signal. Zigzag confirms a real swing, so the outcome
measures whether the sign predicted a **structural move**, not noise.

The convention throughout this codebase: **DR is the rate at which
trend_dir = +1** (i.e., "after the fire, did the next swing go UP?").
A sign with DR = 60% means: 60% of its fires were followed by an UP
swing before a DOWN swing.

A "short-direction" sign just inverts: short DR = 1 − long DR. So a
sign with long DR = 40% works as a short signal (60% of its fires were
followed by a DOWN move first).

---

## 2. Per-fire metrics (does the sign predict at all?)

### 2.1 Direction Rate (DR)

The simplest metric: **what fraction of fires were followed by a UP
swing?**

```
DR = wins / total_fires
   = sum(1 for fire if fire.trend_dir > 0) / n
```

| DR value | Meaning                                                    |
|----------|------------------------------------------------------------|
| 50%      | coin flip — sign predicts nothing                          |
| 53%      | barely useful — needs lots of samples to be sure it's real |
| 55-57%   | mildly informative                                         |
| 60%+     | strongly informative (rare in practice)                    |

**Why it's not enough alone:** DR ignores magnitude. A sign with DR
55% but tiny moves is worse than DR 52% with big moves. Also, DR 53%
on 50 fires might be coincidence; DR 53% on 5000 fires is real.

### 2.2 Mean signed return (mean_r)

```
mean_r = sum(fire.signed_return for fire) / n
       = sum(fire.trend_dir × fire.magnitude for fire) / n
```

This is the **average per-fire long-side return**. If you went long
on every fire and held to the next zigzag, this is your average
return. Combines direction (DR) and magnitude.

| mean_r | Interpretation                           |
|--------|------------------------------------------|
| 0%     | break-even (loses to costs and slippage) |
| +0.5%  | weak edge                                |
| +1-2%  | useful edge                              |
| +3%+   | strong edge                              |

### 2.3 Binomial test (p)

Question: "Is DR meaningfully different from 50%, given the sample size?"

Math: under H₀ (DR = 50%), the number of wins follows a binomial
distribution Binom(n, 0.5). The p-value is the probability of getting
DR as extreme as observed (or more) under H₀.

```
p = P(X ≥ wins | n trials, prob=0.5)   # two-sided in practice
```

| p         | Interpretation                  |
|-----------|---------------------------------|
| p < 0.001 | very unlikely to be coincidence |
| p < 0.05  | "significant" by convention     |
| p > 0.10  | could easily be random noise    |

**Limitation:** assumes fires are independent. In reality fires may
cluster (multiple bars fire on the same BTC market event), so a small
p may overstate significance. We address this with the permutation
test below.

### 2.4 Permutation test (perm_p)

Question: "Is the sign's DR better than what we'd get by firing on
random bars?"

Math: shuffle the fire dates 1,000 times. For each shuffle, compute
DR with the shuffled-date outcomes. Then:

```
perm_p = (count of shuffles with shuffled_DR ≥ real_DR) / 1000
```

| perm_p | Interpretation                                                |
|--------|---------------------------------------------------------------|
| < 0.05 | sign's DR is real — better than random fire dates             |
| > 0.10 | DR could be explained by "BTC tends to drift up" or similar   |

**Why this is stronger than the binomial test:** the binomial test
assumes flat 50/50. But BTC has a bullish drift in some periods, so
random fires might naturally have DR > 50%. Permutation preserves the
drift and asks "is your *timing* informative?"

### 2.5 Regime split (bear_DR vs bull_DR)

Some signs work only in one market regime. We compute DR separately
for fires when BTC was in a bear regime vs bull, defined by ATR:

```
bear regime = ATR(14) > 1.5 × its 50-bar average   (high volatility)
bull regime = ATR(14) ≤ 1.5 × its 50-bar average   (low volatility)

bear_DR = (wins among fires in bear regime) / (fires in bear regime)
bull_DR = (wins among fires in bull regime) / (fires in bull regime)
```

If a sign has overall DR 54% but bear_DR 65% and bull_DR 47%, it's a
**bear-regime sign** — useful only in high-volatility BTC conditions.
We'd then gate it to fire only in bear regimes.

### 2.6 EV decomposition

`mean_r` (§2.2) combines win frequency and trade-size info into one
number. Decomposing it reveals which of those is doing the work:

```
EV = P(win) · E[win] + P(loss) · E[loss]      (E[loss] is negative)
   = win_rate · avg_win − (1 − win_rate) · |avg_loss|
```

This is algebraically the same as `mean_r`, but separating the
components tells us:

- **High win rate, small wins** vs **low win rate, big wins**
- **Whether losses are well-controlled** (small |E[loss]|) or
  occasionally catastrophic
- **Kelly fraction** for sizing: `f* = EV / E[win²]` — needs the
  decomposition

Example reading: a sign with DR 55%, avg_win +2%, avg_loss −5% has
EV = 0.55 × 2 − 0.45 × 5 = +1.1 − 2.25 = −1.15%. The high win rate is
illusory — the rare losses overwhelm the frequent small wins.

Output tables include columns for `P(win)`, `avg_win`, `avg_loss`, and
an `EV check` that should ≈ `mean_r` (sanity check on the decomposition).

### 2.7 Multiple comparisons — Benjamini-Hochberg FDR

When we test many signs across many months and regime cells, we run
hundreds of significance tests. At p<0.05, about 5% of tests will
"pass" by chance alone.

**False Discovery Rate (FDR)** is the expected fraction of "passes"
that are flukes. Controlling FDR at 5% means: of the tests we call
significant, ≤ 5% are false discoveries.

The **Benjamini-Hochberg (BH)** procedure adjusts p-values to control
FDR. Given `m` sorted p-values `p₁ ≤ p₂ ≤ … ≤ pₘ`:

```
q(p_k) = min over j ≥ k of  (p_j × m / j)      (capped at 1.0)
```

A test with `q < 0.05` is "FDR-significant." We apply BH **within
each sign family** (`ema_*`, `bb_*`, etc.) since within-family signs
share data paths and aren't statistically independent.

---

## 3. Score calibration (does the score rank fires?)

Beyond "does the sign predict on average?", we ask "does the **score**
within the sign predict which fires are better?"

If yes, we can use score to **rank** candidates when multiple signs fire
on the same bar.

### 3.1 Spearman rank correlation (ρ)

```
ρ = cov(rank_score, rank_return) / (std(rank_score) × std(rank_return))
```

| ρ     | Interpretation                         |
|-------|----------------------------------------|
| 0.00  | no relationship — score is noise       |
| 0.05  | weak                                   |
| 0.10  | mildly informative                     |
| 0.20+ | strong (very rare in single-fire data) |

**Why rank correlation, not Pearson directly?** BTC returns have fat
tails — a few huge wins/losses dominate Pearson. Ranks are robust to
that.

### 3.2 Quartile EV table

Sort fires by score, split into 4 equal buckets (Q1 = lowest 25%,
Q4 = highest 25%), and show DR + mean_r per bucket.

```
For each quartile q ∈ {1, 2, 3, 4}:
  fires_q  = fires whose score is in quartile q
  DR_q     = wins(fires_q) / |fires_q|
  mean_r_q = sum(signed_return) / |fires_q|

Q4 − Q1 spread = mean_r_4 − mean_r_1
```

| Q4−Q1 spread | Verdict                        |
|--------------|--------------------------------|
| > +2pp       | INFORMATIVE — score adds value |
| +0.5 to +2pp | WEAK — borderline              |
| < +0.5pp     | NOISE — drop the score         |

---

## 4. Strategy-level evaluation

Per-fire metrics tell us "the sign predicts." But a **strategy** is
the full pipeline: load signs → rank → pick entries → hold until exit
fires → track P&L.

A sign with great per-fire DR might never get picked (because other
signs rank higher), or might fire only when the strategy is already in
a position, or might cluster with other signs (false diversification).
So per-fire pass ≠ strategy uplift.

### 4.1 Sharpe ratio (per-trade)

```
Sharpe = mean(trade_returns) / std(trade_returns)
```

| Sharpe | Interpretation                                     |
|--------|----------------------------------------------------|
| < 0    | losing strategy                                    |
| 0 - 1  | break-even-ish                                     |
| 1 - 2  | useful                                             |
| 2 - 3  | strong                                             |
| 3+     | excellent (often too good — check for overfitting) |

**Important caveat:** with small n (e.g., 25 trades/month), Sharpe has
HUGE variance. Don't read a 0.2 Sharpe difference as meaningful at
small n.

### 4.1.1 Sortino ratio

```
downside_returns = [r if r < 0 else 0 for r in trade_returns]
Sortino = mean(trade_returns) / std(downside_returns)
```

Only downside volatility is in the denominator. Strategies with
asymmetric returns get a more honest assessment.

| Sharpe vs Sortino  | What it tells you                                    |
|--------------------|------------------------------------------------------|
| Sortino ≈ Sharpe   | symmetric return distribution                        |
| Sortino > Sharpe   | upside-skewed (good — big wins inflate Sharpe's std) |
| Sortino << Sharpe  | downside-skewed (bad — Sharpe is masking tail risk)  |

### 4.2 Win rate

```
win_rate = (trades with positive return) / total_trades
```

Complement to Sharpe. A high-win-rate-low-Sharpe strategy has many
small wins and few big losses (or vice versa).

### 4.3 Walk-forward (monthly) structure

To avoid overfitting, we evaluate month-by-month:

- All months except the most recent 20% = **training/historical**
- Most recent 20% of available bars = **out-of-sample (OOS)**

For each month, we use the **prior** month to build regime rankings
(which (sign, ATR regime) cells perform best). Then evaluate the
strategy on the month's actual bars. No future data leaks into the
ranking.

**The OOS period is the cleanest signal** because no fitting decisions
used its data. When OOS is strong, it's a positive sign. When OOS is
weak but training months are strong, the strategy may be overfit.

### 4.4 Per-month consistency

A strategy with avg Sharpe +3 across 10 months is great. But if 6 of
the 10 months are negative and 4 are very positive, it's fragile.

We require **≥ 4/5 months non-negative** for ship decisions. This
penalizes high-variance strategies that look great on aggregate but
have hidden risk.

### 4.5 Per-period breakdown

Report metrics aggregated by one natural unit per timeframe:

| Timeframe | Period unit |
|-----------|-------------|
| 1m        | 1 hour      |
| 5m        | 1 day       |
| 15m       | 1 day       |
| 1h        | 1 week      |

Per-period columns: `period`, `n_fires`, `DR`, `total_return`,
`max_DD`, `win_rate`.

Displayed as a scrollable table in the Backtest tab sidebar.

---

## 5. A/B testing (the binding gate)

After per-fire benchmarking passes, we run an A/B at strategy level:

- **Arm A (baseline)** — current production strategy
- **Arm B (variant)** — same strategy with the proposed change

Both arms use the SAME bars, SAME exit rules, SAME portfolio cap —
ONLY the proposed change differs. Sharpe / win% / per-month
consistency are compared.

### Why per-fire ≠ strategy A/B

Three concrete reasons:

1. **Rank crowding**: a sign's cells may never win the ranking against
   other signs' cells. Per-fire DR doesn't matter if the strategy
   doesn't pick the sign.
2. **Confluence dilution**: adding more bullish signs to a "fire if
   ≥N valid signs" gate may let the gate fire on weaker stacks.
3. **Counter-intuitive lift**: per-fire regression in a period can
   be filtered out by the confluence gate, resulting in strategy
   improvement.

### Pre-registered decision rule

Before running, we **commit to the gate** in the code:

```
SHIP variant if:
  (a) avg Sharpe at production N gate ≥ baseline Sharpe
  (b) ≥ 4/5 months non-negative
```

If we change the rule after seeing results, we're cheating
(motivated reasoning). Pre-registration forces honesty.

### 5.4 Marginal contribution analysis

Aggregate Sharpe/mean_r tells you whether the variant is better, but
hides WHY. When testing "add sign X to confluence", also report
**per-trade marginal metrics**:

| Metric                | Math                                                         | Tells us                                                 |
|-----------------------|--------------------------------------------------------------|----------------------------------------------------------|
| **Δ trade count**     | `n(B) − n(A)`                                                | turnover impact (more trades = more costs)               |
| **Δ max drawdown**    | `dd(B) − dd(A)`                                              | did adding X make the worst-case loss worse?             |
| **Daily correlation** | Pearson corr of per-period return series A vs B              | high (>0.7) = duplication, low (<0.3) = real diversification |
| **Tail-hedge lift**   | `mean(B on A's worst quintile periods) − mean(A on those)`   | does X cushion when baseline loses?                      |
| **New-trade win rate**| `wins / total` among trades B has that A doesn't             | quality of the marginal trades introduced                |

---

## 6. The full pipeline (visual)

```
PROBE (cheap, in-memory)
↓ "is this even worth implementing?"
PASS: candidate feature has fire-rate + directional bias
│
↓
CANONICAL BENCHMARK (scripts/rebenchmark_sign.sh)
↓ runs in DB; produces benchmark.md tables
│  - per-month DR + p + perm_p
│  - bear/bull ATR regime split
│  - score calibration (Spearman ρ + quartile EV)
PASS: DR > 53% pooled, ≥ 2/5 months perm_pass, score may or may not be informative
│
↓
STRATEGY A/B
↓ same data, with/without the change
PASS: Sharpe ≥ baseline, ≥ 4/5 months non-negative
│
↓
SHIP — update production defaults or constants
│
↓
REBENCH — update DB to match production
UPDATE docs/analysis/<feature>.md with final numbers
```

Each gate filters. Skipping a gate risks shipping noise.

**A probe that says "this is amazing" but no canonical/A/B follow-up
is not a ship signal.**

---

## 7. Common pitfalls

### 7.1 Per-fire pass ≠ strategy uplift

A sign can pass canonical (DR 53%+ pool) but be trade-for-trade
identical to "without the sign" in strategy and dilute confluence.

**Always run strategy A/B before shipping a load-bearing sign.**

### 7.2 Probes can overstate or invert

Probes use `detect_peaks` on the FULL bar series → peaks settled by
post-fact data → cleaner outcomes than what live trading sees.

The canonical pipeline uses `_first_zigzag_peak` on a 30-bar window
from the fire → matches what's knowable at decision time.

### 7.3 Small sample Sharpe is noisy

A single month with 25 trades has ±2 Sharpe noise. Pooled across 10
months, ±0.5. Don't read 0.2 Sharpe gaps as meaningful at single-month
level.

### 7.4 Score calibration takes large n

Spearman ρ needs n ≥ 200-500 fires per sign to be measurable.
Quartile EV needs at least 40 fires (10 per quartile). Below that
sample size, "score is noise" might just mean "we don't have enough
data to tell."

### 7.5 Strict gates flip negative on cohort changes

A change that PASSES on pooled months may FAIL when re-segmented by
sub-cohort (e.g., per-month, per-ATR-regime). This is why we require
both pooled CI AND per-month consistency.

---

## 8. Decision rules (the rubric)

The actual ship/reject thresholds are in `docs/evaluation_criteria.md`:

- Materiality: DR ≥ +1pp at n ≥ 1,000 or ≥ +2pp at smaller n
- Sample size: drop of ≥ 50% in n must be justified
- EV direction: sign-flip is material
- Per-month: ≥ 4/5 non-negative for strategy A/B ship

This guide explains the math; that guide explains the gates.

---

## 9. Where the metrics live

| Output                                | Script / Helper                                          | Section in benchmark.md          |
|---------------------------------------|----------------------------------------------------------|----------------------------------|
| Per-month DR / mean_r / perm_p        | `src/backtest/sign_benchmark.py --phase benchmark`       | "Multi-Month Benchmark"          |
| Bear/bull ATR regime split            | `src/backtest/sign_regime_analysis.py`                   | "Regime-Split Analysis"          |
| Spearman ρ + quartiles + q(ρ) FDR    | `src/backtest/sign_score_calibration.py`                 | "Score Calibration"              |
| OOS canonical                         | `src/backtest/sign_benchmark.py --phase backtest`        | "OOS"                            |
| Strategy A/B (Sharpe + Sortino + EV) | `src/backtest/strategy_ab.py`                            | A/B section                      |
| Marginal contribution                 | `src/backtest/marginal.py`                               | A/B "Marginal contribution"      |

To rebench one sign end-to-end: `scripts/rebenchmark_sign.sh <sign_type>`.

---

## 10. Glossary

| Term                     | Meaning                                                                                                                  |
|--------------------------|--------------------------------------------------------------------------------------------------------------------------|
| **Fire**                 | An event when a detector's condition is satisfied on a bar                                                               |
| **DR**                   | Direction Rate — fraction of fires followed by an UP swing                                                               |
| **mean_r**               | Mean signed return per fire (long-side perspective)                                                                      |
| **n**                    | Sample size (number of fires)                                                                                            |
| **perm_p**               | Permutation-test p-value (DR vs random-date DR)                                                                          |
| **p (binomial)**         | DR vs 50% under independent-flip assumption                                                                              |
| **bear_DR / bull_DR**    | DR conditional on BTC ATR regime at fire time                                                                            |
| **Spearman ρ**           | Rank correlation of score with signed return                                                                             |
| **Q4 − Q1 spread**       | Top-quartile mean_r minus bottom-quartile mean_r                                                                         |
| **Sharpe**               | mean / std of per-trade returns                                                                                          |
| **win_rate**             | Fraction of trades with positive return                                                                                  |
| **Sortino**              | mean / std_of_DOWNSIDE_returns — penalizes only losses, not upside variance                                              |
| **EV decomposition**     | Splitting mean_r into P(win)·E[win] + P(loss)·E[loss] — same number, more info                                          |
| **avg_win / avg_loss**   | Mean return among trades with r>0 / r<0 respectively                                                                    |
| **BH-FDR**               | Benjamini-Hochberg False Discovery Rate adjustment                                                                       |
| **q-value (q)**          | BH-adjusted p-value — q<0.05 means "FDR-significant"                                                                    |
| **Sign family**          | Group of signs sharing a prefix (ema_*, bb_*, etc.) — used as the BH-FDR grouping unit                                  |
| **Marginal contribution**| Per-trade comparison of A vs B (turnover, drawdown, daily corr, tail-hedge) beyond aggregate Sharpe                      |
| **Tail-hedge lift**      | How much arm B helps on arm A's worst-quintile periods                                                                   |
| **Daily correlation**    | Pearson corr of per-period returns A vs B — high = trades duplicate, low = real diversification                          |
| **Monthly period**       | The walk-forward unit in this project (replaces fiscal year)                                                             |
| **OOS**                  | Out-of-sample — most recent 20% of available bars, not used in any fitting decision                                      |
| **Walk-forward**         | Train on months ≤ T-1, test on month T                                                                                   |
| **A/B test**             | Run strategy twice differing only in the proposed change                                                                 |
| **Pre-registered gate**  | Decision rule committed in code BEFORE seeing results                                                                    |
| **Product**              | FX_BTC_JPY — the only traded instrument in this codebase                                                                 |
| **Bear regime**          | ATR(14) > 1.5× its 50-bar average (high volatility)                                                                     |
| **Bull regime**          | ATR(14) ≤ 1.5× its 50-bar average (low volatility)                                                                      |
| **Confluence**           | Strategy that fires when ≥ N bullish signs are valid on the same bar                                                     |
| **Canonical**            | The official pipeline (`sign_benchmark.py`) — windowed per-fire zigzag                                                   |
| **Probe**                | A one-off exploration script — usually cheaper, often less rigorous                                                      |

---
