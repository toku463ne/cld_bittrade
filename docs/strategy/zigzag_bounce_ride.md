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
| **Default config** | bounce defaults (`size=10, wall_match=True, wall_window=120, reject_past_peak=True`) + `pullback=False` + tuned exit (`sl_mult=0.75, recalc_bars=48, time_stop_bars=120`) |
| **Default timeframe** | **1h** |
| **Status** | `ship=False` — but the exit swap **rescues** the signal from REJECT to IS eqSharpe **+0.89 / OOS +0.31** (4/6 walk-forward folds positive). The bounce direction carries IS edge; OOS is positive but below B&H +0.64, and it gets run over in strong bulls. See §2. |

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

**Walk-forward (fixed config, 6 folds): positive in 4/6.** Beats buy-and-hold in the
down/sideways folds (fold 0 +1.76 vs B&H −0.22; fold 5 +1.74 vs −0.94); the two
misses are a bad-for-everyone fold (fold 1, B&H −1.03) and a **strong-bull fold
(fold 4, −0.22 vs B&H +1.94)** where the counter-trend bounces get run over — the
characteristic weakness of a mean-reversion-flavoured entry.

## 3. Verdict

`ship=False`: OOS +0.31 is below B&H +0.64, fold 4 goes negative in a bull, and the
drawdown (IS 0.88) is higher than the density family (the bounce fires ~3× as often,
1307 vs ~450 IS trades, so more overlapping exposure). It is also weaker than its
siblings — `density_pullback` (IS +1.27 / OOS +1.47) and the tuned
`random_hedge_volfilter` (+0.90 / +1.02), both 4/6+ folds.

But it is a clean **positive result about the framework, not the signal**: a strategy
that is REJECT under its own exit becomes 4/6-fold positive when fed the tuned ride
exit. The exit machinery — next-dense TP + slow ratchet + tight stop — is a reusable
asset that lifts *directional* entries (density breakout, zigzag bounce) over their
own exits; the remaining gap to ship is bull-market behaviour and drawdown, an
exit/sizing problem, not an entry one. Lineage:
[`density_pullback.md`](density_pullback.md) (the recipe),
[`random_hedge.md`](random_hedge.md) (the tuned exit + null baseline),
[`zigzag_bounce.md`](zigzag_bounce.md) (the rejected original).
