# Price Action Trading — Al Brooks (Reading Price Charts Bar by Bar)

> Source: Al Brooks, *Reading Price Charts Bar by Bar* (Japanese ed. プライスアクショントレード入門).
> Distilled from notes covering pp.1–228 (Ch.1 Price Action → Ch.15 Best Trades + Glossary).
> **All original material is intraday 5-min (E-mini & US stocks), one indicator only: the 20-bar EMA.**
> Setups marked **(intraday-specific — adapt or skip for daily)** depend on tick-scalp math, the
> first hour, news/FOMC, or options; everything else is structural and transfers to daily bars.
> This repo trades **Japanese stocks on DAILY bars** with a two-bar fill (signal on bar T, fill at
> open of T+1), so read "1 tick beyond the signal bar" as "stop-entry at the signal bar extreme,
> filled next bar". See the final section for the repo mapping (that section is the reader's own
> synthesis, not Brooks).

---

## Core Concepts & Vocabulary

Glossary (pp.222–228) plus key terms used throughout. Each 1–2 lines.

- **Bar / trend bar / doji** — A *trend bar* has a real body (close ≠ open, directional). A *doji* has little/no body (≤1–2 ticks on 5-min) = a one-bar trading range, neither side in control (p.12, p.225).
- **Signal bar** — The bar that completes a setup; the last bar before the entry bar. Decisions are made on its close (p.223).
- **Entry bar** — The bar on which the order actually fills (1 bar after the signal bar) (p.223).
- **Reversal bar** — A trend bar opposite the trend. **Bull reversal bar** (buy signal): opens at/below prior close, closes above its open *and* above prior close, **lower tail = 1/3 to 1/2 of the bar's range**, little/no upper tail, bull body, sticks out (does not overlap prior bars). **Bear reversal bar** = mirror (upper tail 1/3–1/2 of range, closes below open & prior close) (p.15–16, p.226).
- **With-trend vs counter-trend** — *With-trend* = in the dominant trend's direction (≈ direction of the last 5-min signal; or "if 10–20 recent bars are below the EMA, sells are with-trend"). *Counter-trend / fade* = opposite the trend (p.223, p.226).
- **Trend / trading range / breakout** — *Trend* = price runs corner-to-corner with no large opposing swing. *Trading range* = sideways, neither side in control. *Breakout* = current bar exceeds a prior important price (swing, trendline, prior bar, range edge, prior-day H/L) (p.226–227).
- **Trendline vs trend channel line** — *Trendline* drawn in trend direction through swing lows (uptrend) / highs (downtrend). *Trend channel line* drawn parallel on the OPPOSITE (extreme) side — across highs in an uptrend, across lows in a downtrend (p.226).
- **Micro trendline** — A line touching most of just ~2–10 consecutive bars in a strong trend; one bar's small pullback breaks it and that breakout usually fails → High1/Low1 with-trend entry (p.227).
- **EMA (20)** — The only indicator Brooks plots; 20-bar EMA on the 5-min chart (p.222). On a 1-min proxy he uses the 90-EMA for the 5-min 20-EMA (p.108).
- **High1–4 / Low1–4** — Count of legs in a pullback. In an uptrend pullback, *High1* = first bar whose high exceeds the prior bar's high; after a lower high forms, the next such bar = *High2*, then High3/High4. Low1–4 = mirror in a downtrend (p.224, p.227, p.57–62).
- **M2B / M2S** — *Moving-average 2nd Buy / Sell*: the High2 (uptrend) / Low2 (downtrend) that forms as a **two-leg pullback reaching the EMA**. The highest-confidence H2/L2 variant (p.72, p.222).
- **ii / iii / ioi** — *ii* = two consecutive inside bars (2nd ≤ 1st). *iii* = three. *ioi* = inside-outside-inside. All are low-volatility breakout-soon patterns; trade the breakout 1 tick beyond the pattern (p.18–19, p.222).
- **Harami (はらみ / inside bar)** — A bar whose high ≤ prior high and low ≥ prior low. More reliable signal when its body is in the trade direction (p.17–18, p.226).
- **Twins** — Two adjacent similar-body bars. *Up-down twin* (bull then bear) = sell setup. *Down-up twin* (bear then bull) = buy setup. *Double-top twin* (two equal highs in an uptrend) = bull-flag continuation buy. *Double-bottom twin* (two equal lows in a downtrend) = bear-flag continuation short (p.17, p.19, p.23–24, p.225).
- **Outside / encompassing bar (包み足)** — High > prior high AND low < prior low; essentially a one-bar trading range. Read by where it closes (p.28, p.225).
- **Shaved bar (坊主)** — A bar missing one or both tails (close at an extreme) = one-sided pressure (p.19, p.227).
- **Gap** — Any space between two prices. *Opening gap* = today's first bar opens beyond prior bar's range. *EMA-gap bar* = a bar that does not touch the EMA (uptrend: high below EMA) (p.67, p.222–223).
- **Climax** — A move that goes too far too fast, then reverses into a range or opposite trend; usually overshoots the trend channel line first (p.223).
- **Spike-and-channel** — A climactic *spike* (surge) launches a trend, then a slower trending *channel* forms. The channel start is usually retested within 1–3 days (p.58–61).
- **Wedge / three-push** — Three pushes (3 legs) into a trend extreme, trendline & channel line converging; usually overshoots the channel line then reverses. Trade ALL three-push patterns as wedges (p.64–69, p.223).
- **Final flag** — The last flag/tight range of a trend; its breakout often fails right at the trend's end (**final flag failure**) → reversal of ≥2 legs ≈ flag height (p.141).
- **Breakout pullback (BOPB)** — A small 1–5 bar pullback within 2–3 bars of a breakout; the breakout becomes a false breakout and that failure also fails ("failed failure") → reliable re-entry in the breakout direction (p.94–95, p.227).
- **False breakout (ダマシ)** — A breakout that reverses back through the broken level; most breakouts are false. Fade them or trade the BOPB (p.93, p.225).
- **Failed failure / failure** — *Failure* = price hits the stop before the target (trapped traders forced out). *Failed failure* (ダマシのダマシ) = a false breakout that itself fails → resumes original direction = reliable 2nd-direction signal (p.225).
- **Measured move / AB=CD** — Project a leg's height for a target: 2nd leg ≈ 1st leg (AB=CD); or after a breakout, project from the tight-area/flag midpoint (p.71, p.98–101, p.159).
- **Magnet** — A price that attracts price (prior swings, gaps, trendlines, round numbers, prior failed-reversal signal bars, stop clusters). A tendency only — never fade with limit orders off a magnet alone (pp.98–104).
- **Two-legged move (ABC)** — Most pullbacks and most trends make ≥2 legs; a failed 2nd test → resumption of the original direction (basis of all H2/L2 trades) (p.49, p.71, p.154).
- **Swing high / low** — A bar that pokes well above (high) / below (low) its neighbors (p.224).
- **Barbed wire (barb wire)** — A tight range of 3+ heavily-overlapping bars including ≥1 doji, usually mid-day near the EMA at ~½ day's range. Most dangerous pattern; fade extremes only, never trade its breakouts (p.85–90, p.226).
- **Shrinking stairs** — A 3+ swing trend where each new breakout is SMALLER than the last = waning momentum → reversal/trendline-break likely (p.61–62, p.224).
- **Pause bar** — A bar that does not advance the trend (high ≤ prior high in an uptrend); can become a reversal/entry setup (p.227).
- **Scalp / swing / scratch** — *Scalp* = small profit, exit before a pullback (E-mini 4–8 ticks; SPY/stocks 10–20c; pricey stocks $1–2). *Swing* = held through ≥1 pullback, part with no target. *Scratch* = exit near breakeven (p.224).
- **Trapped trader / trap (落とし穴)** — Price reverses before a fresh trade reaches target, stopping it out; the trapped crowd's forced exits fuel the opposite move (p.223).

