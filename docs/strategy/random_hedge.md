# Strategy: `random_hedge` (null-entry control)

A deliberate **null-entry baseline**, not a tradeable strategy. It opens a
**market-neutral long+short hedged pair on random bars** and exits each leg with
the project's best exit machinery (adaptive zs stop + next-dense target +
periodic ratchet). The point is to answer one question the whole research arc kept
raising — *is the edge in the exit, not the entry?* If random entries with smart
exits made money, the exit alone would be the edge. They do not.

| | |
|---|---|
| **Name** | `random_hedge` |
| **Class** | `src/strategy/random_hedge.py` → `RandomHedgeStrategy` |
| **Simulator** | `src/simulator/multi_simulator.py` → `MultiSimulator` (≤ `max_slots`) |
| **Reuses** | `ZsTpSl` (`src/exit/zs_tp_sl.py`), `_next_dense` (`density_multi_breakout`), `detect_peaks` (`src/indicators/zigzag.py`) |
| **Default config** | `entry_prob=0.01, seed=0, zigzag_size=12, sl_mult=1.0, recalc_bars=12, time_stop_bars=120, target_window=336, max_slots=50` |
| **Default timeframe** | **1h** |
| **Status** | **REJECT / control** — `ship=False`. Random entry + these exits is net-negative in-sample (IS equity Sharpe **−0.35**). The exit does not manufacture edge from noise. Kept as the **null baseline** to measure real entries against. See §5. |

---

## 1. Hypothesis (and why a hedged pair)

Every entry probe on this branch found the density breakout has **no directional
entry edge** (DR ≈ 0.50 at every horizon — see [`findings.md`](../findings.md));
the payoff lives in the exit / position management. `random_hedge` tests that
head-on by removing entry skill entirely.

The **hedged pair** (a long *and* a short on the same random bar) makes the entry
**perfectly market-neutral** — at fill the pair has zero directional expectation —
so any P&L can only come from the **asymmetric exits**. This is also a strong
correctness check: a hedged pair is zero-sum at entry, so a high win rate on *both*
legs is impossible without a bug (see §4).

## 2. Entry — random, hedged, seeded

On each bar (after warmup), with probability `entry_prob` (default 0.01), emit a
**pair** of signals — one LONG, one SHORT — at the bar close; both fill at the next
bar's open (two-bar rule). A seeded `numpy` RNG makes the backtest deterministic.
The entry carries **no skill** and is a placeholder: the intended use is to swap in
a better-priced entry later and measure the lift over this baseline.

## 3. Exit — zs stop + dense target + periodic ratchet

Per-leg `ExitConfig` plus a dynamic ratchet hook, whichever triggers first:

- **Stop (`sl_abs`)** — `sl_mult × band`, where `band` is the `ZsTpSl` EWA of recent
  zigzag leg sizes (adaptive volatility; high-side winsorised). Side-independent.
- **Take-profit (`tp_abs`)** — the next *pre-existing* dense node beyond entry in
  the trade direction (`_next_dense`, `target_window=336`), at least
  `target_min_dist_frac × band` away so it is not trivially close.
- **Ratchet (`dynamic_exit`)** — every `recalc_bars` (12) bars, if the leg is
  winning, trail the stop to `favorable_extreme ∓ band` (never loosened). This is
  the "recalculate the SL toward the winner side" rule.
- **Time stop** — `time_stop_bars` (120 ≈ 5 days) backstop.

## 4. Harness change + two bugs caught

**Harness:** the `MultiSimulator` filled one signal per bar, so "both sides at
once" was not expressible. Added `Strategy.precompute_multi() -> {ts: [Signal,…]}`
and a list-of-pendings fill loop (each leg fills while a slot is free, two-bar rule
preserved). Single-signal `precompute` is wrapped as one-element lists, so existing
strategies are unchanged — `density_multi_breakout` is byte-identical (608 trades,
eqSharpe 0.903 / 0.842).

**Two bugs the hedged-pair sanity check exposed** (the first run printed an
impossible eqSharpe **7.8 / 80 % win / PF 70**):

1. **Same-bar trailing look-ahead** — the ratchet recomputed the stop from the
   current bar's high, then the *same* bar's low triggered it, booking the bar's
   range as profit. Fixed: breach-check against the prior-bar stop **before**
   recomputing for future bars.
2. **`id(pos)` stale state (the real culprit)** — per-position ratchet state was
   keyed on `id(pos)`. CPython reuses freed object addresses, so a new position
   inherited a *dead* position's ratcheted stop and "exited" immediately at a
   stale favorable level (fake +60 %-in-1-bar wins at a constant price). Fixed by
   keying on `(entry_idx, side)`, which is unique per position and cleared each run.

> **Lesson:** never key per-object state on `id()` across object lifetimes; and a
> control whose result looks too good is doing its job — a hedged pair *cannot*
> win on both legs.

## 5. Results (bug-free, GMO 1h ~5y)

### Aggregate

| metric | in-sample | OOS |
|---|---|---|
| **equity Sharpe** | **−0.346** | +1.155 |
| total return | −0.51 | +0.27 |
| **DR** (win rate) | **0.370** | 0.395 |
| profit factor | 0.94 | 1.19 |
| max DD | 0.70 | 0.16 |
| trades | 710 | 152 |

vs B&H annualised Sharpe **+0.64**. Exit mix (all): trail 460 · stop 272 · target
109 · time 21. **`ship=False`.** DR ≈ 0.37–0.40 is sub-coin-flip — expected for a
trend-ride payoff (few big winners), but here the winners do **not** cover the
losers in-sample (PF 0.94).

### Per-period (frequency-adaptive: ~175 trades/yr → year / quarter, not week)

**In-sample, by year** — `DR | total_return | max_DD`:

| year | n | DR | total_return | max_DD |
|---|---|---|---|---|
| 2021 | 119 | 0.370 | +0.0144 | 0.295 |
| 2022 | 167 | 0.371 | **−0.3961** | 0.403 |
| 2023 | 162 | 0.346 | −0.1219 | 0.221 |
| 2024 | 204 | 0.382 | +0.0253 | 0.253 |
| 2025 | 58 | 0.397 | −0.0321 | 0.180 |

→ IS consistency: **2/5 years (40 %)** and **7/17 quarters (41 %)** non-negative —
far below the ≥ 80 % ship gate. The loss is concentrated in the 2022–23 bear
(−0.40 / −0.12); the hedged pair bleeds the stop+cost in trendless/whipsaw years.

**OOS, by year:**

| year | n | DR | total_return | max_DD |
|---|---|---|---|---|
| 2025 | 102 | 0.392 | +0.1392 | 0.150 |
| 2026 | 50 | 0.400 | +0.1260 | 0.161 |

→ OOS consistency: 2/2 years, **3/5 quarters (60 %)**.

Random entry + smart exits is **net-negative in-sample and fails the consistency
gate badly** (40 %). The exit machinery shapes the payoff distribution but **cannot
create edge from a random entry**. The negative-IS / positive-OOS split (and the
much smaller OOS sample) is the regime-artifact tell seen elsewhere on this branch
— a single split disagreeing in sign — not a stable edge.

## 6. Conclusion & use

This **tempers** the "the edge is in the exit" framing: the exit is necessary but
not sufficient — `density_multi_breakout` needs *both* its selective entry and its
dense-aware exit. `random_hedge`'s real value is as a **null baseline**: plug a
candidate entry into this exact exit framework and judge it by **lift over random**
(a stronger test than absolute Sharpe). Research lineage / sibling negatives:
[`findings.md`](../findings.md), [`density_multi_breakout.md`](density_multi_breakout.md).
