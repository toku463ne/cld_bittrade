# Volume Price Analysis (VPA) — Anna Coulling (A Complete Guide to Volume Price Analysis)

Source: 出来高・価格分析の完全ガイド (Anna Coulling, *A Complete Guide to Volume Price Analysis*). VPA is a **Wyckoff-based** method: read every bar's price action, then **confirm or reject it with volume**. It is explicitly **timeframe- and instrument-agnostic** — the same rules work on tick, 5-min, daily, weekly and monthly bars across stocks, ETFs, FX, futures and commodities. Because this repo trades **Japanese stocks on DAILY bars with reliable exchange volume**, MOST of this book transfers directly: daily OHLCV is exactly the data VPA assumes, and the only adaptation is mechanical thresholds in place of the author's "subjective art." The final section (`Daily-Bar Adaptation Notes`) is the reader's own mapping to this repo's signs and is NOT from the book.

---

## Foundations

### Wyckoff's Three Laws

1. **Supply & Demand** (p.2) — Price is driven by the economic law of supply vs demand: demand > supply → price rises; supply > demand → price falls until the excess is absorbed. This is the root justification for reading volume against price: rising price + rising volume = genuine demand; falling price + rising volume = genuine supply; absorption of supply at a low = bottoming.

2. **Cause & Effect** (p.3) — To get a result there must be a cause, and the **effect is proportional to the cause**. Small volume → small move; large accumulated cause (long/heavy accumulation or distribution) → large subsequent trend. Backtest hook: scale the expected trend magnitude/duration to the size and duration of the range that built it (a multi-week daily range → a multi-week trend; a 5-min range → roughly a 1-hour trend) (p.22, p.65, p.100).