---

## The Universal Entry & Stop Mechanic

The backbone of every setup (p.11, p.14, p.162–165).

- **Stop-entry, 1 tick beyond the signal bar.** Wait for the signal bar to fully close, then enter on a **stop order 1 tick beyond it in the trade direction**: buy-stop 1 tick above the signal bar's high; sell-stop 1 tick below its low. If never hit, cancel and wait for the next setup. (You may *straddle* a bar with stops on both ends and let the market pick the side.)
- **Stocks "1-tick trap" variant.** In stocks, place the entry stop **2–3 ticks** beyond the bar (not 1) to avoid being filled by a 1-tick poke that then reverses (p.22). On $200 stocks allow 5–10 cents.
- **Signal bar must be a with-direction trend bar.** Only buy if the signal bar is bullish (close > open); only sell if it's bearish. A doji or wrong-direction bar means your side does not yet have control → wait for a 2nd signal (p.14–15, p.23, guideline 27). Strength: body well past the open, close near the extreme, no opposing tail.
- **Initial protective stop.** 1 tick beyond the OPPOSITE extreme of the signal bar (long: 1 tick below the signal bar's low) until the entry bar completes.
- **Trail to the entry bar.** After the entry bar closes, move the stop to 1–2 ticks beyond the entry bar (p.163–164, p.185).
- **Move to breakeven, then trail.** After the first target / scale-out, move the stop to ~breakeven. Best trades rarely go more than ~3 ticks (sometimes 5 E-mini points) against you after entry; an unusually good fill is a warning the read is wrong (p.164, guideline 21).
- **Always swing part.** Scalp 25–75% at the first target, swing the rest with no fixed target, trail to breakeven. Moves routinely blow far past targets (p.118, p.158–161). For a strong setup, swing all and scale out ⅓–½ at 2–3× the initial risk.
- **Money-stop sizing.** If the signal/entry bar is too big, use a money stop instead: e.g. **8 ticks on the E-mini 5-min**, or **~60% of the signal-bar height / pullback** (place a long's stop ~40% up from the signal-bar low toward entry). Cut position size to keep $ risk constant (e.g. wide-range day → 50–75% size, wider stop, bigger target) (p.55, p.163–164).
- **Daily optimal stop = largest stop needed in the first hour** (intraday-specific): on E-mini most days work with 8 ticks; if the first hour needed 9, remember 9 for the day and raise the target too (p.164–165).
- **Stop hit → reverse?** If stopped before any profit you were trapped; sometimes reversing is right (e.g. a failed Low2 short = a buy). But **do NOT reverse inside a tight range**; re-enter quickly when trapped out of a good trend trade (p.163, guideline 9–10).

---

## Setups Catalogue

For each setup: **Type · Context · Entry · Stop · Exit/target · Pages · Notes.** Grouped into seven buckets. (Unless noted, entry = stop-entry 1 tick beyond the signal bar, stop = 1 tick beyond its opposite extreme.)

---
### (a) With-Trend Pullback Entries
---

#### High1 / Low1 — first-pullback scalp at the strongest part of a trend
- **Type:** with-trend continuation (scalp).
- **Context:** Only the strongest part of a trend. H1 = first bar whose high exceeds the prior bar's high (ends the first down/sideways leg of an uptrend pullback); L1 mirror.
- **Entry:** Buy H1 (uptrend) / sell L1 (downtrend), best when the H1/L1 is a **micro-trendline-break false breakout** in a strong trend, OR after a strong move far past the EMA the first pullback reaches the EMA.
- **Stop/Exit:** Beyond the signal bar; scalp most (high-probability but small).
- **Pages:** p.41 (Bar5), p.50–51, p.73–74.
- **Notes:** H1/L1 alone is otherwise too early — wait for H2/L2. In a strong downtrend a High1 is still a good buy; in a strong uptrend don't wait for H4.

#### High2 / Low2 (= M2B / M2S) — two-legged pullback continuation (the core entry)
- **Type:** with-trend continuation (primary trade).
- **Context:** Trend with momentum; a 2-leg (ABC) pullback. **M2B / M2S** = the H2/L2 whose two-leg pullback *reaches the EMA* — the highest-confidence variant.
- **Entry:** Buy the High2 (uptrend) / sell the Low2 (downtrend), 1 tick beyond the signal bar. Prerequisite: a **minor trendline must have broken** during the pullback (shows the counter-side briefly active); otherwise the "H1, H2" is just the first counter-leg.
- **Stop:** Beyond the H2/L2 signal bar.
- **Exit/target:** Trend continuation; scalp part, swing part; expect a test of the prior trend extreme.
- **Pages:** p.32–34, p.43–48, p.57–62, p.72, p.77, p.213–216.
- **Notes:** Past H4/L4 it is probably a new swing, not a pullback — reconsider. M2B/M2S have very high win rates on strong-trend days — take them. A bar far from the EMA is not a clean M2B. ii/ioi variants count as H2/L2 setups.

#### EMA pullback / EMA-gap-bar2 entry
- **Type:** with-trend continuation.
- **Context:** Trend riding one side of the EMA; price pulls back to (or gaps away from) the EMA. *EMA-gap bar* = a bar not touching the EMA (uptrend: high below EMA → "gap up to EMA" that the market tries to fill).
- **Entry:** When price reaches the EMA and turns, buy 1 tick above the first bar whose high fell below the EMA (uptrend). **EMA-gap-bar2** = after the gap, the 2nd attempt back above the prior bar's high = the tradeable buy (mirror for shorts above the EMA in a downtrend).
- **Stop/Exit:** Below the EMA pullback low; swing part (EMA tests are especially reliable in stocks and deepen each time until a major-trendline break).
- **Pages:** p.42 (Bar8), p.67–70, p.105 (Fig 1.10 bar8), p.139, p.194–195, p.213–216.
- **Notes:** In a strong trend only the first 2–3 EMA tests need a formal stop-entry. **2HM** (price off the EMA ≥2 hrs): the first touch back is a high-win-rate with-trend scalp (intraday-specific timing, but "long stretch off the MA → fade the first return" transfers).

#### Double-Bottom Bull Flag / Double-Top Bear Flag (continuation)
- **Type:** with-trend continuation (NOT a reversal here).
- **Context:** Two pullbacks to ~the same level inside a trend (double bottom in an uptrend / double top in a downtrend); often the first pullback of a trend day. Legs may slightly under/overshoot — more reliable when they undershoot.
- **Entry:** Buy 1 tick above the bar at the 2nd bottom (bull flag) / sell 1 tick below the 2nd top (bear flag).
- **Stop:** Below the 2nd low (bull) / above the 2nd high (bear).
- **Exit/target:** Trend continuation; measured-move target ≈ 1–2× the range height.
- **Pages:** p.43, p.57–58, p.64–66, p.71–72, p.120, p.184.
- **Notes:** Most continuation patterns work and most reversal patterns fail in a trend — keep with-trend. Distinct from the **Double-Bottom Pullback** reversal (bucket b). A strong drop is the bear flag's "pole."

#### Trendline pullback entry
- **Type:** with-trend continuation.
- **Context:** Established trend with a clean trendline through swing points.
- **Entry:** When price pulls back to the trendline (even over/undershooting) and reverses, enter in trend direction on the reversal bar (buy 1 tick above it at an up-trendline).
- **Stop/Exit:** Beyond the reversal bar; trend resumes toward the extreme.
- **Pages:** p.36–37.
- **Notes:** Don't bother drawing the line if obvious. Don't buy the pullback if the prior move was a climax + trend-channel-line-overshoot reversal — short instead.

#### Micro trendline failed breakout (one of the most reliable with-trend setups)
- **Type:** with-trend continuation.
- **Context:** A micro trendline (2–10 bars) inside a strong trend; one pause/pullback bar pokes through it and the breakout fails.
- **Entry:** Enter in trend direction 1 tick beyond the bar that broke the micro trendline (uptrend: buy 1 tick above the bar that dipped below the line). Poke can be <1 tick.
- **Stop/Exit:** Beyond the signal bar; mostly scalps (use the 5-/3-min micro line, not every 1-min break).
- **Pages:** p.38–42 (Figs 2.5–2.8), p.52 (Bar9–10), p.73, p.122, p.136–138, p.213–216.
- **Notes:** Effectively a BOPB + final flag of the counter-trend. If the entry itself fails within 1–2 bars (a "false-breakout of the false-breakout"), that becomes the reliable BOPB. Long narrow micro channels (~10 bars) almost always break-and-fail.

#### Pyramid / add-on entries in a strong trend
- **Type:** with-trend continuation (sizing).
- **Context:** Confirmed strong trend (every tick is a with-trend entry).
- **Entry:** Add on each pullback (High1/High2, EMA test, BOPB) as long as the opposite side hasn't taken control; move the WHOLE position's stop to 1 tick beyond the last signal bar and trail.
- **Pages:** p.35–36 (never too late), p.93, p.193 (daily pyramiding), p.213–216.
- **Notes:** "Never too late": if you'd still hold the swing part had you entered earlier, enter NOW at the same size and same trailing stop — risk is identical.

---
### (b) Reversal Setups
---

#### Trendline-break reversal — first lower-high / higher-low after a MAJOR trendline break + retest of the extreme
- **Type:** reversal (the book's single most important reversal structure).
- **Context:** **Two universal conditions (p.104):** (1) absolute — the prior major trendline (≥10–20 bars / ~1 hr) must break; (2) usual — after the break, price retests the prior extreme (may under/overshoot, but not by much).
- **Entry:** New downtrend → sell the **first lower high** after the break. New uptrend → buy the **first higher low**. The *best* pattern: a strong break, then a **two-leg move that updates the extreme** (higher high / lower low) and fails (a trap) → powerful reversal of ≥2 legs.
- **Stop:** Beyond the lower-high / higher-low (the reversal extreme).
- **Exit/target:** First target = retest of the prior extreme; expect ≥2 legs; swing part.
- **Pages:** p.104–115, p.140–141, p.206, p.208–209, p.220–228 (Fig 15.x). 
- **Notes:** Most reversal patterns FAIL (trends last longer than expected) → never fade before the trendline break (guidelines 7, 22, 30). Strong-break signs: large range, far past EMA, breaks the last higher-low/lower-high, lasts 10–20 bars, a prior trendline break already occurred.

#### Second-entry reversal (2回目の仕掛け)
- **Type:** reversal (and general "take the 2nd attempt" rule).
- **Context:** After a strong move (≥4 trend bars against the fade direction), or a persistent trend making new extremes while the opposite side appears. Daily-chart bottoms: the 2nd reversal up usually pays more than the 1st.
- **Entry:** Don't fade the 1st attempt — enter on the **2nd entry** (2–3 bars later, same reasoning). Good 2nd entries fill at the same or worse price than the 1st (an easy/better fill is suspect — likely a failed-H2/L2 trap).
- **Stop/Exit:** Beyond the 2nd-entry extreme; high win rate; always swing part of a strong reversal.
- **Pages:** p.33–35, p.34–35 (wait-for-2nd), p.185, p.204–207, p.222 (glossary), guideline 34.
- **Notes:** If the good 2nd entry also fails, only re-enter on a 3rd attempt if it's a wedge (channel-line failed breakout).

#### Double-Bottom Pullback (long) / Double-Top Pullback (short) — reversal versions
- **Type:** reversal.
- **Context:** After a sell-off, a double bottom forms, then a pullback tests just *above* the double-bottom low (mirror: double top then a lower-high pullback). Best when the higher-timeframe (daily) trendline already broke.
- **Entry:** Buy the pullback that holds above the prior double-bottom low (e.g. an inside bar poking 1 tick above the prior bar) / short the lower-high pullback after a double top.
- **Stop:** Below the double-bottom low / above the double-top high.
- **Exit/target:** Scalp if the 2nd bottom doesn't reach the 1st (may be only a 2-leg sideways correction); swing only if clean + trendline broke.
- **Pages:** p.107–108 (Fig 1.11), p.119–121, p.196–197.
- **Notes:** Distinct from the continuation Double-Bottom Bull Flag. In a *strong* downtrend a slight higher-low is more likely a 2-leg pullback than a reversal — require a strong trendline break first.

#### Trend channel line overshoot reversal (climax fade)
- **Type:** reversal / counter-trend fade.
- **Context:** Price overshoots the trend channel line (the parallel line on the extreme side) then reverses; best on the **2nd occurrence**. Often a climax/parabola where the slope accelerates.
- **Entry:** Fade on the reversal bar after the overshoot (sell an overshot bull channel line). Best with a large reversal bar, even better as a 2nd-entry signal.
- **Stop:** Beyond the overshoot extreme.
- **Exit/target:** ≥2-leg move; often a measured move; swing part.
- **Pages:** p.37–38, p.43–46, p.110–111, p.187 (Fig 12.1 bar6/9), p.221.
- **Notes:** In a *strong* trend most channel-line overshoots are small and fail → they become **with-trend** setups (buy where the trapped counter-trend traders bail). Only fade after the prior trendline breaks. True V-tops/bottoms are rare = a kind of false channel-line overshoot.

#### Wedge / Three-Push reversal
- **Type:** reversal.
- **Context:** Three pushes (3 legs) into a trend extreme, trendline & channel line converging; the 3rd push usually overshoots the channel line then reverses. Slow 3-push pullbacks (2–3 hrs) trap counter-trend traders.
- **Entry:** Counter-trend after the 3rd push overshoots and reverses (enter on the reversal/doji-completion bar). "Double false break" wedge is a great version.
- **Stop:** Beyond the wedge tip (3rd push).
- **Exit/target:** ≥2-leg move, often a **measured move ≈ wedge height**; expect a test of the wedge start; swing part.
- **Pages:** p.64–69, p.74–78, p.123–127, p.223.
- **Notes:** 3rd push smaller than 2nd = fading momentum (can extend to 4th/5th in strong trends). A wedge needs **climactic** action (a spike), not overlapping barbed-wire bars, to reverse — otherwise treat it as a trend-direction setup (see bucket f, wedge failure). Trade ALL three-push patterns as wedges.

#### Expanding triangle reversal
- **Type:** reversal or continuation.
- **Context:** ≥5 swings (sometimes 7, rarely 9), each BIGGER than the last (higher highs AND lower lows); each breakout traps breakout traders. Final reversal usually after 5 reversals.
- **Entry:** Buy the bottom = 1 tick above the lower-low (5th leg) signal bar; sell the top = 1 tick below the higher-high.
- **Stop/Exit:** Below the signal-bar low (long); scalp each leg, swing part once the 5th leg completes.
- **Pages:** p.83 (Fig 4.26), p.126–129 (Figs 8.30–8.32), p.209 (GS daily).
- **Notes:** Equilibrium ≈ midpoint of the move = a rough target gauge.

#### Spike-and-Trading-Range climax reversal
- **Type:** reversal (climax — see also bucket e).
- **Context:** A climactic spike, then a 1–2 bar counter-move, then a narrow trading range (instead of a clean channel).
- **Entry:** Trade the **breakout of the narrow range** in the direction it breaks. Within the range, counter-trend double-top/double-bottom flags give with-new-trend entries.
- **Stop/Exit:** Beyond the range / signal bar.
- **Pages:** p.121–123 (Figs 8.22–8.24).
- **Notes:** A breakout bar followed by an inside bar = a small spike-and-trading-range reversal setup. Plan both directions.

#### Up-Down Twin / Down-Up Twin reversal
- **Type:** reversal (2-bar pattern ≈ a reversal bar on a higher timeframe).
- **Context:** Two adjacent similar-body bars at a swing extreme. *Down-up twin* (bear then bull) at a swing low = buy; *up-down twin* (bull then bear) at a swing high = sell.
- **Entry:** Buy 1 tick above the up (2nd) bar of a down-up twin / sell 1 tick below the down (2nd) bar of an up-down twin.
- **Stop/Exit:** Beyond the twin's opposite extreme.
- **Pages:** p.17, p.24, p.26, p.222, p.224.
- **Notes:** NOT valid if the twin is a flag below/above the EMA inside a trend (then it's counter-trend; skip). Often pre-empted by traders entering the M2B/M2S before the bar closes.

---
### (c) Breakout & Breakout-Pullback
---

#### With-trend breakout in a strong trend
- **Type:** breakout continuation.
- **Context:** Strong trend; breakout bar is large, high-volume, 2–3 bars follow-through; pullbacks rare.
- **Entry:** Every breakout beyond a prior extreme is a with-trend entry; you may enter at market at swing size with a protective stop. Better R/R: enter the **1st or 2nd pullback** after the breakout, not the breakout itself. If no pullback comes, enter at market or on a 1-min pullback at half size after ≥2 strong (or 3–4 medium) trend bars.
- **Stop/Exit:** Protective stop; scalp half then breakeven; trail and add on pullbacks.
- **Pages:** p.29, p.93–94 (Fig 6.1).
- **Notes:** Don't buy blindly — skip the 3rd push to the channel line and breakouts that retest a prior high after a trendline break (reversal risk).

#### Breakout pullback / breakout test (BOPB)
- **Type:** breakout continuation (highest-value harvest of breakouts).
- **Context:** After a breakout, price pulls back to within ~2–3 ticks of the entry/breakout price (1 bar to 20+ bars later). Does NOT require an actual breakout first — a 1–4 bar approach that stalls short then pulls back counts.
- **Entry:** Place a stop order 1 tick beyond the test bar in the breakout direction — filled if the move resumes, NOT filled if the test becomes a reversal bar. A "failed failure" (false breakout that itself fails) is the same trade.
- **Stop:** Beyond the test/signal bar; many move to breakeven after the first move stalls (accept ~10–30c "scratch" risk rather than re-entering for 60c).
- **Exit/target:** Trend continuation; ≈ cup-and-handle.
- **Pages:** p.44–45, p.94–97 (Figs 6.3–6.6), p.135–136, p.182–184, p.227.
- **Notes:** The test can overshoot a prior swing by a couple ticks before reversing. Precise tests often poke 1 tick past a breakeven stop (GS 2008 notorious) — re-enter 1 tick beyond the tested bar. The single most reliable first-hour pattern type (with false breakouts).

#### ii / iii / ioi breakout
- **Type:** breakout (either direction; take with-trend in a trend).
- **Context:** Two/three consecutive inside bars (or inside-outside-inside) in the middle of the range = coiled low volatility.
- **Entry:** Stop order 1 tick beyond **both ends** of the pattern (not just the final bar); in a trend take the with-trend breakout. For ioi, only take the breakout if there's a reason price will run (e.g. ioi at a new swing high → down-breakout short, the inside bar low = first entry).
- **Stop/Exit:** Beyond the pattern (add cushion for a tiny entry bar — barbed-wire risk).
- **Pages:** p.18–19, p.21–23, p.35–36, p.222.
- **Notes:** A 5-min ii is often a 1-min double top/bottom → a small ii can launch a sizeable counter-trend move. A with-trend ii breakout after a long move + trendline break is usually only a scalp that reverses near target (= final-flag failure); the counter-trend ii breakout often leads to a big reversal.

#### Outside-bar entries
- **Type:** breakout / trend-bar (context-dependent).
- **Context:** Outside bar = high > prior high AND low < prior low = one-bar range.
- **Entry:** Default: do NOT trade a 5-min outside bar's breakout (buying high/selling low of a range; stop too far). Exceptions: (1) a *trend* outside bar starting the first leg of a reversal acts as a strong trend bar → enter just beyond the **prior** bar's extreme, not the outside bar's far extreme; (2) an outside bar completing a two-leg pullback to the EMA = good with-trend entry; (3) a trapping outside bar (bull outside bar trapping shorts) = entry against the trapped side.
- **Stop:** Money stop or reduced size if the bar is large.
- **Pages:** p.28–31 (Figs 1.22–1.26), p.50 (Fig 1.20 bar2).
- **Notes:** When an outside bar leaves you unsure, WAIT. ioi (inside bar after an outside bar) → trade the ioi breakout.

#### Trading-range breakout (opening / general)
- **Type:** breakout (lower-risk variants preferred).
- **Context:** First 3–10 bars (or any session) form a TR with ≥2 reversals; range < average daily range → breakout likely.
- **Entry (lower risk, pick one):** (1) fade with a small bar at the range high (short) / low (buy); (2) wait for the breakout to become a false breakout, then fade; (3) take the breakout-pullback. You *can* enter on the breakout itself but risk is higher.
- **Pages:** p.83–85, p.184–185 (Figs 11.23–11.24).
- **Notes:** Tight ranges break in the **prior-trend direction** and **opposite the EMA side** (range below EMA → breaks down). Barbed-wire ranges → only failed breakouts.

---
### (d) Trading-Range / Fade Setups
---

#### Barbed-wire fade (fade extremes, never the breakout)
- **Type:** range fade (scalp).
- **Context:** 3+ heavily-overlapping bars incl. ≥1 doji, usually mid-day near the EMA at ~½ day's range. Most dangerous pattern.
- **Entry:** NEVER trade the breakout. Fade: a small bar near the range HIGH → sell 1 tick below its low; small bar near the range LOW → buy 1 tick above its high (best when the breakout is only 1–2 ticks). If a bull bar breaks out 2–3 ticks, place a sell-stop 1 tick below its low (fade); if filled and it fails, buy-stop 1 tick above (BOPB).
- **Stop:** Just beyond the small signal bar (tight; ~2 ticks E-mini, cap ~8).
- **Exit/target:** Scalp only — goes nowhere until a trend bar breaks it.
- **Pages:** p.85–90 (Figs 5.5–5.8), p.226.
- **Notes:** Usually breaks in the trend direction → also hunt with-trend H2/L2, BOPB. Rule: most bars below EMA → never buy; above EMA → never sell. The cleanest trade comes AFTER a trend bar clearly breaks and one side wins. M2 off the EMA from barbed wire is good.

#### Horizontal swing-level fade
- **Type:** range fade / with-trend pullback (depends on day type).
- **Context:** Horizontal lines through swing highs/lows act as barriers; their breakouts usually fail and reverse.
- **Entry:** Expect a swing-high breakout to fail → short the lower-high; swing-low breakout to fail → buy the raised low. On *range* days, the 2nd higher-high / lower-low at a horizontal is the best fade. On *trend* days, use horizontals only for pullback entries (double-top bear flag / double-bottom bull flag) at the swing extreme, after a trendline break.
- **Stop/Exit:** Beyond the false-breakout extreme; scalp on range days.
- **Pages:** p.42–43 (Figs 2.9–2.11), p.133–135 (Figs 9.8–9.9), p.210.
- **Notes:** Sometimes the false breakout's false breakout makes a more extreme 2nd high/low → an even better 2nd-entry fade.

#### Trending-trading-range day (stacked ranges) / staircase
- **Type:** range fade within a trend.
- **Context:** A series of stacked tight ranges separated by small breakouts, trending overall (3–4 ranges/day). Or a gently-sloped channel/staircase of ≥3 swings.
- **Entry:** Fade each range's extremes in BOTH directions. When price pulls back into a prior range it usually retraces to that range's opposite end (first target = the most recent counter-trend entry point).
- **Pages:** p.55–58 (Figs 3.11–3.12), p.61–62 (Figs 3.17–3.19).
- **Notes:** A false High2 / Low2-failure inside the range can be a very high-win-rate fade (Fig 3.12 bar15). **Shrinking stairs** (each breakout smaller) → two-leg reversal / trendline break likely; if a step accelerates through the channel line then reverses → ≥2-leg move; if it does NOT reverse → measured move ≈ channel height.

#### Mid-day / middle-of-range caution
- **Type:** (avoid).
- **Context:** Middle third of the session, price in the middle third of the day's range, on non-trend days.
- **Entry:** AVOID. If forced, fade only the day's high/low with patience; put the stop at breakeven fast (a "too-good" mid-day setup is usually a trap).
- **Pages:** p.89–90 (Fig 5.10), guideline 23.

---
### (e) Climax Setups
---

#### Spike-and-channel (climax launches a trend)
- **Type:** climax → with-trend, then channel-start retest.
- **Context:** A climactic spike (after a prior trend's climax) launches a trend, then a tight channel forms.
- **Entry:** Buy pullbacks (BOPB / H1–H2) within the channel; trade ONLY with-trend inside a tight channel (pullbacks too small for counter-trend R/R). Counter-trend only after the channel breaks.
- **Exit/target:** The **channel start is usually tested within 1–3 days** (becomes a range or reverses) — a magnet.
- **Pages:** p.58–61 (Figs 3.13–3.14), p.72, p.90–92 (Fig 5.12), p.198 (Fig 13.7), p.210–211.
- **Notes:** A counter-trend false breakout inside the channel = great with-trend setup. Tight channels LOOK weak (overlapping bars, long tails) but are very strong trends.

#### Spike-and-trading-range climax (reversal) — see bucket (b)
- Cross-referenced: the climactic-reversal variant where a narrow range (not a channel) follows the spike (p.121–123).

#### Climax + two-leg correction (parabola exhaustion)
- **Type:** climax exhaustion.
- **Context:** A persistent climax (e.g. 16 of 17 bars lower highs, or 20 bars of near-pullback-free bull bars = parabolic, unsustainable).
- **Entry:** After the climax + a long (≥1 hr) pullback, do NOT take an EMA pullback with-trend unless very strong; expect a **multi-bar, two-leg correction** (≥1 hr on 5-min), not an immediate V-reversal.
- **Pages:** p.113–114 (Fig 1.15 LEH), p.178 (Fig 4.10 RIMM), p.121.
- **Notes:** Climaxes are frequent on 1-min (several/day), rare on 5-min (~2–3/month). After a parabolic climax expect a two-legged bounce.

#### Climactic-volume capitulation reversal (daily) — REQUIRES a reversal bar
- **Type:** reversal (daily-chart, transfers directly).
- **Context:** A sharp down day on volume 5–10× normal, usually a gap-down, **closing well off the low** with a strong bull bar that breaks the down channel line → tradeable bottom; expect ≥2-leg rally to the EMA over days/weeks.
- **Entry:** Buy on the climax-day close, or next day's pullback, or after the 5-min turns up filling a gap. Cautious: wait to exceed a potential signal bar's high.
- **Pages:** p.198–201 (Figs 13.8 LEH, 13.9 BSC).
- **Notes:** **CRITICAL counter-example:** high volume WITHOUT a reversal bar is NOT a buy (BSC: volume 15× normal but short lower tail, no channel-line break, closed near the low → kept falling). **Volume alone is not a signal — require confirming reversal price action.** Pick the name with the bigger/clearer bull reversal bar.

---
### (f) Failure / Trapped-Trader Setups
---

#### General trapped-trader fade
- **Type:** any-direction scalp on a failed pattern.
- **Context:** Any good-looking pattern that fails. Trapped counter-trend traders' protective stops sit 1 tick beyond the signal/entry bar.
- **Entry:** Place a stop-entry where the trapped traders' stops sit (1 tick beyond the signal/entry bar) — you enter as they bail, in the direction they're forced to flee.
- **Stop/Exit:** Move to breakeven quickly; always scalp at least part (often ≥2 legs).
- **Pages:** p.10, p.116–117, p.139, guidelines 8–10.
- **Notes:** Trapped traders won't re-enter the same direction for a while → price tends to run your way.

#### Failed High2 / Low2 → with-trend entry
- **Type:** failure → with-trend.
- **Context:** H2/L2 are the most reliable with-trend setups; when one *fails* (because someone faded a strong trend with no real trendline break), the failure becomes a with-trend setup the OTHER way. Common right after a climax.
- **Entry:** Trade the failure with-trend — uptrend: a *Low2 failure* = a High2 buy; downtrend: a *High2 failure* = a Low2 short.
- **Pages:** p.106 (Fig 3.12 bar15), p.118–122 (Fig 5.6), p.131–134 (Figs 9.4–9.7).
- **Notes:** A Low2/High2 alone (no prior trendline break) is NOT a counter-trend reason — it almost always fails. A High2 trap (novices think it's an uptrend pullback) → strong sell-off — need a STRENGTH sign (trendline break / higher-high-then-turn) to actually buy an H2.

#### Failed reversal bar → with-trend entry
- **Type:** failure → with-trend.
- **Context:** A reversal bar forms, traders take it, then its extreme is broken (the reversal-bar failure).
- **Entry:** Enter with the original trend 1 tick beyond the failed reversal bar (downtrend: sell 1 tick below a failed bull reversal bar — trapped bulls must bail).
- **Pages:** p.26 (Fig 1.19), p.20 (Fig 1.8), p.21 (Fig 1.9 → harami buy after failed bear reversal).
- **Notes:** In a strong uptrend, don't sell until the bull trendline breaks — a failed bear reversal bar becomes a buy.

#### Final flag failure
- **Type:** failure → reversal (often ends the trend).
- **Context:** A long trend forms a small horizontal flag (often a simple ii); price breaks the trendline, makes a new extreme, then reverses within 2–3 bars.
- **Entry:** Trade the counter-trend reversal once the final flag fails; ≥2 legs expected.
- **Exit/target:** Move ≈ **measured move = flag height** (e.g. flag-high-to-bar-low distance).
- **Pages:** p.71, p.110–111 (final-flag failure buy), p.141–143 (Figs 9.22, 9.24–9.25).
- **Notes:** A micro-trendline BOPB that reverses within 1–2 bars ≈ a final-flag failure. Can develop into a larger flag → wedge → continuation. After several with-trend wins + a long sideways stretch, beware a final-flag trap → the range breakout may fail.

#### Wedge failure → with-trend (false three-push)
- **Type:** failure → with-trend.
- **Context:** A wedge/3-push forms but WITHOUT a prior trendline break or true channel-line-overshoot climax (e.g. overlapping barbed-wire bars). It rarely reverses.
- **Entry:** Enter WITH the trend as the eager wedge faders get stopped out. Do NOT trade counter-trend unless a trendline already broke AND a reversal bar exists (5-min reversal bar in a strong trend).
- **Pages:** p.144–146 (Figs 9.26–9.28).
- **Notes:** A wedge needs climactic action (a spike down/up), not a trading-range/bear-flag, to reverse. Wedge-failure move ≈ measured move = wedge height.

#### Wedge-failure-failure (failure of a failure)
- **Type:** failed failure → reversal/continuation.
- **Context:** A wedge reversal whose failure itself becomes a false breakout making a new extreme = "false breakout of a false breakout" → ≥2-leg move.
- **Entry:** After the wedge high, price dips, sharply reverses toward a new high but fails (2nd failure of the bulls) → strong move likely; enter the resulting direction.
- **Pages:** p.147 (Fig 9.29), p.108 (Fig 1.11 bar7 "failure of a failure").
- **Notes:** Even more reliable on a trend day (with-trend false breakouts are rare → the next attempt likely succeeds).

#### 1-tick false breakout fade
- **Type:** failure → original direction (high reliability).
- **Context:** A signal/entry bar's protective-stop level is taken out by just 1 tick (stocks 1–10c; $200 stock 5–10 ticks) then reverses. The most reliable minor reversal is the last pullback of a strong trend near the EMA, where a pullback to the original entry-stop has little fuel left.
- **Entry:** Enter WITH the original trend 1 tick beyond where the trapped traders were stopped.
- **Pages:** p.129–131 (Figs 9.1–9.3), p.163 (Fig 10.17).
- **Notes:** If the stop is approached within 1 tick but NOT filled, that's effectively a double-bottom bull flag (1st bottom = signal-bar low, 2nd didn't reach the stop) → the trade usually profits.

#### Swing-high / swing-low false-breakout fade
- See **Horizontal swing-level fade** (bucket d) — the same mechanic at swing levels: breakouts of prior swing highs/lows usually fail; fade the failed breakout, preferably after a big trend signal bar. (p.133–135, p.219 Fig 15.21.)

#### 5-tick failed scalp reversal (intraday-specific — adapt or skip for daily)
- **Type:** failure → opposite direction (scalp).
- **Context:** E-mini: a 4-tick scalp needs a **6-tick** move to fill (1 entry + 4 profit + 1 to execute the limit). If price reverses at only ~5 (or 8–9) ticks, trend traders lose control; trapped scalpers' stop-outs fuel the reverse. QQQQ 10-tick target needs ~12 ticks; AAPL ~$1 target stalling at 93c twice = same.
- **Entry:** When the scalp falls 1–2 ticks short and reverses, enter the OPPOSITE direction.
- **Stop/Exit:** Breakeven on the trapped scalpers' fuel; ≥ a scalper's profit.
- **Pages:** p.147–148 (Figs 9.30–9.32), p.222 (glossary).
- **Notes:** Daily adaptation: the *structure* (a move that stalls 1–2 ticks short of an obvious round target and reverses, trapping the breakout crowd) transfers; the exact tick counts do not.

---
### (g) Trendline & Trend-Channel-Line Setups
---

#### Trendline break = first sign of two-sided trading
- **Type:** regime signal (precondition for all reversals).
- **Context:** Successive trendlines flatten / a major trendline (≥1 hr) breaks.
- **Use:** Most trendline *breakouts* are false → set up a with-trend entry on the failure. But a hard/fast break of a MAJOR trendline (big counter-trend bars) → the trend may reverse → trade the reversal after the extreme is retested (bucket b). A trendline break does NOT by itself flip the trend — keep hunting with-trend until the extreme is tested.
- **Pages:** p.36–38 (Figs 2.1–2.2), p.104, p.108–109, p.136–138.

#### Trend channel line break = trend strengthening (not reversal)
- **Type:** with-trend continuation signal.
- **Context:** A trend channel line is overshot/broken *without reversing* = trend stronger than thought.
- **Use:** Trade WITH the trend (a 1–2 bar false breakout of a steep micro-trendline = a great with-trend setup). Most channel-line breakouts are false and lead back into the channel → trade the failed breakout.
- **Pages:** p.37–38, p.45–46, p.136–138 (Figs 9.12–9.16).

#### Dueling lines
- **Type:** with-trend entry / counter-trend scalp at a line cluster.
- **Context:** A long trendline is tested at the same time/level as a shorter opposite-sloped trend channel line.
- **Entry:** The touch (false breakout + reversal) of the cluster = a with-trend entry; the counter-trend channel-line test marks the end of the correction, then testing the long trendline = a near-perfect with-trend entry. A simultaneous overshoot of a channel line AND a crossing counter-trendline = a good scalp.
- **Stop/Exit:** Beyond the line cluster / signal bar.
- **Pages:** p.37–38 (Fig 2.2 bar6), p.43–46 (Figs 2.14–2.16).

#### Trend-channel-line as support / measured-move projection
- **Type:** with-trend / target tool.
- **Context:** A down trend channel line (off prior swing lows) can act as SUPPORT for a later swing low; channel height projects a measured move.
- **Pages:** p.45–46, p.118 (Fig 3.18 Andrews-pitchfork estimate), p.38 (Fig 2.4 H&S right-shoulder projection).
- **Notes:** Head-and-shoulders right-shoulder projection: shift the neckline (as a channel line) parallel to the left shoulder to project the right shoulder — a heads-up only; recent price action dominates.

---

## Trade Management & Exits

- **Scale-out + always swing the rest.** Scalp 25–75% at the first target (E-mini 4–8 ticks; SPY/stocks 10–20c; pricey stocks $1–2), then trail the remainder with NO fixed target — moves blow far past targets (p.118, p.158–161, p.185).
- **Breakeven-stop timing.** Move the stop to ~breakeven only AFTER the first target is hit / first move stalls — not earlier. Best trades rarely go >~3 ticks adverse after entry; on stocks wait until ~$0.60–0.80 in your favor before moving to breakeven (p.119, p.164, p.216–218).
- **Trailing-stop methods.** (1) Signal-bar → entry-bar → breakeven progression; (2) trail 1 tick below each new with-trend signal bar / prior-bar low when pyramiding; (3) tighten on a smaller timeframe near the close (drop to 3-min ~10s before the 5-min bar closes — but a tighter-TF stop can be hit on noise) (p.31–33, p.91, p.185).
- **Measured-move targets.** Project the 1st leg's height (1× or 2×) after breakout-tests, three-pushes, big-up/big-down ranges, and from a tight-area/flag midpoint (AB=CD). Targets are *guidelines for which side to trade*, not limit-fade levels (p.71, p.98–101, p.159).
- **Expect ≥2 legs.** Trends and pullbacks usually make ≥2 legs; after an important reversal hold a swing portion (it can become a new trend); after a strong move the extreme is almost always retested (p.49, p.71, p.154, p.206).
- **Add (増し玉) on with-trend setups.** In a strong trend, add on each pullback/EMA test at swing size, scalp/swing the adds the same way; in a daily uptrend pyramid on each push as long as bears haven't taken control (p.93, p.193, p.213–216).
- **Sizing for risk parity.** On wide-range/volatile days cut size to 50–75% and widen the stop + target to keep $ risk constant; for high-priced stocks reduce shares (p.55, p.163, p.211–212).
- **Time-of-day exits (intraday-specific — adapt or skip for daily).** The day's high/low is often set in the first 1–2 hours; once one extreme is in, the market usually heads to the other by the close (except open-trend days). The 11:00–11:30 "stop-out pullback trap" resumes the trend → use as a with-trend entry, not a flip. Swing first-hour reversals toward the day's extreme (p.69, p.166–167, p.182–183, p.206).

---

## Trading Guidelines / Discipline

Distilled from the ~39 numbered guidelines (p.219–222) plus recurring rules:

- **Take only the best trades.** Until consistently profitable, take ONLY the 2–5 best setups/day (2nd-entry reversals at new swing highs/lows; trend-day pullbacks). Sitting hours doing nothing is the correct policy (#4, #12, #24, #36, #38).
- **Need ≥2 reasons to enter** (with-trend or in-range); 2 is enough. Valid reasons: reversal bar · good signal-bar pattern · EMA pullback (esp. two-leg) · breakout-pullback · breakout test · High2/4 or Low2/4 (counter-trend needs a PRIOR trendline break) · a failure/false breakout (off a prior high/low, flag, trendline, channel-line overshoot, 5-tick failed breakout). Single-reason exceptions: a plain H1/L2 in a strong trend; a channel-line overshoot + good reversal bar; a 2nd-entry point (p.160–162).
- **No counter-trend scalping.** There is no reliable counter-trend pattern; counter-trend trading is slow, certain ruin. Only fade after a MAJOR trendline break + strong reversal bar that tests the extreme — and look with-trend first (#7, #22, #28, #29, #30).
- **Most patterns fail; the failure is the trade.** A failed pattern's false breakout is the 2nd-entry in the original direction = high win rate. When one side gets trapped, the opposite scalp is reliable (#8, #9, #10).
- **Always look for two legs.** Two failed tests of the same level → reliable signal the other way (#34).
- **"Buy low, sell high" EXCEPT in a strong trend** — then buy High2 even at the day's high / sell Low2 at the low. But markets are mostly ranges; after 2–3 legs up don't buy the high unless certain of a strong trend (#19, #27).
- **Trade only what HAS happened, never what you believe WILL happen** (p.138, #3).
- **Keep it simple — one chart, one timeframe, no indicators** (one 5-min chart + 20-EMA). If you can't profit on a bare chart, more analysis won't help. Juggle one ball (#12, #14).
- **Good fill, bad trade.** Be suspicious of better-than-expected fills (your read is probably wrong) — but still execute a good setup (#21).
- **Discipline is the #1 factor; doing nothing for hours is #2.** Trading is easy to understand, hard to execute. Over-trading (2–3 losers in 15 min, chasing low-risk on the 1-/3-min, counter-trend, barbed-wire) is the slow road to ruin (#32, #37, #38).
- **Grow via SIZE, not more trades or more setup types.** Once profitable, increase position size; don't add marginal trades or new patterns (#35, #39).
- **Match your style to your personality** — you should follow your rules with little anxiety (#33).

---

## Daily-Bar Adaptation Notes (for this repo)

*This section is the reader's own mapping to the repo, NOT from Brooks.* Brooks is intraday 5-min; on **daily JP bars with two-bar fill (signal T → open T+1)**, "1 tick beyond the signal bar" becomes a stop-entry at the signal-bar extreme filled next bar. Many structural setups survive the timeframe change; the tick-scalp / first-hour / news / options material does not.

### Translates well to daily bars (structural, regime-driven)
- **Trendline-break reversal + retest of extreme** → a clean daily reversal sign; maps onto `rev_peak` / `rev_nday` (sell first lower-high after a major down-break of an up-trendline; buy first higher-low after an up-break). The "two-leg test that updates the extreme then fails" is the high-conviction variant.
- **Trend channel line overshoot reversal / wedge / three-push** → `rev_peak` variants. A daily bar that overshoots a fitted upper channel line then closes back inside ≈ a peak-reversal sign; the 3-push/wedge geometry is a multi-bar precondition.
- **High2/Low2 (M2B/M2S) two-legged pullback continuation** → a *new* daily sign: "two-legged pullback to the SMA/EMA in an established trend, then resume." Closest existing signs are `str_lag` (lags then catches up) and the breakout family; an explicit `high2`/`low2` continuation detector (count pullback legs, require a prior minor-trendline break, require EMA touch) would be additive.
- **Double-bottom bull flag / double-top bear flag (continuation)** and **double-bottom/top pullback (reversal)** → daily double-bottom/top detectors; reversal version maps to `rev_nlo` (N-day low reversal) / `rev_peak`; continuation version is a distinct sign worth adding (it co-fires with an uptrend, unlike the reversal version).
- **Micro trendline failed breakout** → a `brk`-style sign on a short (2–10 bar) fitted line: a daily false breakout of a short micro-trendline that resumes the trend ≈ a brk-with-trend continuation. Relate to `brk_sma`/`brk_bol` but it is trend-context-specific.
- **Breakout pullback / breakout test (BOPB)** → directly maps to a "breakout then shallow retest then resume" sign layered on `brk_sma`/`brk_bol`; the "failed failure" logic (false breakout that itself fails) is a strong daily entry and could gate the existing brk signs.
- **False breakout fade of swing highs/lows (horizontal levels)** → `rev_nlo` / `rev_peak` at horizontal swing levels; the "swing-high breakout fails → short the lower high" is a daily fade sign.
- **ii/iii/ioi and inside-bar breakouts** → daily inside-bar (harami) coil → breakout sign; low-volatility-then-expansion, relatable to a Bollinger-squeeze (`brk_bol`) precondition.
- **Climactic-volume capitulation reversal (daily) — REQUIRES a reversal bar** → this is *already daily* in the book (Ch.13). Strongly relevant to `div_vol` / `rev_nlo`: a high-volume down day that closes well off the low with a bull reversal bar = buy; high volume WITHOUT a reversal bar = NOT a buy. **This is a direct caution for any volume-spike sign** and echoes the repo's own `lowprice_volspike` REJECT (volume bar = move ending unless price reverses).
- **Spike-and-channel + channel-start retest** → a measured-move/magnet target tool for daily exits; the "channel start is retested within 1–3 days" becomes "within N daily bars."
- **Trend strength checklist & "trade only with-trend in a strong trend"** → regime gating; aligns with the repo's CorrRegime / N225-trend-score work and the "with-trend vs counter-trend" philosophy.

### Maps to existing repo signs
- `brk_sma`, `brk_bol` ← with-trend breakout, breakout-pullback, ii/ioi breakout, micro-trendline failed breakout.
- `rev_nday`, `rev_nlo`, `rev_peak` ← trendline-break reversal, channel-line overshoot/wedge reversal, double-bottom/top pullback, swing-level false-breakout fade, climactic capitulation reversal.
- `str_hold` / `str_lag` / `str_lead` ← the "stock vs index" relative-strength reading is Brooks's "with-trend vs the broader tide"; `str_lag` ≈ a lagging two-leg catch-up (High2-like).
- `div_vol`, `div_bar`, `div_gap` ← climax/volume-without-reversal cautions; the volume-bar-as-exhaustion idea.
- `corr_*` ← Brooks has no correlation analogue; this is the repo's own axis (no mapping).

### Intraday-only (skip or treat as non-tradeable context on daily)
- 5-tick / 6-tick scalp math, QQQQ/E-mini tick targets, the "1-tick trap" exact tick counts.
- First-hour / opening-range / 3rd-bar-15-min-close / 2HM-time / 11:30-trap timing rules (time-of-day structure has no daily analogue; the *structure* of "stop-run then resume" may, but not the clock).
- FOMC/news 30-min emotional-bar handling; pre-market/Globex tests.
- Options chapter (Ch.14) — instrument choice for capping overnight/crash risk; the repo is cash-equity, manual.
- Sub-5-min charts (1-min/3-min) for tighter entries.

### Concrete new-sign candidates worth a Stage-0 study (reader's suggestions)
1. **`high2` / `low2` daily** — two-legged pullback to the 20-EMA in an established SMA-trend, requiring a prior minor-trendline break; with-trend continuation. (Faces the same fill-order-null / regime-dependence scrutiny as every prior selection idea — see MEMORY.)
2. **`micro_brk_fail`** — daily false breakout of a short (3–10 bar) fitted trendline that resumes the trend (a brk-with-trend continuation).
3. **`chan_overshoot_rev`** — daily close back inside a fitted trend channel line after an overshoot = `rev_peak` variant.
4. **`bopb`** — breakout (brk_sma/brk_bol) followed by a shallow retest of the breakout level then resume; or use the "failed failure" as a confirmation gate on existing brk signs.
5. **Volume-reversal gate** — require a bull/bear *reversal bar* (close off the extreme) before treating a volume spike as a signal, per the BSC-vs-LEH lesson; consistent with the repo's existing `lowprice_volspike` REJECT.

> All of the above are *hypotheses to test*, not validated edges. Every selection/ordering/sizing variant in this repo has had to clear the paired fill-order null at ~36 trades/yr; a Brooks-derived daily sign must clear the same bar before it ships.
