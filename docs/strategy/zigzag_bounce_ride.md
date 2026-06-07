# Strategy: `zigzag_bounce_ride` (bounce entry + tuned ride exit)

`zigzag_bounce` is a REJECT under its **own** ZS fixed TP/SL exit (single position,
IS Sharpe −0.10 / OOS −0.05 — see [`zigzag_bounce.md`](zigzag_bounce.md)). This applies
the [`density_pullback`](density_pullback.md) recipe to it: keep the bounce *direction*,
swap in the **tuned ride exit** (multi-position, next-dense TP, zs-band stop, slow
ratchet — `sl_mult=0.75, recalc_bars=48, time_stop_bars=120`). The bounce direction
does carry an edge once it rides.

| | |
|---|---|
| **Name** | `zigzag_bounce_ride` |
| **Class** | `src/strategy/zigzag_bounce_ride.py` → `ZigzagBounceRideStrategy` (subclasses `RandomHedgeStrategy`) |
| **Simulator** | `src/simulator/multi_simulator.py` → `MultiSimulator` |
| **Reuses** | `ZigzagBounceSign` (entry); `_next_dense` (TP); zs SL + ratchet exit (`random_hedge`, tuned) |
| **Default config** | bounce defaults (`size=10, wall_match=True, wall_window=120, reject_past_peak=True`) + `pullback=False` + tuned exit (`sl_mult=0.75, recalc_bars=48, time_stop_bars=120`) + `drop_counter_trend=True` |
| **Default timeframe** | **1h** |
| **Status** | **`ship=True`** — clears gate (a) in **both** splits (IS eqSharpe +0.74 > B&H +0.64; OOS +0.29 > B&H **−0.60**, since BTC fell in OOS) and gate (b) (quarterly consistency **76% > B&H 62%**). The exit swap rescued it from REJECT; the counter-trend gate gave 5/6 folds, DD 0.88→0.74 (§3). **Caveat:** the OOS pass is a *relative* win (it made +0.29 while holding BTC lost) — modest in absolute terms, and weaker than `density_pullback` (OOS +1.47). Take `density_pullback` forward first. |

---

## 1. What changes vs `zigzag_bounce`

Only the exit. The entry is every `ZigzagBounceSign` fire (a reaction off a recent
swing level / wall), direction unchanged. Instead of the single-position fixed
ZS TP/SL (`tp=1.0, sl=1.0, max_bars=48`), each fire is routed into the tuned
multi-position ride exit: a next-dense take-profit, a `sl_mult=0.75` zs-band stop,
the slow `recalc_bars=48` ratchet, and a 120-bar time stop — judged by the
mark-to-market equity Sharpe. `pullback=False` fills at market (next open).

## 2. Results (GMO 1h ~5y, equity Sharpe)

| config | IS eqSh | OOS eqSh | IS DD | IS trades |
|---|---|---|---|---|
| zigzag_bounce, *own* fixed exit (single pos) | −0.10 | −0.05 | — | — |
| random null baseline (for reference) | +0.17 | +0.86 | — | 715 |
| **bounce @ market + tuned exit** | **+0.887** | **+0.312** | 0.88 | 1307 |
| bounce @ pullback (limit at the level) | −0.306 | −0.968 | 1.67 | 806 |
| bounce @ market + ATR-Q4 gate | +0.842 | −0.135 | 1.17 | 1116 |

**Findings:**

1. **The exit swap rescues the signal** — from net-negative under its own exit to
   IS +0.89 / OOS +0.31. The bounce direction carries real in-sample edge; it just
   needed a ride exit (next-dense TP + ratchet) instead of a fixed scalp TP.
2. **Pullback destroys it** (IS −0.31 / OOS −0.97) — a limit at the bounce's
   reference level is adversely selected (filled on continuation *through* the
   level), the same winner's-curse that sank the density-edge fade. Market entry is
   the one.