3. **Effort vs Result** (p.3) — THE central VPA divergence/anomaly detector (Newton's 3rd-law analogy). Price action (result) should reflect volume (effort). **Agreement = the move is genuine → trust/continue. Disagreement = an anomaly → an alarm bell → prepare for reversal.** Apply a "forensic, bar-by-bar" approach: if the law holds, proceed; if effort ≠ result, you MUST find the reason — it flags a hidden opposing force. Codeable as a divergence between volume rank and price range / close progress on a bar.

### Smart Money vs the Herd — the market cycle (p.2, p.24-25, p.45 Fig 5.9)

"Insiders" (specialists / market makers / large institutions — the book's umbrella term for **smart money**) hold inventory, buy at wholesale (lows) and sell at retail (highs). The herd (一般大衆) does the opposite — buys tops out of FOMO, sells bottoms out of fear. The full cycle, repeating forever on every timeframe:

**Accumulation (bottom) → Markup (public trend-following) → Distribution (top) → Markdown → back to Accumulation.**

- **Accumulation** (買い集め): insiders fill the warehouse at wholesale inside a sideways range, using shakeouts/bad news to scare out weak holders. Ends in an upside breakout.
- **Distribution** (売り抜け): insiders empty the warehouse at retail in a narrow range near the highs, drawing FOMO buyers on each dip. Ends in a downside breakout.
- Markups are slow ("up the stairs"); markdowns are fast ("down the elevator / snakes") — fear acts faster than greed (p.40-41).
- Manipulation in this book means manipulating **emotion (fear & greed) via news**, not random price-pushing (p.46). Volume is "the one thing insiders cannot hide" — the basis of VPA (caveat: dark pools / split orders conceal individual block size, but not aggregate bar volume) (p.42-44, p.98).

### The Cardinal Rule

**Volume is always judged RELATIVE to a recent rolling average — never on absolute thresholds** (p.11-12, p.21-22 Principle 3, p.97). Compare each bar's volume to a moving baseline of recent volume → "below average / average / above average / very high / extreme." Only consistency within one data feed matters; never cross-compare feeds or symbols. An "extreme" reading that merely matches a trend's own inflated baseline is NOT a true anomaly (p.97).

**Volume must CONFIRM price, or the bar is an anomaly/warning** (p.23 Principle 6 — confirmation 裏付け vs anomaly 例外). Confirmed → the move is genuine and continues. Anomaly (volume ≠ price) → possible reversal. Two corollaries: **volume without price movement is meaningless** (only the combination signals), and **a single reversal signal is a WARNING, not a trigger** — markets are supertankers; reversal/absorption takes ~5-6 bars (or a 2-4 bar climax window), so wait for multi-bar confirmation before acting (p.20-21 Principle 2, p.48).

---

## Reading a Single Bar (candle anatomy)

Every candle has 7 elements: open, high, low, close, upper wick (上ヒゲ), lower wick (下ヒゲ), real body (実体). With volume, the **two wicks and the body** carry the most information (p.14-15, p.50).

- **Body = strength of sentiment** for that bar. Wide body = strong sentiment (bullish if close > open, bearish if close < open); narrow body = weak/indecisive. Codeable as `body_frac = |close − open| / range` or body vs ATR (p.15, p.57-58).
- **Wicks = rejection / intrabar sentiment change.** A long wick marks where price was pushed and rejected. Long **lower** wick = buyers rejected lower prices (bullish rejection); long **upper** wick = sellers rejected higher prices (bearish rejection). **No wick = strong one-directional sentiment** continuing in the body's direction (p.15, p.50).
- **Close position within the bar is the key feature.** Close in the **upper third** = bulls won the bar; **lower third** = bears won. Used throughout (stopping volume closes in upper half; topping volume in lower half).

### Codeable per-bar features

| Feature | Definition |
|---|---|
| `body_frac` | `|close − open| / (high − low)` |
| `upper_wick_frac` | `(high − max(open,close)) / range` |
| `lower_wick_frac` | `(min(open,close) − low) / range` |
| `close_pos` | `(close − low) / (high − low)` — 1.0 = close at high, 0.0 = close at low |
| `range_vs_avg` | `range / SMA(range, N)` — wide-range vs narrow-range bar |
| `vol_vs_avg` | `volume / SMA(volume, N)` — the relative-volume axis (the operative one) |

### Named single bars

- **Dragonfly / Tombo doji 「トンボ」** (p.16-18) — body ≈ 0, long **lower** wick, close ≈ open ≈ high. Sellers dominate first, selling exhausts (売りが枯渇), buyers take control and lift the close back up → **bullish** reversal candle (potential bottom). Detect: `body_frac ≈ 0`, large `lower_wick_frac`, `close_pos` high.
- **Gravestone / Touba doji 「トウバ」** (p.16-18) — body ≈ 0, long **upper** wick, close ≈ open ≈ low. Buyers dominate first, buying exhausts (買いが枯渇), sellers take control → **bearish** reversal candle (potential top). Mirror of Tombo.
- **Long-legged doji 「足長同時線」** (p.55-57) — open ≈ close with long **both** wicks (wide two-way swing returning to open) = indecision / turning point. After an uptrend → first sign of reversal down; after a downtrend → reversal up. **Key exception: the LOW-VOLUME case is a stop-hunt / fake** — a wide two-way swing needs effort; on low volume it is insider price manipulation, NOT a reversal → stand aside. (Clusters around major news; only validates on at-least-average, preferably high/extreme volume.)
- **Wide-range bar 「長大線」** (p.57-58) — one clear strong-sentiment message; should carry very high volume. Wide-range on **below-average volume = alarm bell** (effort-less move, not genuine).
- **Narrow-range bar 「短小線」** (p.58) — weak sentiment, ubiquitous and dull by itself; interesting ONLY as the anomaly (narrow body + above-average volume → see effort-vs-result anomaly below).

Reading price action alone is only HALF the story — it gives direction but not strength or genuineness. Volume completes it; never act on a candle without volume (p.19, p.27-28).

---

## The VPA Sign Catalogue

The heart of the method. Each sign = a volume+price condition, read through the smart-money story. **Position within the trend changes the meaning entirely** — the same shape inverts at a top vs a bottom (Principle 4, p.50), so every detector must be gated on where in the trend the bar sits.

### Effort-vs-Result CONFIRMATION (continuation)

- **Pattern:** Wide body + above-average volume (big result, big effort), OR narrow body + below-average volume (small result, small effort). Short wicks. (p.23-24 Fig 4.1/4.2, p.26 Fig 4.5)
- **Read:** Confirmed / genuine → continuation. In an uptrend a wide up-body on rising volume = insiders participating → "follow the insiders, hold/enter long" until an anomaly appears. Multi-bar: 3+ up bars with monotonically rising bodies AND rising volume = confirmed trend (two levels of confirmation: per-bar and trend-cumulative). Symmetric on the downside: clean no-wick down bars + rising volume = confirmed selling.
- **Entry:** Low-risk continuation in the trend direction.
- **Pages:** p.23-28.
- **Hints:** `up bar & body_frac > baseline & vol_vs_avg > 1` → continuation flag. Low volume on a small bar is NORMAL, not a warning — anomaly arises only on a MISMATCH.

### Effort-vs-Result ANOMALY — narrow body + HIGH volume (stopping / distribution)

- **Pattern:** Price moved only a little (narrow body) but volume is high/extreme (much effort, little result). (p.24-25 Fig 4.4, p.97, p.100-102)
- **Read:** **Weakening / bearish at a top** (or, inverted, absorption/bullish at a bottom). High volume + small gain = new buyers being absorbed by selling insiders (distribution); buying effort is neutralized, price can't advance ("car flooring the engine on ice → tires spin → stalls"). At a bottom the inverse = selling absorbed by buyers.
- **Entry/Exit:** Take profit early if long, or prepare for the reversal. Confirmed by a following shooting star (top) / hammer (bottom).
- **Pages:** p.24-25, p.97, p.100-102.
- **Hints:** `body_frac small & vol_vs_avg >> 1`, gated on trend position. This is the core of `div_vol` in this repo.

### Effort-vs-Result ANOMALY — wide body + LOW volume (trap / no participation)

- **Pattern:** Big real body but volume below average (big result, no effort). (p.24 Fig 4.3, p.57-58, p.95-96)
- **Read:** **Bearish warning / TRAP.** A large move should carry large volume; it doesn't → insiders not participating. Often a fake up-move (especially at the open) to lure weak longs in before reversing to hit their stops; or market makers "probing" sentiment on thin volume. The "ダマシ" / fakeout.
- **Entry/Exit:** Don't chase. If holding, investigate/exit; if flat, wait for the next bar to see when insiders actually enter.
- **Pages:** p.24, p.57-58, p.95-96.
- **Hints:** `|return| large & vol_vs_avg < 1` → anomaly/no-confirm flag. By "day 3" a true move shows volume far above the prior day's.

### No-Demand bar

- **Pattern:** A narrow-body **up** bar on LOW / declining volume, appearing during or after a rally. (p.58, p.84, p.89-91)
- **Read:** **Bearish / weak** — "it takes effort (volume) to go up"; the rally lacks smart-money participation. The up-leg is exhausting. If the next bar is a shooting star, the weakness is proven.
- **Entry:** Not a buy. A rising market on falling volume = warning the move is failing.
- **Exit filter:** In an uptrend, a **pullback** on low volume is fine (minor reaction → hold); but a **rally** on low volume signals exhaustion → prepare to exit.
- **Pages:** p.58, p.84, p.89-91.
- **Hints:** `up bar & body_frac small & vol_vs_avg < ~1` in an up-context.

### No-Supply bar

- **Pattern:** A narrow-body **down** bar on LOW volume (mirror of no-demand). (p.58, p.37-38)
- **Read:** **Bullish** — buyers absorbing; small body on a down-probe with low volume = no selling pressure left = supply exhausted. First sign of a turn from bearish to bullish.
- **Entry:** Confirmation comes if a hammer or long-legged doji follows. (This is the same mechanism as the no-supply **test** below.)
- **Pages:** p.58, p.37-38.

### Test bar (no-supply / no-demand test)

- **Pattern:** After absorption, smart money probes back into the prior heavily-traded zone. **LOW-volume test = PASS; HIGH-volume test = FAIL.** The classic successful supply-test bar = **small body (color irrelevant) + long lower wick, close back up near open, on below-average volume** (p.37-40 Fig 5.3-5.6, p.45, p.87-90, p.93).
- **Read:** A low-volume test confirms no supply (after accumulation, bullish) or no demand (after distribution, bearish) remains → the campaign can proceed. A high-volume test means sellers/buyers returned in force → test fails; the insider must shake out again and re-test. Tests often come in series, each on progressively lower volume.
- **Entry:** A successful low-volume test followed by an **above-average-volume wide up bar** = the go signal to enter long (the canonical sequence: stopping volume → hammer → low-volume test → high-volume up bar → breakout, ideally gapping up).
- **Stop:** Below the test/hammer low.
- **Pages:** p.37-40, p.45, p.87-90, p.93.
- **Hints:** `down-probe into prior range & vol_vs_avg < 1 & lower_wick_frac large & close_pos > 0.5` → pass. One of the most powerful and timeframe-robust VPA signals; **net-new** to this repo.

### Stopping Volume + Hammer (at a bottom)

- **Pattern (multi-bar):** During a sharp fall, a series of down bars where, bar by bar: long **lower** wicks; close in the **upper half** (`close_pos > 0.5`); **bodies progressively shrink**; volume **above average and gradually increasing**; the sequence terminates in a **hammer** (p.53-55, p.59-61, p.86-90). A standalone bar version = small body + above-average/very-high volume after a down-move (selling absorbed by institutional buying).
- **Read:** **Strong bullish** — smart money braking the decline ("supertanker can't stop instantly"); precursor to a selling climax / accumulation. Effort (huge volume) with little result (small body, close off lows) = down-move running out.
- **Entry:** Do NOT buy the stopping-volume or hammer bar alone (a lone hammer cannot stop a strong down-move). Wait for the terminating hammer → low-volume **test** → above-average-volume wide up bar. Aggressive traders act on the hammer; cautious traders wait for the strength bar.
- **Stop:** Just below the hammer's lower wick (explicit, SLV example p.89).
- **Pages:** p.53-55, p.59-61, p.86-93, p.95.
- **Hints:** Window detector over N bars: lower_wick long, close_pos > 0.5, body shrinking, volume rising and > avg, after a steep prior decline. **Net-new** sequence to this repo.

### Topping-Out Volume + Shooting Star / Hanging Man (at a top)

- **Pattern (multi-bar):** Mirror of stopping volume at the top. Series of up bars: long **upper** wicks; close in the **lower half** (`close_pos < 0.5`); bodies progressively shrink; volume above average and rising; arc/dome shape; terminating in a **shooting star** (流れ星: long upper wick, small body, close near open) (p.50-53, p.60-61, p.90-94). Related single bars at a top: **Hanging Man** (首吊り線 — hammer shape but at a top → bearish, needs above-average volume; confirm with a following shooting star within 2-3 bars, p.58-59, p.101) and **Gravestone doji**.
- **Read:** **Bearish / topping** — insiders supplying into greedy buyers (distribution); up-attempts get capped, momentum dies. Develops into a buying climax.
- **Entry/Exit:** Exit longs / prepare shorts. Confirmation = a 2nd shooting star whose volume exceeds the 1st, or a cluster of 2-3 stars failing at the same level (= building distribution / buying climax).
- **Stop (short):** Above the first shooting star's upper wick.
- **Pages:** p.50-53, p.58-61, p.90-94, p.101.
- **Hints:** Window detector: upper_wick long, close_pos < 0.5, body shrinking, volume rising and > avg, after a sustained rise. Cluster rule: repeated same candle at the same price level multiplies the signal.

### Selling Climax (at a BOTTOM → BULLISH)

> **Definition (STANDARD Wyckoff/Coulling — use this).** A *selling climax* occurs at the **BOTTOM**, at the end of a down-move: insiders drive price down on bad news to induce **panic selling** by the public (the climactic *selling*), then **buy** the capitulation in size (filling the warehouse = accumulation). Named for the crowd's climactic selling. (One reader's note swapped the buying/selling climax labels — corrected here.)

- **Pattern:** At the bottom of a down-move, **high-to-extreme volume on down bars that close back UP** (small body, long **lower** wick), price held in a narrow range, then a strong upside breakout. Often spans **2-4 bars** (orders split — a big buy can't complete in one day). (p.44, p.46-48 Fig 5.8/5.11, p.93-94)
- **Read:** **Bullish reversal warning** — extreme volume = the market is preparing to turn up. Stopping/absorption volume in concentrated form.
- **Entry:** Wait for the climax to COMPLETE (patience — multi-bar event), then buy / cover shorts. Confirm with the post-climax range hold and breakout.
- **Pages:** p.44-48, p.93-94.
- **Hints:** Extreme `vol_vs_avg` spike (the example cited >6M vs ~500k avg ≈ >10×) + lower-wick reversal bars at a bottom + range hold + breakout. **Climax detectors should scan a 2-4 bar window, not one candle.**

### Buying Climax (at a TOP → BEARISH)

> **Definition (STANDARD — use this).** A *buying climax* occurs at the **TOP**, at the end of an up-move: the euphoric public keeps **buying** (the climactic *buying*) while insiders **distribute** their remaining inventory into that demand. Named for the crowd's climactic buying. (Reader note swapped the labels — corrected.)

- **Pattern:** Near the end of an extended uptrend, price **closes near its open on high/extreme volume, repeated 2-3 times**; the defining candle = **small body + long UPPER wick** (insider lifts price early to draw FOMO buyers → volume swells → sells into it → close falls back to open). (p.42-44 Fig 5.7/5.10, p.94)
- **Read:** **Bearish reversal warning** — overbought top; price then drops sharply "down the slide" back toward accumulation.
- **Entry/Exit:** Exit longs / prepare shorts. Wait for the climax to complete.
- **Pages:** p.42-44, p.47, p.94.
- **Hints:** Cluster of upper-wick small-body bars at a trend top with `vol_vs_avg >> 1`, 2-3× repetition. Dark-pool caveat: big blocks are hidden in individual orders but show in aggregate bar volume.

> **General climax law (p.48):** Extreme volume signals an imminent reversal. Heavy volume at a **top** (buying climax) → downward reversal; heavy volume at a **bottom** (selling climax) → upward reversal. Combined with wick direction (upper wick at top / lower wick at bottom) + close-near-open, this is the most reliable reversal tell.

### Accumulation Range & Breakout

- **Pattern:** A sideways trading range **after a sharp decline**, with above-average volume clustering on down-bars (insider buying / repeated shakeouts), resolving in an **upside breakout**. Takes weeks-to-months on stocks (p.33-34 Fig 5.1, p.98).
- **Read:** **Bullish** — warehouse being filled at wholesale. The breakout above the range is the actionable event. Post-base, a healthy markup rises on **steady average volume** without extreme bars.
- **Entry:** Buy the volume-confirmed breakout above the range.
- **Pages:** p.33-34, p.98.

### Distribution Range & Breakdown

- **Pattern:** A narrow trading range near the **highs** of an extended uptrend, on high volume (insiders selling into FOMO dips), resolving in a **downside breakout** (p.35-36 Fig 5.2, p.93-95).
- **Read:** **Bearish** — warehouse emptied at retail. Exit longs / look for shorts on the down-break.
- **Entry/Exit:** Short / exit on the volume-confirmed breakdown below the range floor.
- **Pages:** p.35-36, p.93-95.

### Low-Volume Fakeout vs High-Volume Valid Breakout

- **Pattern:** Leaving a congestion zone requires effort → a genuine breakout shows a **decisive close beyond the level + above-average and rising volume** (ideally a wide-spread bar, strongest if it gaps). A breakout on **low/below-average volume = a classic insider trap / ダマシ** (p.55 Principle 5, p.68-69, p.84-85, p.100).
- **Read:** Volume-confirmed break = real → trade with it. Low-volume break = stand aside (likely fake; reverses to trap entrants).
- **Entry:** (1) close clearly beyond the level (a visible gap from the level, not a few-point pierce); (2) volume above average and increasing → then enter.
- **Stop:** Just inside/below the range — below the breakout level (former resistance now support) / below the last pivot low.
- **Pages:** p.55, p.68-69, p.84-85, p.100. Maps to this repo's `brk_sma` / `brk_bol` with a volume gate.

### Low-Volume Pullback = Healthy Continuation

- **Pattern:** After a volume-confirmed breakout/trend leg, price pulls back **on declining/below-average volume** (p.68, p.75-77, p.85, p.90).
- **Read:** **Bullish continuation** — no supply coming in; the trend is intact → hold. A pullback on RISING volume is the warning (potential reversal). Symmetric: a counter-move against any held position is "just a pullback" IF volume falls on the counter-move AND no stopping/topping volume precedes it.
- **Entry/Exit:** Hold (or add) while pullbacks come on falling volume; exit when the trend leg's own volume shrinks (息切れ) AND a contrary high-volume absorption bar appears.
- **Pages:** p.68, p.75-77, p.85, p.90-95.

### Volume-at-Price (VAP) high-volume nodes as S/R

- **Pattern:** VAP = a histogram of cumulative volume **per price level** (volume profile / 価格帯別出来高 — the conventional volume bar rotated 90° and decomposed by price). Up- vs down-volume can be color-split per band (p.17, p.80-85 Ch.9).
- **Read:** **Heavy-volume price nodes (POC / HVN) = the strongest future support/resistance** (much business done there → takes substantial volume to break back through). Thin nodes (LVN) = price slices through easily. Volume concentrated in the lower price region → buying dominates; upper region → selling dominates.
- **Entry/Stop/target:** Use HVN bands as natural S/R for entries, stops and targets; do NOT anchor a stop to a low-volume (weak) range. Grade each range by (a) accumulated volume and (b) dwell time (bars) — longer + above-average = the node that matters; benchmark every range against the chart's highest-volume range.
- **Pages:** p.17, p.80-85. VAP *locates* zones; run conventional VPA *at* those zones to confirm. **Net-new** to this repo. **→ Stage-0 REJECT (2026-06-27):** on daily JP, HVN support is INVERTED (pullbacks into a high-volume node drift *worse* than into a thin node; node edge negative every horizon) and HVN resistance is nil — a heavy node behaves as absorption/overhang, not a floor. See `src/analysis/vap_node_sr_stage0.py` and memory `project_vap_node_sr_stage0_reject.md`.

> **VPA vs VAP (p.17):** VPA reads the *linear* volume↔price relationship of a fully-formed bar (open→close). VAP reads *where within the price range* volume concentrated. Complementary; use both.

---

## Support, Resistance & Trading Ranges

### Isolated 3-bar pivots (codeable)

The tool that anchors the START of a range (a range is only confirmable in hindsight) (p.66, p.76, p.99-101):

- **Pivot High:** `high[T] > high[T-1] AND high[T] > high[T+1] AND low[T] > low[T-1] AND low[T] > low[T+1]` (middle bar strictly above both neighbors). Provisional **ceiling**.
- **Pivot Low:** strict inverse — middle bar's high AND low both below both neighbors'. Provisional **floor**.
- Confirmed only at T+1 (two-bar lag — consistent with this repo's fill model). Treat levels as **elastic zones ("rubber bands, not iron bars")**, not exact lines; pivots don't always form cleanly (sometimes a pivot high with no matching pivot low). It is **volume**, not the pivot, that confirms a range began (volume drops below average inside the range).

### Range mechanics

- Markets are sideways **~70%** of the time, trending only ~30% (p.62-63). Three causes of ranges: (1) pre-major-news compression; (2) a buying/selling climax (warehouse full/empty); (3) price re-entering an old congestion zone where trapped traders exit.
- **Cause & Effect:** the longer/deeper/wider the range, the higher the odds of a strong breakout and the longer the subsequent trend (p.65, p.79, p.100). Ranges are the **incubator of trends** — new trends are born there, so they offer the earliest edge.
- Range edges = a map of crowd fear & greed: trapped weak longs sell into the prior top (building resistance); strong patient buyers accumulate at the floor (building support) (p.63-65).

### Support ⇄ Resistance flip (the "House" model)

Broken **resistance becomes support**; broken **support becomes resistance** (p.70-71). Repeated failure to break a ceiling = very strong resistance → reversal; repeated failure to hold a floor = extreme weakness. Old congestion zones are "DNA" left in the chart — price returns and they reactivate (self-fulfilling, everyone watches the same levels). Weight S/R by the timeframe it formed on (longer = stronger, p.72). Backtest feature: distance to nearest historical pivot/range zone, weighted by that zone's volume and dwell time.

### Valid-breakout rule

Decisive **close beyond the level** + **above-average and rising volume** (wide-spread bar ideal, gap = strongest); stop just below the last pivot / former level (now flipped). Low-volume break = fakeout, stand aside (p.68-69, p.84-85, p.100). Don't wait for the textbook 3-touch trend line — by the 3rd stepped-up high/low the trend is already at climax/distribution; use S/R + volume-confirmed range breakout to enter as the trend is **born**, then draw **dynamic trend lines** by connecting successive pivot highs (upper line) and pivot lows (lower line) live, holding while pivots step up with volume backing (p.73-78). Rising price on **below-average volume = no real trend** (effort absent) → expect re-entry into a range.

### Named consolidation patterns

| Pattern | Pages | Structure | Read |
|---|---|---|---|
| **Descending triangle** | p.103 | Lower rally highs, flat floor | **Bearish** — high-prob down-break of the flat floor |
| **Ascending triangle** | p.104 | Flat ceiling, rising lows | **Bullish** — up-break of the flat ceiling; ceiling then becomes support (stop there) |
| **Pennant** | p.104 | Highs descend AND lows ascend (coiling spring) | **Neutral direction** — wait for the break to declare; explosive release; good for direction-agnostic plays |
| **Triple top** | p.105 | Same resistance tested & rejected 3× | **Bearish** reversal; OR if it breaks up, ceiling → strong support (trade the break long) |
| **Triple bottom** | p.105 | Same support tested & held 3× | **Bullish** reversal; OR if it breaks down, support → strong resistance (trade the break short) |

All share one thing: a consolidation that is simultaneously forming a ceiling/floor, from which a breakout always follows (reversal or continuation) — confirm direction with VPA + VAP (p.106). Bigger/longer pattern → bigger move (Cause & Effect). All appear on every instrument and timeframe.

---

## Multi-Timeframe Method (Putting It All Together)

- **Three nested timeframes** with a fixed ratio (p.31-32, p.40-41, p.102-103). Author's sets: 5/15/30-min (primary 15) or 30/60/240 (primary 60). The **longer** chart sets the dominant trend = your bias ("telescope" / where you are in the macro trend); the **shorter** chart gives early warning + fine entry; the **middle** is where you take the trade.
- **Micro → Macro → Global** (the 3-step VPA process, p.31-32): Step 1 = read one bar vs its predecessor (confirm/anomaly); Step 2 = read it against the prior 2-3 bars (small trend vs small reversal — enough for a low-risk entry); Step 3 = read the whole chart (top/bottom/middle of the long trend, with S/R, trend lines, patterns).
- **Ripple / propagation rule** (p.32, p.102-103): a real sentiment change starts on the **short** timeframe and ripples outward (stone in a pond) to longer timeframes. Confirm a signal across all three before acting; when the change reaches the long TF the resulting trend is **stronger and longer-lasting**. A weakness that is ambiguous on the 15-min is an obvious shooting star on the 30-min — let the higher TF lead exits.
- **The cycle is fractal / Matryoshka** (p.40-41): the full warehouse-fill→empty cycle runs on every timeframe simultaneously (tick → daily → monthly), each nested in the next.
- **Trade WITH the dominant longer-TF trend = lower risk** ("swim with the tide"). Counter-trend trades are higher risk and must be **held only briefly / sized smaller / taken-profit faster** (p.75, p.89-90, p.95, p.102-103). Buying a pullback within an up-dominant longer trend is fine (it's a dip in the direction of the tide). Money-management: the **1% rule** per trade (p.28).

> **Other chart types (Ch.12, p.107-110), for reference:** EquiVolume (box width = volume, height = range — drops the time axis, losing Cause & Effect); Candle Volume (candles with width ∝ volume, keeps wicks); Delta Volume (bid-vol − ask-vol per bar, for centralized order-flow markets, not FX) and Cumulative Delta. All are alternative lenses on the same effort-vs-result relationship; the author treats Delta as "next generation," untested at time of writing.

---

## Daily-Bar Adaptation Notes (for this repo)

> **This section is the reader's mapping to this repo — NOT from the book.** VPA assumes exactly the data we have: daily OHLCV with reliable exchange volume. The author calls VPA "an art, not a science" that can't be automated (p.20); our job is to approximate each sign with mechanical, relative-volume thresholds and then put it through the repo's standard evaluation gauntlet. Everything below is a **hypothesis to Stage-0 test, not a validated edge.**

### Mapping VPA signs to existing repo signs

| VPA concept | Closest existing repo sign | Notes |
|---|---|---|
| Effort-vs-result anomaly (narrow body + high vol / wide body + low vol) | `div_vol`, `div_bar` | This IS the repo's volume/bar-divergence family. VPA gives it the smart-money interpretation + the close-position gate. |
| Gap-based anomaly / gap breakout on volume | `div_gap` | VPA: gap-up on high vol = real; gap-up on low vol into resistance = trap (p.84, p.88, p.95-96). |
| Climax / stopping-volume reversals | `rev_nday`, `rev_nlo`, `rev_peak` | Selling/buying climaxes and stopping volume are N-day reversal setups; VPA adds the **close-position + wick + volume** confirmation these signs may not currently require. |
| Volume-confirmed breakout vs low-volume fakeout | `brk_sma`, `brk_bol` | Add a **volume gate**: require breakout-bar `vol_vs_avg > 1` and rising; flag low-volume breaks as fakeout candidates. |
| Stock-flat-vs-index / lead/lag absorption | `str_hold`, `str_lag`, `str_lead` | Conceptually adjacent to VPA absorption (a stock holding/absorbing while the index drops = hidden buying); VPA is single-instrument, these are index-relative. |

### Net-new vs the repo

Not cleanly covered by existing signs and therefore candidate new builds: **no-demand bar**, **no-supply bar**, **test bar (low-volume test)**, **stopping-volume + hammer sequence**, **topping-out + shooting-star sequence**, and **VAP high-volume-node S/R** (volume-profile is not currently a repo primitive).

### CRITICAL — VPA AGREES with the `lowprice_volspike` REJECT

The repo already REJECTED a naive **"cheap stock + abnormal volume spike + up day = buy"** trigger (memory `project_lowprice_volspike_stage0_reject.md`): it **inverted** — bigger spike/up-move was monotonically *worse*, because the volume bar marked the move **ENDING** (pump-and-fade). **VPA predicts exactly this.** A volume spike on an up day with NO confirming reversal bar / weak close is a **buying climax / topping-out / effort-vs-result anomaly at a top = BEARISH exhaustion**, not a continuation buy. The book is explicit: extreme volume signals an *imminent reversal* (p.48); a wide up bar on low volume is a *trap* (p.95-96); high volume + small result = *distribution* (p.24, p.97).

**Therefore any VPA-derived daily BUY sign MUST require the confirmation VPA itself demands — and must NOT rank by spike size:**
- The volume spike must come with the **right close position / wick / reversal bar** for its trend location: a long **lower** wick + close in the upper third at a **bottom** (stopping volume / selling climax), NOT a high close on a high-volume up bar at a top.
- Require **multi-bar completion** (2-4 bar climax window) + a following **low-volume test** + a strength bar before entry — never act on the spike bar alone.
- Volume must be **relative** (`vol_vs_avg` per stock, rolling baseline), never absolute, and never used as a ranking key by magnitude (bigger ≠ better — that is the inverted axis).
- Even a clean VPA buy sign still faces the repo's **paired fill-order null at ~36 trades/yr** (CLAUDE.md Methodology): a real, exogenous key does not lower that bar. Treat any of these as candidate *signs* to benchmark, then test selection value separately under the null.

### Concrete new-sign candidates (each = a Stage-0 hypothesis, not an edge)

1. **`no_demand`** — narrow-body up bar, `vol_vs_avg < ~0.8`, within/after an up-leg → bearish/exhaustion. Test as a short or as an exit/avoid filter on longs.
2. **`no_supply`** — narrow-body down bar, low volume, within a base/down-probe → bullish. Pairs with the test bar. **→ Stage-0 REJECT (2026-06-27):** on daily JP bars the volume of an uptrend pullback bar is uninformative (vmult-quartile drift is flat/non-monotone; VPA candle-shape confirm adds nothing). Replicated with a STRICT strong-uptrend (close>SMA20>SMA50, rising SMA50, +20-bar advance, ADX≥20) pullback-to-the-MA spec — still flat — so the null is not a loose-gate artifact. See `src/analysis/no_supply_stage0.py`, `no_supply_strict_stage0.py`, and memory `project_no_supply_stage0_reject.md`.
3. **`stopping_vol`** — N-bar window: shrinking bodies, long lower wicks, `close_pos > 0.5`, rising above-avg volume, after a steep decline, terminating in a hammer → bullish reversal setup. Compare/overlap with `rev_nlo`.
4. **`vpa_test`** — low-volume down-probe (`vol_vs_avg < 1`, long lower wick, `close_pos > 0.5`) back into a recent high-volume zone, followed by an above-avg-volume up bar → long trigger.
5. **`climax_rev`** — 2-4 bar extreme-volume cluster at a trend extreme with the correct wick/close (lower wick + upper-third close at a bottom = bullish; upper wick + lower-third close at a top = bearish). **This is the disciplined replacement for the rejected `lowprice_volspike`** — it requires the reversal-bar confirmation the naive trigger lacked.
6. **`vol_breakout_confirm`** — range/pivot breakout with decisive close beyond the level AND `vol_vs_avg > 1` rising; the low-volume-break complement is a `fakeout` flag (potential short/avoid). Implement as a volume gate on `brk_sma`/`brk_bol` and A/B against the ungated sign. **→ Stage-0 REJECT, INVERTED (2026-06-27):** on daily JP the gate is backwards — high-volume breakouts UNDERperform low-volume ones (heaviest vmult quartile worst across DON20/DON40/SMA20x; gate edge negative every horizon, dose-response worse). A high-volume breakout bar = exhaustion, not confirmation (same mechanism as `lowprice_volspike`). See `src/analysis/vol_breakout_confirm_stage0.py` and memory `project_vol_breakout_confirm_stage0_reject.md`.

For each, Stage-0 the per-fire DR / forward-return distribution against the relevant baseline (and gate on close-position confirmation), then — only if a per-fire edge survives — proceed to the paired fill-order null on the 6-slot book before claiming any selection value.
