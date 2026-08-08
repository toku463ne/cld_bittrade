# Trend-Following Rule Construction — 小次郎講師 (Kojiro Koushi), *真・トレーダーズバイブル*

Source: 『小次郎講師流 目標利益を安定的に狙い澄まして獲る 真・トレーダーズバイブル ——Vトレーダーになるためのルール作り』 (小次郎講師). A Japanese trading-rules manual built on two pillars: **(1) the Turtles' money/risk-management chassis** (ATR-volatility unit sizing, the 2N stop, pyramiding, Donchian breakout entries) and **(2) the author's own trend engine — 移動平均線大循環分析 (moving-average "great-cycle" analysis) and 大循環MACD.** The book's thesis: *entry rules only locate the エッジ (edge); survival and the year's P&L are decided by money management, risk management, and 増し玉 (pyramiding)* — so the entry signal is "one element of a trade rule," not the rule.

The book is **timeframe- and instrument-agnostic** and is taught with the standard MA params **5 / 20 / 40** (bar counts, on any timeframe). The author's native habitat is **intraday FX and futures** (nested 5/15/30-min or 30/60/240-min sets) — which is essentially **cld_bittrade's domain: BTC/JPY on 1m–1h bars**. So the mechanical content (MA-stack stages, Donchian channels, ATR units, MACD pairs) transfers cleanly; crypto's 24/7-continuous, high-volatility, intraday-trend-persistent character arguably fits this trend system *better* than a daily-stock port. The final section (`Adaptation Notes for cld_bittrade`) is the reader's own mapping to this repo's signs/strategies/exits and is **NOT from the book**. cld_bittrade is **single-instrument + automated**, so the binding evaluation is the CLAUDE.md **ship gate** (annualised equity Sharpe ≥ buy-and-hold BTC/JPY in **both** the IS and OOS splits, plus per-quarter non-negative fraction ≥ B&H's) — there is no cross-sectional or fill-order test here. Everything below the book sections is a **hypothesis to benchmark, not a validated edge.**

---

## Part 0 — Foundations (Edge, Expected Value, Probability)

### Edge (エッジ) — trade only where one side is favored (p.2, p.37, p.84-86)

Price up/down is normally **50/50 (フィフティフィフティ)**. An "edge" exists only in the rare moments when buy *or* sell is clearly favored — the canonical case being **a trend in progress** (uptrend → only "buy" has an edge; never short an uptrend). **Rule:** read where the edge is, take positions only in the edge direction, otherwise do not trade (休む). Explicitly forbidden: shorting an uptrend because an oscillator says "overbought (買われ過ぎ)" or because "it's about due for a top." A buy signal means *"buy-side has an edge here (probability)"* — **not** *"price will go up (prediction)."* Realistic attainable win-rate ≈ 60%, at most 70%.

- **Codeable as:** `edge_long = trend_state == UP` (大循環 stage bullish, or price > rising long-MA). Gate mean-reversion/oversold buys on the trend filter being up; veto a short generated purely from `RSI>70` while trend is up.

### No prediction / state-reactive design (p.3)

