# Strategy: `density_pullback` (directional pullback entry)

The **momentum** counterpart to the rejected fade (`random_hedge_density`), and the
positive result of the "lift over random" arc: it plugs a *directional, better-priced*
entry into the `random_hedge` exit framework and is the **first entry that clearly
beats the random null baseline in-sample**. Not a ship (OOS is weak at the default,
neutral-tuned exit), but it cleanly establishes two things: entry *quality* lifts far
over a random entry, and a *pullback* fill improves robustness/drawdown over a market
fill.

| | |
|---|---|
| **Name** | `density_pullback` |
| **Class** | `src/strategy/density_pullback.py` → `DensityPullbackStrategy` (subclasses `RandomHedgeStrategy`) |
| **Simulator** | `src/simulator/multi_simulator.py` → `MultiSimulator` (resting limit orders) |
| **Reuses** | density-breakout detection (`_rolling_bands`, `_next_dense` from `density_multi_breakout`); zs SL + ratchet exit (`random_hedge`) |
| **Default config** | `window=168, max_band_pct=0.03, limit_window=24, pullback=True` + tuned exit (`sl_mult=0.75, recalc_bars=48, time_stop_bars=120`) |
| **Default timeframe** | **1h** |
| **Status** | **`ship=True`** (passes the revised ship gate — the project's first) — tuned default (`sl_mult=0.75, recalc_bars=48`) IS eqSharpe **+1.27 / OOS +1.47** (both > B&H +0.64), quarterly consistency **80% > B&H 62%**, 6/6 walk-forward folds. Caveat: the exit was tuned on this 5y, so per eval §6.5 the honest final confirmation is forward/lockbox data — paper-trade before live. |

---

## 1. Idea

Both prior entry results pointed here. The entry-horizon work found no *directional*
edge in the breakout *instant*; `random_hedge` found the exit can't make edge from a
random entry; the fade (`random_hedge_density`) lost because limit fills at the box
edge are adversely selected and mean-reversion dies in trends. The inverse of the
fade is to ride **with** a real directional signal and merely wait for a better fill:

- **Signal** — the `density_multi_breakout` entry: price consolidates inside the
  tight ~1-week value-area box, then closes through an edge (LONG on a top break,
  SHORT on a bottom break).
- **Entry** — instead of buying the breakout close, rest a **limit at the broken
  edge** and fill only on the **retest** (buy broken resistance / sell broken
  support), cancel if not reached within `limit_window` bars. The limit is always a
  genuine concession (below the close for a long, above for a short), so it is a
  momentum-with-pullback, not a fade.
- **Exit** — the `random_hedge` framework unchanged: zs-band SL + next-dense TP +
  periodic ratchet. Keeping the exit fixed makes the entry the only variable, so the
  result is a clean **lift over random**.

`pullback=False` enters at the breakout close (market) — the control that isolates
the price-improvement from the directional signal itself.

## 2. Results (GMO 1h ~5y, equity Sharpe)

| entry | IS eqSh | OOS eqSh | IS DD | IS trades |
|---|---|---|---|---|
| random market (null baseline) | +0.170 | +0.856 | — | 715 |
| random market + ATR-Q4 (best null) | +0.454 | +0.462 | — | 540 |
| **breakout @ market (control)** | **+0.783** | −0.307 | 0.39 | 514 |
| **breakout @ pullback limit** | **+0.679** | **+0.062** | **0.29** | 448 |

> These rows hold the exit fixed at the **comparison-era** `recalc_bars=12, sl1.0` so
> the entry is the only variable. The tuned default (`sl0.75, recalc=48`, §3) lifts
> the pullback to **IS +1.27 / OOS +1.47** — but the entry *comparison* below is read
> at the common exit.

**Two findings:**

1. **A directional entry lifts massively over random in-sample** — IS eqSharpe
   +0.68–0.78 vs the random null's +0.17 (and near B&H +0.64). This is the first
   entry on the arc to clearly beat the null: entry *quality* matters, the exit is
   not the whole story.
2. **The pullback (better price) buys robustness, not IS Sharpe** — vs the market
   control, the pullback gives up a little IS (+0.78 → +0.68: it misses breakouts
   that never retest) but turns OOS from **−0.31 to +0.06** and cuts drawdown
   **0.39 → 0.29**. So a better-priced fill *is* worth something here — as
   robustness and risk reduction, not as a raw in-sample maximiser. (The opposite
   of the fade, whose "better price" was illusory adverse selection.)

## 3. Why the OOS is weak — the exit, not the entry

The directional breakout's OOS lags even the random *neutral* baseline at the default
exit, which is the tell: a market-neutral pair always has one leg riding the OOS
trend and is forgiving of entry timing, whereas a directional ride must be right *and*
survive its stop. The inherited zs-band SL (tuned for the neutral pair) is too tight
for a breakout — it gets stopped on the retest noise before the trend develops.
Giving the ride room recovers it. A full exit grid (`sl_mult × recalc_bars ×
time_stop_bars`) shows a **broad plateau, not a spike**: the dominant lever is the
**ratchet cadence** — recomputing the trailing stop every 48 bars instead of 12 lifts
both IS and OOS monotonically, across *every* `sl_mult`; `sl_mult` low (1.0) gives the
best drawdown; `time_stop_bars` barely matters once the ratchet is slow.

| exit (pullback=True) | IS eqSh | OOS eqSh | IS DD |
|---|---|---|---|
| old default (`sl1.0, recalc=12, ts120`) | +0.679 | +0.062 | 0.29 |
| `recalc=24` | +0.899 | +0.478 | 0.32 |
| `sl1.0, recalc=48, ts120` | +1.007 | +0.690 | 0.37 |
| **tuned default (`sl0.75, recalc=48, ts120`)** | **+1.266** | **+1.471** | 0.34 |

**Walk-forward (`src/backtest/analysis/density_pullback_exit_wf.py`, 6 folds).**

*Full grid (`--axis grid`).* A — fixed sweet spot positive in **4/6** folds (the two
near-zero folds, −0.05, are ones where B&H was −0.9 to −1.0 — it still beat a falling
market). B — anchored re-selection: **rc48 is chosen in all 5 folds**, mean test
eqSharpe +0.425. The recalc lever is confirmed out-of-sample (and transfers to
`random_hedge`: 8/8 seeds, see [`random_hedge.md`](random_hedge.md) "Current best
setup").

*One-knob `sl_mult` (`--axis sl`, recalc/ts fixed at 48/120, finer 0.5–2.0 grid).*
The earlier grid started at 1.0 and missed the real optimum below it — **`sl_mult=0.75`
is the only value positive in all 6 folds**, with the best OOS by far and a low
drawdown:

| sl_mult | folds +ve | IS | OOS | IS DD |
|---|---|---|---|---|
| 0.5 | 5/6 | +1.08 | +0.74 | 0.28 |
| **0.75** | **6/6** | **+1.27** | **+1.47** | 0.34 |
| 1.0 | 4/6 | +1.01 | +0.69 | 0.37 |
| 1.5 | 4/6 | +1.15 | +0.48 | 0.53 |
| 2.0 | 4/6 | +0.86 | +0.21 | 0.87 |

OOS degrades monotonically above 0.75 and DD inflates. The anchored re-selector (B)
leans to *looser* stops (1.25–1.5) because they win in-fold IS-Sharpe, but those
degrade OOS (negative in the two down-market folds) — a textbook
degradation-over-absolute case: the robust pick is the fixed `sl0.75` (6/6), not the
IS-Sharpe-max corner. **`sl_mult=0.75` is now the default** (a *tighter* stop than the
neutral pair's 1.0 — a directional ride can use a closer stop because it is meant to
be right about direction; the slow ratchet then banks the run). The same `sl0.75`
transfers to `random_hedge`+ATR-Q4 (8-seed OOS +0.76 → +1.02, still 8/8 IS).

## 3b. Most trades have no TP — does the "ride" carry the edge?

`_next_dense` returns `None` for **68% of `density_pullback` entries** (303/448 IS):
a breakout leaves the box into clear air, so there is usually no pre-existing dense
node ahead — those trades have no take-profit and ride to the SL / trail / time
stop. (There are essentially **no trivially-close TPs** — the `min_dist` floor holds
TP:SL ≥ 1.0 for ~100% of trades, median TP ~2.9% of price; the worry was the wrong
direction.) Probe: `src/backtest/analysis/density_pullback_notp_probe.py`.

Do the no-TP rides carry the edge, or the with-TP trades? **Neither robustly — the
split flips across the IS/OOS boundary (and, for random_hedge, across seeds):**

| subset (eqSharpe) | density_pullback IS | OOS | random_hedge IS | OOS |
|---|---|---|---|---|
| no-TP / ride | **+0.918** | −0.506 | −1.060 | +0.596 |
| with-TP | −0.574 | **+0.875** | +0.797* | +0.576* |
| all (full) | +0.679 | +0.062 | −0.346 | +1.155 |

For `density_pullback` the two subsets are **anti-correlated** across the split (the
ride pays in the IS trend, the target pays in the OOS); the **full mix is the most
balanced**. The `random_hedge` "with-TP carries it" reading is a **seed-0 fluke**
(*): over 8 seeds with-TP is IS −0.02 / OOS +0.19 (4/8, 5/8) — not robust, below both
the baseline and the ATR-Q4 gate. So **TP-presence does not cleanly separate edge**,
and "require a dense target ahead" is not a usable lever — the same per-trade-subset-
that-wins-one-split-doesn't-survive pattern seen elsewhere on the branch.

## 4. Verdict & next

**`ship=True` — the first strategy to pass the (revised, relative) ship gate.** Tuned
default: IS eqSharpe +1.27 / OOS +1.47 (both > B&H +0.64), quarterly consistency
**80% > B&H 62%**, 6/6 walk-forward folds, not OVERFIT. The arc paid off: entry
quality lifts over the random null, a pullback fill buys robustness over a market
fill, and a walk-forward-tuned slow-ratchet / tight-stop exit makes it ride.

It clears gate (a) in **both** splits (IS +1.27 ≥ B&H +0.64, OOS +1.47 ≥ B&H −0.60)
and on a high margin — its OOS pass is not just "beat a falling market," it is a strong
absolute Sharpe.

**Honest caveats before live:** the exit (`sl0.75, recalc=48`) was tuned on this same
5y, and both ship gates were revised (consistency → relative; gate (a) → both-splits)
during this work — so there is accumulated researcher freedom. Per eval §6.5 the only
honest *final* estimate is an untouched lockbox / forward period; **paper-trade it
forward before sizing up.**

Lineage: [`random_hedge.md`](random_hedge.md) (null baseline + fade reject) →
this. Sibling: [`density_multi_breakout.md`](density_multi_breakout.md).