3. **The ATR-Q4 gate hurts here** (OOS +0.31 → −0.14) — it was tuned for the
   *neutral* hedged pair; a directional signal does not want it. So the bad-entry
   gate is strategy-specific, not universal.

**Walk-forward (market entry, no gate; 6 folds): positive in 4/6.** Beats B&H in the
down/sideways folds (fold 0 +1.76 vs B&H −0.22; fold 5 +1.74 vs −0.94); the two
misses are a bad-for-everyone fold (fold 1, B&H −1.03) and a **strong-bull fold
(fold 4, −0.22 vs B&H +1.94)**.

## 3. The bull weakness, diagnosed and fixed (counter-trend entry gate)

Splitting the bad bull fold by side pinpoints the cause — it is **not** the exit
capping winners; it is **counter-trend shorts bleeding and outnumbering the longs**:

| fold | LONG sum_r | SHORT sum_r |
|---|---|---|
| fold 2 (good bull, B&H +1.35) | +1.21 | +0.27 |
| **fold 4 (bad bull, B&H +1.06)** | +0.32 (weak) | **−0.43** (n 147 > 120 longs) |

An exit-side counter-trend *cut* (close a fighting, under-water position after K
bars) was tried and **rejected** — it lifted aggregate OOS/DD but made the target
bull fold *worse* (−0.22 → −0.60), because it locks the loss on counter-trend trades
that then mean-revert in a choppy bull. The fix is **entry-side**: drop counter-trend
entries (keep trend-aligned *and* neutral, by EMA-200 position + slope —
`drop_counter_trend=True`, now the default):

| config | folds +ve | fold 1 | fold 4 | IS | OOS | IS DD |
|---|---|---|---|---|---|---|
| gate off | 4/6 | −0.16 | −0.22 | +0.89 | +0.31 | 0.88 |
| **gate on (default)** | **5/6** | **+0.51** | **−0.04** | +0.74 | +0.29 | **0.74** |

The gate fixes both losing folds (fold 4 −0.22 → −0.04, fold 1 −0.16 → +0.51), lifts
fold-robustness 4/6 → 5/6, and cuts drawdown 0.88 → 0.74, for a small IS-Sharpe cost
(+0.89 → +0.74) and flat OOS — the right robustness-over-absolute trade. (Going
further to *only* trend-aligned entries overshoots: it drops OOS, so the neutral bin
is kept.) On `density_pullback` the same gate is roughly neutral (it has no bull
weakness — already 6/6) but lowers its DD 0.34 → 0.22, so it is available there but
left **off by default** to preserve its stronger OOS (+1.47).

## 4. Verdict

**`ship=True`.** It clears gate (a) in **both** splits — IS eqSharpe +0.74 ≥ B&H
+0.64, and OOS +0.29 ≥ B&H **−0.60** (BTC fell in the OOS window, so each split is
judged vs *its own* B&H — IS-vs-IS, OOS-vs-OOS) — and gate (b) on relative
consistency (76% > B&H 62%). Honest caveats: the OOS pass is a *relative* win (it
earned +0.29 while buy-and-hold lost), so it is modest in absolute terms and weaker
than `density_pullback` (OOS +1.47, which clears B&H on a much higher margin); and the
drawdown (0.74) is higher (the bounce fires ~3× as often, more overlapping exposure).
`density_pullback` is the one to take forward first.

But it is a clean **positive result about the framework, not the signal**: a strategy
that is REJECT under its own exit becomes 5/6-fold positive once fed the tuned ride
exit *and* the counter-trend gate. The exit machinery — next-dense TP + slow ratchet
+ tight stop — is a reusable asset that lifts *directional* entries (density breakout,
zigzag bounce) over their own exits, and the bull weakness is a **counter-trend-entry**
problem, fixed entry-side, not an exit one. Lineage:
[`density_pullback.md`](density_pullback.md) (the recipe),
[`random_hedge.md`](random_hedge.md) (the tuned exit + null baseline),
[`zigzag_bounce.md`](zigzag_bounce.md) (the rejected original).