"Turtles do not predict and do not pretend to read the future" (quoting 『タートル流投資の魔術』 and 一目山人's 一目均衡表原著). Voicing a forecast anchors you → you cherry-pick confirming news, refuse to loss-cut, and **average down into losers** (the biggest blow-up mode).

- **Design constraint:** rules condition on bar-T realized state, never a predicted future path. **Forbid add-to-loser logic** (see ナンピン below).

### Trade Edge / Expected Value (TE) — the "勝利の方程式" (p.4-6, p.86-88, p.96-97)

```
TE (期待値) = win_rate × avg_profit − loss_rate × avg_loss      [avg_loss as positive magnitude]
            = L·I − M·J        (L=win_rate, M=1−L, I=avg_win, J=avg_loss)
```

TE > 0 → wins over many trades (law of large numbers, 大数の法則); TE < 0 → loses. **Win-rate alone is meaningless:** an 80%-win rule can lose (8×10 − 2×50 → TE −2万); a 30%-win rule can win. Annual P&L decomposes as **`annual_PnL = TE × annual_trade_count`** ⇒ to raise annual profit at low TE, **increase the number of names traded** (raises count without forcing no-edge trades on one name). Turtle baseline: win 35-40%, RR ≈ 3.

- **Codeable as:** `te = win_rate*mean_win - (1-win_rate)*mean_loss`; this is the per-sign mean per-trade return — already the repo's primary backtest metric. Accept iff `TE>0` AND trade count adequate.

### Risk-Reward (RR) ratio & break-even table (p.7-9, p.88, p.97)

```
RR (PR) = avg_profit / avg_loss          win condition: RR > (1 − win_rate) / win_rate
```

Break-even RR by win-rate (RR above → winner, below → loser):

| win% | 10 | 20 | 30 | 40 | 50 | 60 | 70 | 80 | 90 |
|---|---|---|---|---|---|---|---|---|---|
| break-even RR | 9.00 | 4.00 | 2.33 | 1.50 | 1.00 | 0.67 | 0.43 | 0.25 | 0.11 |

RR > 1 = **損小利大** (cut losses small, let profits run); the typical losing JP retail trader has win% ~60% but RR ~0.33 (損大利小). Win-rate obsession (勝率至上主義) causes premature profit-taking + held losers.

- **Codeable as:** acceptance gate `rr > (1−win_rate)/win_rate`; ZsTpSl exit design target = realized RR clears the win-rate-implied threshold (typically aim RR ≥ 2-3).

### Cognitive-bias catalogue (priors for sign design) (p.44-48)

①損を出したくない病 (disposition effect — hold losers, cut winners) ②サンクコスト病 (sunk-cost) ③結果にこだわりすぎ病 ④**値ごろ病** (anchoring to "cheap/expensive" vs *past* price — explicitly: a price level relative to the past is meaningless; only the future matters) ⑤バンドワゴン病 (herding) ⑥**小数の法則信仰病** (law-of-small-numbers — distrust "N-year cycle" claims; a pattern needs ≥300 random samples to validate). Items ④ and ⑥ directly back this repo's small-sample / OOS-overfit discipline (distrust a backtest edge that rests on few trades or one regime).

---

## Part 1 — Money & Risk Management (the Turtle chassis)

> The book's central claim: this section, not the entry, is what makes a "Vトレーダー."

### True Range & ATR (the "N") (p.28-33)

```
TR  = max(high − prev_close,  prev_close − low,  high − low)     # accounts for gaps
ATR = average of TR, default N = 20 (≈ 1 trading month) = the book's "N"
```

Three averaging modes, all selectable:
- **SMA:** `ATR = Σ(TR, 20)/20`
- **MMA (Wilder, Turtles' early):** `ATR_t = (ATR_{t-1}×19 + TR_t) / 20`
- **EMA (Turtles' later):** `ATR_t = (ATR_{t-1}×19 + TR_t×2) / 21` — front-loads recency.

ATR measures the instrument's current average daily move; recompute regularly (Turtles weekly; author intra-week on big moves). Repo already has ATR in `src/indicators/`.

### Position sizing — 1 Unit = 1 ATR = 1% of capital/day (p.17-21, p.33, p.60-61, p.90-94)

The single most important formula in the book:

```
1 Unit (1ユニット) = floor_to_lot( (capital × 0.01) / (ATR(N) × lot_size) )
```

i.e. size each position so a **1 ATR adverse move = 1% of capital**. Worked: capital ¥10M, Sony ATR ¥52, lot 100 → 10M×0.01 / (52×100) = 19.23 → 1900 shares. This **volatility-normalizes risk across instruments** (ATR-80 name carries 2× the per-lot risk of an ATR-40 name). Target annual return 10-30% (40%+ high risk, 100%+ unrealistic).

- **Portfolio risk meter:** `portfolio_risk_pct = Σ open units` (each unit = 1%). A trader must always be able to answer "what % am I risking today?"

### Risk of Ruin (破産の確率) — fixed-fractional sizing (p.11-16)

P(ruin) (drawdown ≥ ~90%, unrecoverable) depends on 5 inputs: capital, win%, avg_win, avg_loss, and **per-trade risk % (the lever)**. Key findings: even a +edge ruins if per-trade risk is too large; ruin% rises with per-trade risk; **beyond a threshold ruin% rises abruptly (非線形 knee)**. Standard target: **P(ruin) ≤ 1%**. Adjust *position size*, not stop location.

- **Codeable as:** `risk_per_trade = capital × f` (f ≈ 1-2%); `units = risk_per_trade / (entry − SL)`; keep `f` below the non-linear ruin knee; Monte-Carlo validate to `P(ruin) ≤ 1%`.

### Stop-loss = 2N (2 ATR), outside the noise band (p.34-36, p.58-61)

Price = **trend + noise**. Place the stop **just outside the noise band** so ordinary pullbacks don't trigger it but a true reversal exits fast. Turtles measured noise ≤ 2 ATR ⇒

```
SL_long  = entry − 2·ATR(N)        SL_short = entry + 2·ATR(N)
```

With 1-unit sizing, a 2N stop = exactly **2% capital loss per unit** (the modern top-trader standard). The book argues the tunable range is **2.0N-3.0N** (default ~2.5N); under 2N is too tight. Always place the stop as a resting 逆指値 at entry; never override discretionarily ("マーケットが常に正しい"). Beware stop-overshoot from gaps / weekend / holiday holds / illiquidity → flatten before long holidays. cld_bittrade's `src/exit/` ATR-trail / `zs_tp_sl` / fixed-TP-SL (`rules.py`) are the analogues (a fixed 2-ATR initial stop = an ATR-trail with `k=2.0`).

### Trailing stop (p.62-64, p.94)

Raise the stop as price advances. Variants: (a) raise by the full rise; (b) raise by **half** the rise (`Δstop = 0.5·Δhigh`) — author's preference, keeps the stop further from price so ordinary pullbacks don't flush you. Turtle ratchet form:

```
N = ATR(N)
while price ≥ last_raise + 0.5N and stop < avg_entry:   stop += 0.5N; last_raise = price   # rush to break-even
after stop > avg_entry:  if price ≥ last_raise + 1.0N:  stop += 0.5N; last_raise = price     # then trail at half-pace
```

Advanced 大循環 profit-exit: place a 逆指値 sell at **yesterday's mid MA value** (`exit if close < SMA20[t-1]`).

### Pyramiding (増し玉) — add to winners only (p.25-27, p.51-52, p.65-67, p.94)

After a winning entry, **add 1 unit each time price moves a fixed ATR increment in your favor**, up to the per-name cap. Two add-spacings:
- **0.5N (base):** add every ½ ATR; max risk at 4 units = 0.5N+1N+1.5N+2N = **5N (5%)**; better average price.
- **1.0N (low-risk):** add every 1 ATR; max risk at 4 units = **2N (2%)**; worse average price.

On **each add, move the single aggregate stop to 2N below the latest fill** and apply it to all units. Anchor stops/adds to **actual** fill prices on slippage. Max 3 adds (4-unit cap).

### Exposure caps by correlation (p.25-27, p.65, p.94)

The diversification rule **always overrides** the add rule:

| Scope | Cap |
|---|---|
| Same name (同一銘柄) | **4 units** |
| Highly-correlated group (相関高い, \|ρ\|≳0.7) | **6 units** |
| Loosely-correlated group (相関ある) | **10 units** |
| One direction, all names (買い or 売り) | **12 units** |
| Concurrent distinct low-corr names | ~3 names |

Rationale: 4 units in one name share one adverse condition; correlated names give **no diversification** ("高い相関関係にある銘柄を複数取引しても分散効果は得られない"). Correlation is **non-stationary** — re-measure each period (worked gold-complex ρ table: NY金 0.92, 東京ゴム 0.83 … ドル/円 −0.23). **On a single-instrument bot this is mostly moot, but it is exactly CLAUDE.md's portfolio-level correlation check before running multiple strategies/pairs live** — treat correlated pairs/strategies as one bet.

- **Codeable as:** before any add, require `units_name+1 ≤ 4 AND units_corr_cluster+1 ≤ 6 AND units_loose+1 ≤ 10 AND units_side+1 ≤ 12`. Closing a unit decrements all group counters.

### ナンピン (averaging-down) — PROHIBITED (p.68-72); 両建て/ツナギ (p.72-77)

**Never add to a losing position.** Trend-followers add up (1000→1100→1200, avg in profit); ナンピン adds down (1000→900→800, avg in loss) — gambling on a reversal that may never come ("上がりっぱなし" markets exist). **両建て (equal long+short)** freezes PnL = event insurance only, never a substitute for cutting losses (Gann: 禁止). **利乗せの両建て / ツナギ売り** = against a held long, repeatedly open a short at swing-highs and cover at swing-lows to harvest counter-swings while the core runs (overlay short at zigzag HIGH, cover at zigzag LOW).

- **Strategy guard:** never add to a position with negative unrealized PnL; only pyramid in the profitable direction.

### Verification / change-control hygiene (p.95-97)

Count trades **in units** (1-unit entry closed by 1 exit = 1 trade) to keep win%/RR well-defined under scaling. Keep a rule **unchanged ≥ 6 months** before revising; **flatten all positions before changing a rule**; when verifying mid-flight, **mark open positions to market** as if closed (don't let "take profits early / defer losses" inflate a period). V-trader rate `P = expected_annual_pnl / annual_target` (≥1 = rule meets target). Matches the repo's anti-overfitting / honest-evaluation methodology.

---

## Part 2 — Turtle Breakout Entries / Exits

### Donchian / Turtle breakout entries (p.39-40, p.49-53, p.64)

New-high/new-low breakouts carry an edge because trapped sellers' limit orders at the old high get exhausted, removing overhead supply ("スルスル"). Two systems:

```
Entry Rule 1 (mid trend):  buy if high > max(high[t-20 .. t-1])   sell if low < min(low[t-20 .. t-1])
Entry Rule 2 (long trend): buy if high > 55-day high              sell if low < 55-day low
```

On fill, set SL = entry ∓ 2·ATR. **Donchian-system variant** adds a long-term trend filter: only buy when `SMA(50) > SMA(300)`, only sell when `SMA(50) < SMA(300)`.

- **PL filter (Rule 1 only):** if the name's **previous trade was a winner, skip the next Rule-1 signal** (two big trends rarely occur back-to-back; cut ~30% of trades with no profit loss). Rule 2 has **no** PL filter — it is the failsafe that catches a huge trend the PL filter made you skip.
- **Weakness:** breakout signals arrive **late** (trend already underway) → for small trends you can enter the top. This motivates the author's own 大循環 / MACD entries below.

### Donchian breakout exits (p.64)

Exit channel = half the entry period, opposite extreme: a 20-day-high long exits on the **10-day low**; a 55-day-high long exits on the **20-day low** (mirror for shorts).

### Exit on trend-end, not a fixed target (p.54-57)

Never pre-set a fixed take-profit price — "頭と尻尾は市場に返す" (give the head & tail back, capture the middle). The year's P&L is decided by the few large trends; a fixed target caps exactly those. Exit on a **trend-termination signal** (MA cross / stage change), not a `tp_price`.

### Universe filters (p.78, p.93, p.125)

Trade only names that are: **liquid** (your order doesn't move price), **volatile** (ATR/price above floor — "volatility is the trend-follower's lifeline"), **shortable**, **unrestricted**, P&L-nettable, and **clean/trendy** (few gaps 窓, short wicks ヒゲ, not whippy 乱高下, persistent trends). Watch ~**5 names** so at least one has a big yearly move. Down-moves are faster/sharper than up-moves ("壊れ vs 積み上げ") — shorts profit quicker but suffer more stop-overshoot on crashes.

---

## Part 3 — 移動平均線大循環分析 (Moving-Average Great-Cycle)

The author's primary trend engine. Plot **3 SMAs: 短期=5, 中期=20, 長期=40** (daily) and read **order (並び順) → stage**, **slope (傾き) → strength**, **spacing (間隔) → continuity**. (Other common params 25/50/75/100/150/200; weekly 13/26/52.)

### The 6 ステージ (stages) by MA ordering (p.108, p.113, p.131)

Top-to-bottom ordering of (short, mid, long) has exactly 6 permutations:

| Stage | Ordering (top→bottom) | Meaning |
|---|---|---|
| **1** | 短 > 中 > 長 | stable **uptrend** (買い本仕掛け zone) |
| **2** | 中 > 短 > 長 | uptrend ending |
| **3** | 中 > 長 > 短 | entering downtrend |
| **4** | 長 > 中 > 短 | stable **downtrend** (売り本仕掛け zone) |
| **5** | 長 > 短 > 中 | downtrend ending |
| **6** | 短 > 長 > 中 | entering uptrend |

```
s=SMA(5); m=SMA(20); l=SMA(40)   # EMA(5,20,40) for 大循環MACD
rank the three values → ordering tuple → stage int 1..6
rising(x) = x[t] > x[t-1]
```

### 大循環の法則 — the stage cycle (p.109-112)

Stages transition **one step at a time** (never skip, bar a rare 3-line single-point cross). ~**70% 順行 (forward)** 1→2→3→4→5→6→1…; ~**30% 逆行 (reverse)** 1→6→5→4→3→2→1…. Knowing only 2 possible next states is the edge. If a market follows 順行 cleanly = high-EV ("獲りやすい"); if it won't obey the law, drop that market.

### Stage transitions = 3 GC + 3 DC (p.129-130)

Each step is a specific 2-MA cross among (5,20,40):
- 1→2: SMA5 **DC** SMA20 · 2→3: SMA5 **DC** SMA40 · 3→4: SMA20 **DC** SMA40 (**帯 turns 陰転**)
- 4→5: SMA5 **GC** SMA20 · 5→6: SMA5 **GC** SMA40 · 6→1: SMA20 **GC** SMA40 (**帯 turns 陽転**)

**Fakeout suppression:** a lone 2-MA cross gives many ダマシ in ranges; require **all 3 MA slopes aligned** before trusting a transition. Cost = slightly later entry (solved by 早仕掛け).

### クロスされる側の傾き — does the cross "take"? (p.114-116)

Whether two MAs actually cross is read from the **slope of the slower (longer-period) line being crossed**: ①steep-up → cross almost certainly fails/reverts; ②mild-up → likely fails; ③flat-to-down → likely succeeds; ④down → succeeds and won't revert. Gate: only treat a transition as valid if `slope(crossed_MA) ≤ ~flat`.

### 帯 (band) = the SMA20–SMA40 gap (p.119-124, p.127)

```
band_dir   = sign(SMA20 − SMA40)     # +1 上昇帯(陽) / −1 下降帯(陰)
band_width = |SMA20 − SMA40|         # trend strength; widening=continuation, narrowing→もみ合い
陽転/陰転  = cross(SMA20, SMA40)      # 帯のねじれ = 大転換 (major reversal)
```

The 帯 shows the 大局 (big-picture) trend. **A thick, stable band acts as dynamic S/R:** in a thick 上昇帯, dips into the band = **押し目買い** (buy-the-dip, price repelled up); in a thick 下降帯, rallies into it = **戻り売り**. Valid **only while** the band is ◎stable ◎slope intact ◎wide:

```
if band_dir>0 and band_width>thresh and slope(SMA40)>0:
    buy when low ≤ SMA20 (price touches top of band) and price holds   # mirror for shorts
```

### Stage-by-stage strategy & entry tiers (p.118-119, p.124-134)

| Stage | Primary action |
|---|---|
| 1 | **BUY 本仕掛け** (only after all 3 slopes up); widening gaps → add |
| 2 | exit longs (手仕舞い); 売り試し玉 timing — unless band still thick |
| 3 | stand aside (様子見); optional 早仕掛け short |
| 4 | **SELL 本仕掛け** (all 3 slopes down) |
| 5 | exit shorts; if band thick hold short; buy 試し玉 |
| 6 | stand aside; **buy 早仕掛け** (one step before Stage 1) |

**Canonical entries (p.125):** BUY = `stage==1 AND rising(s,m,l)`; SELL = `stage==4 AND falling(s,m,l)`. **Exit long** = transition 1→2 (`cross_down(SMA5,SMA20)`). Mirror for short.

**Three commitment tiers** (trade-off: earliness vs ダマシ):
- **本仕掛け** (full) — Stage 1, all 3 rising. *Weakness: late → small/zero gain on small trends.*
- **早仕掛け** (full size, 1 step early) — Stage 5/6 with all 3 slopes already turned up (or long-MA flattening from down). Higher reward on small trends, higher fakeout risk.
- **試し玉** (probe, **⅓-⅕ size**) — Stage 5/6/1 with short+mid rising and long-MA clearly easing from down; reconnaissance position, looser conditions allowed because size keeps the loss non-fatal. Pairs with 本仕掛け (試し玉 + 本仕掛け = 1 set).

**仕掛けポイント早見表 (buy quick-reference, p.134)** — `(stage, 3-slope clarity) → {full, early, probe(⅓-⅕), none}`; stronger up-alignment + later stage → bigger commitment (sell = mirror).

**もみ合い放れ (p.127-128):** a range breaks UP only via Stage 1, DOWN only via Stage 4 (stages 2/3/5/6 never produce a valid break). Watch SMA5: accelerating away from band center → real breakout; turning back → range continues.

**獲りやすい vs 獲りにくい regime filter (p.128):** easy = stages 1/4 long-lasting + wide band; hard = stages 1/4 end fast, transition stages dominate, narrow/clustered band → don't trade.

**Pitfall — 急騰急落 (p.125-126):** a single big candle can jump Stage 4→1 then immediately revert to Stage 2. On a spike-driven stage flip (`|ret| > k·ATR` in 1 bar), **wait one bar (ワンテンポ)** and confirm before entering.

---

## Part 4 — 大循環MACD (the early-entry overlay)

The author's solution to 大循環分析's only flaw (late signals): overlay MACD, which "gives buy/sell signals earlier than MAs."

### EMA, MACD definitions (p.136-141)

```
EMA(N): ema_t = (ema_{t-1}·(N−1) + price·2)/(N+1)      # α = 2/(N+1) — standard EMA; validates repo EMA
MACD1   = EMA(12) − EMA(26)
SIGNAL  = EMA(MACD1, 9)
HIST    = MACD1 − SIGNAL
```

EMA's turns are closer in time to price turns than SMA (SMA lags + flips on the *dropped* value); EMA is smoother → fewer ダマシ.

### Three signals in chronological order (p.142-146)

For a bottom→up turn, signals appear in this order (earliest → latest):
1. **HIST bottom-out** (max-negative then turns up) — earliest, but noisy = "劇場のベル," only good for a 試し玉.
2. **MACD1 × SIGNAL G-cross** — the **best / most reliable** buy signal → 本仕掛け.
3. **EMA12 × EMA26 G-cross** — latest; this is the normal (late) 大循環 entry → use as the **増し玉** trigger.

(Sell mirror: HIST peak-out → MACD1×SIGNAL D-cross → EMA12×EMA26 D-cross.)

- **増し玉 STOP conditions** (do NOT add when any appear, chronologically): HIST rise eases → HIST falls → MACD1 rise eases → MACD1 goes flat.
- **仕切り (exit):** trim **half** at HIST peak-out→down; exit the rest at **MACD1×SIGNAL D-cross**.
- **ロスカット:** prior swing low (直近の底). After a G-cross buy, if price quickly breaks the prior bottom → not a true bottom-out → exit.
- **ダマシ filters:** prefer G-crosses **below** the zero line + **large** HIST swings (above-zero / near-zero crosses & small HIST swings are unreliable). Post-entry: if MACD1 or SIGNAL stalls (not both right-shoulder-up), or **MACD1 never reaches the zero line** (so the EMA cross can't happen) → it was a ダマシ → exit immediately.

### 大循環MACD construction — 3 MACDs (p.146-150)

大循環分析 EMAs (5,20,40) on top + **three MACDs**, each = a pairwise EMA gap (signal 9), each pre-reading one stage transition:

```
MACD(上)  = EMA5  − EMA20   (signal 9)   zero-up-cross ⇒ SMA5×SMA20 GC ⇒ → Stage 5
MACD(中)  = EMA5  − EMA40   (signal 9)   zero-up-cross ⇒ SMA5×SMA40 GC ⇒ → Stage 6
MACD(下)  = EMA20 − EMA40   (signal 9)   zero-up-cross ⇒ SMA20×SMA40 GC ⇒ → Stage 1
```

MACD(上) is fast (leads price); MACD(下) is slow (confirms big move). **Require all 3 MACDs right-shoulder-up** so you aren't fooled by the fast line alone.

**Buy entries** (mirror for sells: 3 MACDs falling, MACD(下) D-cross, stages {3,2,1}):
- **本仕掛け:** `stage==6 AND crossed_up(MACD(下), signal) AND rising(all 3 MACDs)`
- **早仕掛け:** `stage==5 AND …`
- **試し玉 (⅓-⅕):** `stage==4 AND …` (band still spread above → may bounce, caution)

**Exit (手仕舞い):** watch the fastest **MACD(上)**; its roll-over pre-tells the coming stage change → exit a step early (`not rising(MACD(上))`), or trail a 逆指値 at the prior-day **EMA20**.

---

## Adaptation Notes (for cld_bittrade)

> **This section is NOT from the book — it is the reader's mapping to cld_bittrade** (BTC/JPY scalping/trend bot on bitFlyer, 1m–1h bars, automated, min-lot 0.001 BTC until benchmark passes). The author's intraday-FX habitat *is* this repo's domain, so the transfer is clean. The **binding evaluation is the CLAUDE.md ship criteria** — annualised **equity** Sharpe ≥ **buy-and-hold BTC/JPY** in **both** the IS and OOS splits, AND per-quarter non-negative fraction ≥ B&H's — pre-registered in code, benchmarked through `scripts/rebenchmark_sign.sh`, scored against `docs/evaluation_criteria.md`, decided via `/sign-debate`. Everything below is a **hypothesis to benchmark, not a validated edge.**

### What's DIFFERENT here vs a multi-name daily book (read first)

- **Single instrument → NO cross-sectional market-neutral / beta-strip, and NO 6-slot fill-order null / cross-name correlation caps.** The crypto analog of "is this just market beta?" is the **displaced-capital test**: does the strategy's equity Sharpe beat **B&H BTC/JPY** in **both** the IS and OOS splits? A long-only trend-rider that merely rides a BTC bull leg is the crypto "beta" trap — it fails the OOS leg when BTC falls (the repo deliberately matches each split to its *own* B&H so a falling-BTC OOS is the right bar, not an absolute floor).
- **24/7 continuous** → the book's gap / weekend / holiday stop-overshoot caveat (p.61) mostly dissolves (no exchange gaps), but funding resets and liquidation cascades create their own shock-bars; keep ATR stops wide enough to survive them.
- **High volatility + intraday trend-persistence** → ATR-unit sizing is essential, and momentum-continuation may hold up *better* than it did on JP daily (where it inverted). **Don't assume either way — benchmark it.**
- **Long AND short are both first-class** (perps, no borrowability problem) → the book's symmetric Stage-1 buy / Stage-4 sell, both-sided Donchian, and 戻り売り shorts are all directly usable.
- **Re-tune bar-counts per timeframe.** 5/20/40 is the book's daily default; keep the *ratios*, sweep the absolute lengths per 1m / 5m / 15m / 1h. Same for ATR(N), Donchian(N), MACD(12/26/9).

### Mapping book concepts to existing cld_bittrade signs / strategies

| Book concept | Closest cld_bittrade sign / strategy | Notes |
|---|---|---|
| Single-MA golden/dead cross; 2-EMA G/D-cross (p.37-39, p.138) | `ema_cross` | Direct. |
| 大循環 3-MA stage / perfect order; MACD-lead entry (Part 3-4) | `ema_atr_breakout` (EMA9/21 + ATR filter) is nearest; full 5/20/40 stage is **net-new** | The stage classifier + slope + 帯 is a richer trend gate than a bare 2-EMA cross. |
| Turtle/Donchian N-bar channel breakout + ATR filter (Part 2) | `ema_atr_breakout`, `density_breakout*` | Channel high/low breakout is **net-new** as a primitive; pairs with the ATR filter `ema_atr_breakout` already uses. |
| 帯 (band) S/R 押し目買い / 戻り売り; next-pivot exit (Part 3) | `zigzag_bounce`, `density_band` | Pullback-into-rising-band buy ≈ a zigzag bounce inside an intact trend. |
| VAP nodes / range S/R; valid-breakout vs low-volume fakeout (Part 0-2) | `density_*` family (`density_breakout`, `_vol`, `_acc`, `_clearair`, `density_volwall_breakout`) | The `density_*` signs ARE this repo's volume/price-node primitive — the book's HVN S/R + volume-confirmed breakout map straight onto them. |
| ATR 2N stop, half-rise trail, no fixed TP (Part 1) | `src/exit/rules.py`, `src/exit/zs_tp_sl.py` (ATR trail / time stop / fixed TP-SL) | The book's exits are variants to A/B via `strategy.get_exit_rules()`. |

### Where the book CONFIRMS existing cld_bittrade doctrine (adopt as priors)

- **ATR-volatility sizing** — `ema_atr_breakout` already sets TP/SL in ATR multiples (TP ±1.5 ATR, SL ±0.8 ATR); the book's *1 Unit = k·ATR = fixed-% risk* formalizes position **size** the same way. (NB the book's stop is much WIDER — 2-3 ATR — than ema_atr's 0.8 ATR scalp stop: trend-ride vs scalp horizon.)
- **Displaced-capital benchmark** — the book's "buy cheap/dear vs the FUTURE not the past" + "trade only where there's an edge" is the repo's "benchmark = B&H BTC/JPY, not cash."
- **OOS / overfit discipline** — the book's ≥6-month rule-freeze + mark-to-market verification = the repo's IS/OOS split + the OVERFIT flag (OOS Sharpe < 0 or OOS DD > 2× IS DD).
- **One strategy live + correlation check before adding a second** = the book's unit caps / "correlated names are one bet."
- **Never average down (ナンピン); risk-of-ruin ≤ 1%; per-trade risk 1-2%** — clean money-management targets for `src/portfolio/` (and the min-lot 0.001 BTC rule is the current hard sizing cap).
- **Two-bar fill** (signal at close of T, fill at open of T+1) — identical to the repo's fill model.

### Net-new strategy candidates (register in `src/strategy/registry.py`, run the benchmark pipeline)

1. **`ma_stage`** — long when Stage 1 (EMA5>20>40, all rising), short Stage 4; commitment tiers 試し玉 / 早仕掛け / 本仕掛け by stage + slope; exit on stage flip. Benchmark vs B&H in both splits.
2. **`macd_stage`** (大循環MACD) — three pairwise-EMA MACDs (5-20, 5-40, 20-40) each pre-reading a stage transition; entry = MACD1×Signal G-cross below zero with a large histogram swing, add (増し玉) on the EMA cross. The "enter 1-2 stages early" lead is the crypto-intraday-friendly half.
3. **`brk_donchian`** — N-bar high/low channel breakout + ATR stop, **both-sided**; the book's Rule-1 (20) / Rule-2 (55) as bar-counts per timeframe.
4. **`ma_band`** — 帯 = EMA20−EMA40 gap; 押し目買い into a thick rising band; band width/direction as a trend-strength gate on the other signs.
5. **Kojiro exit** — 2-3 ATR initial stop + **half-rise trail** (raise stop by ½ each new-high advance), no fixed TP; A/B via `get_exit_rules()` against the current fixed-TP / ATR-trail exits, judged on **equity Sharpe vs B&H** (see prior below — this gate differs from the one that rejected it on JP daily).

### PRIORS from the sister repo (cld_trade_advisor) — RE-TEST, do not assume

The same book was mined on cld_trade_advisor (**JP daily stocks, multi-name 6-slot manual book**). Those results are **priors only** — the regime (JP daily, mean-reverting, cross-sectional 6-slot fill-order null) is *fundamentally different* from crypto intraday, so each is a hypothesis to re-test here, NOT a foregone conclusion:

- **`ma_stage`** → REJECT on JP daily: the 6-stage axis was pure N225 beta (zero forward-return structure after market-neutralizing). *Crypto note:* there is no cross-sectional MN strip here — the test is vs B&H BTC/JPY — and crypto intraday trends persist, so a stage gate may behave differently. **Re-test.**
- **`brk_donchian`** → REJECT on JP daily: the bare new-high break under-performed (buying into exhausted resistance) and breakout strength was *inverted* (bigger = worse). *Crypto note:* crypto breakouts are the canonical momentum regime; the JP-daily inversion may NOT replicate. **Re-test, both-sided.**
- **Kojiro ATR-stop + half-rise trail exit** → REJECT on JP daily: the low-DR / high-RR Turtle profile (DR ~38%) hurt the **6-slot diversification book's** Sharpe (it could not diversify the per-trade variance). *Crypto note:* on a **single-instrument** bot judged on **equity Sharpe vs B&H BTC/JPY** — a different gate — that low-win / high-RR trend-ride is exactly the displaced-capital payoff the repo's consistency gate was *relaxed to allow*; it could pass. **Re-test.**
- **General momentum caveat:** on JP daily, "high volume / big breakout = continuation" repeatedly **INVERTED** (the volume spike marked the move *ending* — `lowprice_volspike`, `vol_breakout_confirm`). Crypto intraday momentum is more persistent, so the inversion may not carry — but **benchmark every volume/breakout gate; assume neither direction.**

For each candidate: implement → register → `scripts/rebenchmark_sign.sh <strategy>` → judge against the **pre-registered** ship gate (equity Sharpe ≥ B&H BTC/JPY in both splits + per-quarter non-neg ≥ B&H) in `docs/evaluation_criteria.md`, via `/sign-debate`.
