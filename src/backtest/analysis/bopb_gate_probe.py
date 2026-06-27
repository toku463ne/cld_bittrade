"""Stage-0 probe: Brooks **breakout-pullback (BOPB)** gate on `density_breakout` (1h BTC).

`density_breakout` enters the instant price closes out of the dense band. Brooks'
highest-value harvest of a breakout is NOT the breakout bar — it is the
**breakout-pullback / "failed failure"**: let price retest the broken edge, and
enter only when the retest holds and the move *resumes* (a false breakout that
itself fails). The test that turns into a reversal bar never triggers the stop-
entry, so the gate self-selects away the fakeouts.

This probe layers that gate on the SAME breakouts the production sign already
finds (no new detector, same exit), so it isolates ONE question: does requiring a
retest-and-resume beat taking every breakout at the close?

GATE MECHANIC (causal; reuses src/signs/density_breakout.DensityBreakoutSign):
  For each breakout at t0 (LONG above the broken edge `near`, far edge `far`):
    1. Retest — scan (t0, t0+RETEST_W]: the broken edge should act as support,
       so wait for a bar whose low dips back to/through `near` (long). If instead
       a bar CLOSES more than FAIL_FRAC band-heights back inside the band first,
       the breakout failed -> skip (not a BOPB).
    2. Resume — from the retest bar j, place a stop-entry at its extreme high[j];
       scan (j, j+RESUME_W]: fill on the first bar trading through it,
       entry = max(open, high[j]). (Mirror for shorts.)
    A breakout that never retests within RETEST_W = "ran away" -> the gate SKIPS
    it. Tracking those is the whole risk (Brooks: the strongest trends don't pull
    back), so we measure the ran-away bucket explicitly for the falsifier.
EXIT is IDENTICAL to the production strategy: structural stop beyond the OPPOSITE
  band edge (+SL_BUFFER) + time stop, no trail (the strategy found any trail hurts).
  Computed from the ACTUAL entry price in both arms, so only entry differs.

THREE arms (entry-quality + portfolio flat-only views), IN-SAMPLE ONLY:
  baseline — every breakout, entered at open[t0+1] (the production behaviour).
  bopb     — only breakouts that retest-and-resume, entered at the resume.
  ran_away — the breakouts the gate DROPS (no retest), scored at baseline timing.

NULL (selection control): a random equal-size subset of the baseline breakouts
  (same count as `bopb`, HL_SEEDS seeds, portfolio view). Asks whether the retest
  SELECTION beats randomly dropping the same number of breakouts — if bopb only
  matches this null, the retest filter adds nothing.

PRE-REGISTERED ACCEPT GATE (written before running; do not change after):
  On GMO_BTC_JPY 1h IN-SAMPLE, adopt the BOPB gate on density_breakout ONLY if its
  PORTFOLIO view clears ALL of:
    (G1) per-trade Sharpe >= baseline portfolio Sharpe + 0.05 AND net Σret >= baseline, AND
    (G2) bopb portfolio Sharpe beats the random equal-size-subset null mean by
         >= +1.0 null-sd (lift z >= 1.0), AND
    (G3) n_bopb >= 30 portfolio fills.
FALSIFIER: if the ran_away (dropped) bucket's mean return >= the bopb bucket's mean
  return, the gate is discarding the winners (Brooks "best trends don't pull back")
  -> REJECT the gate; report explicitly.
OOS HYGIENE: in-sample only; the lockbox OOS is never touched (run the cycle
  walk-forward once, only if this gate passes).

Read-only: writes no DB, mutates no production sign/strategy code. Unregistered.
Run: uv run --env-file .env.bt python -m src.backtest.analysis.bopb_gate_probe
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.backtest.sign_benchmark import split_lockbox
from src.core.types import Bar, ExitConfig, Side
from src.data.cache import load_cache
from src.exit.rules import OpenPosition, evaluate_exit
from src.signs.density_breakout import DensityBreakoutSign

# --- config ------------------------------------------------------------------
RETEST_W = int(os.getenv("BOPB_RETEST_W", "24"))   # bars to wait for a retest (~1 day)
RESUME_W = int(os.getenv("BOPB_RESUME_W", "12"))   # bars to wait for the resume after retest
FAIL_FRAC = float(os.getenv("BOPB_FAIL_FRAC", "0.5"))  # close-back-into-band frac that voids it
SL_BUFFER = 0.10          # structural stop this frac of band height beyond the far edge
MAX_BARS = 120            # time stop (~5 days on 1h) — matches the strategy default
FEE_RATE = float(os.getenv("FEE", "0.0002"))
LOT = 0.001
SEEDS = int(os.getenv("HL_SEEDS", "40"))


@dataclass(frozen=True, slots=True)
class Entry:
    """A resolved entry: the bar filled and the price, plus the band edges for the stop."""

    bar: int
    price: float
    side: Side
    far: float
    band_h: float


def _structural_sl(side: Side, entry: float, far: float, band_h: float) -> float:
    """Distance to the structural stop beyond the OPPOSITE band edge (the strategy rule)."""
    raw = (entry - far) if side is Side.LONG else (far - entry)
    return max(raw + SL_BUFFER * band_h, SL_BUFFER * band_h)


def walk(
    opens, highs, lows, closes, e: Entry,
) -> tuple[float, int] | None:
    """Walk the structural-stop + time-stop exit from ``e.bar+1``; net return + exit idx."""
    if e.bar + 1 >= len(opens):
        return None
    cfg = ExitConfig(sl_abs=_structural_sl(e.side, e.price, e.far, e.band_h), time_stop_bars=MAX_BARS)
    pos = OpenPosition(side=e.side, entry_price=e.price, entry_atr=0.0)
    exit_price = closes[-1]
    exit_idx = len(opens) - 1
    for j in range(e.bar + 1, len(opens)):
        bar = Bar(timestamp=None, open=opens[j], high=highs[j], low=lows[j], close=closes[j], volume=0.0)  # type: ignore[arg-type]
        res = evaluate_exit(pos, bar, cfg)
        if res is not None:
            exit_price, exit_idx = res[1], j
            break
        pos.bars_held += 1
    signed = e.side.sign * (exit_price - e.price) / e.price
    return signed - 2.0 * FEE_RATE, exit_idx


def baseline_entry(opens, t0: int, side: Side, far: float, band_h: float) -> Entry | None:
    """Production entry: fill at open[t0+1]."""
    if t0 + 1 >= len(opens):
        return None
    return Entry(t0 + 1, opens[t0 + 1], side, far, band_h)


def bopb_entry(
    opens, highs, lows, closes, t0: int, side: Side, near: float, far: float, band_h: float
) -> Entry | None:
    """Resolve the BOPB retest-and-resume entry, or None if it never sets up."""
    n = len(opens)
    long = side is Side.LONG
    # 1. Find the retest bar j: edge reclaimed as support/resistance, not a deep failure.
    j = None
    for c in range(t0 + 1, min(t0 + 1 + RETEST_W, n)):
        if long:
            if closes[c] < near - FAIL_FRAC * band_h:   # collapsed back into band -> failed
                return None
            if lows[c] <= near:                          # dipped back to the broken edge
                j = c
                break
        else:
            if closes[c] > near + FAIL_FRAC * band_h:
                return None
            if highs[c] >= near:
                j = c
                break
    if j is None:
        return None  # ran away (no pullback) — gate skips
    # 2. Resume: stop-entry beyond the retest bar's extreme.
    trig = highs[j] if long else lows[j]
    for k in range(j + 1, min(j + 1 + RESUME_W, n)):
        if long:
            if closes[k] < near - FAIL_FRAC * band_h:
                return None
            if highs[k] >= trig:
                return Entry(k, max(opens[k], trig), side, far, band_h)
        else:
            if closes[k] > near + FAIL_FRAC * band_h:
                return None
            if lows[k] <= trig:
                return Entry(k, min(opens[k], trig), side, far, band_h)
    return None  # retested but never resumed


def _stats(rets: list[float]) -> tuple[int, float, float, float]:
    if not rets:
        return 0, 0.0, 0.0, 0.0
    a = np.asarray(rets, dtype=float)
    std = float(a.std(ddof=1)) if a.size > 1 else 0.0
    sharpe = float(a.mean() / std) if std > 0.0 else 0.0
    return a.size, float(a.sum()), sharpe, float((a > 0.0).mean())


def _portfolio(opens, highs, lows, closes, entries: list[Entry]) -> list[float]:
    """Flat-only single-position walk over time-ordered entries (skip while busy)."""
    out: list[float] = []
    free_until = -1
    for e in sorted(entries, key=lambda x: x.bar):
        if e.bar <= free_until:
            continue
        r = walk(opens, highs, lows, closes, e)
        if r is None:
            continue
        out.append(r[0])
        free_until = r[1]
    return out


def main() -> None:
    product = os.getenv("HL_PRODUCT", "GMO_BTC_JPY")
    from src.core.types import Timeframe

    tf = Timeframe.H1
    bars = load_cache(tf, product=product).bars
    is_b, _oos = split_lockbox(bars)  # IN-SAMPLE ONLY — OOS reserved (hygiene)
    df = load_cache(tf, product=product).to_frame().loc[: is_b[-1].timestamp]
    opens = df["open"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    closes = df["close"].tolist()
    pos_of = {ts: i for i, ts in enumerate(df.index)}
    print(f"{product} 1h IN-SAMPLE: {len(df)} bars  {df.index[0]} -> {df.index[-1]}")

    sign = DensityBreakoutSign()  # production defaults (window168/bins48/cov0.70/box2%)
    fires = sign.detect(df)
    print(f"density_breakout fires: {len(fires)}  "
          f"(retest_w={RETEST_W} resume_w={RESUME_W} fail_frac={FAIL_FRAC}, "
          f"exit=structural far-edge + {MAX_BARS}b time stop)\n")

    base: list[Entry] = []
    bopb: list[Entry] = []
    ran_away: list[Entry] = []   # dropped by the gate, scored at baseline timing
    for f in fires:
        t0 = pos_of.get(pd.Timestamp(f.fired_at))
        if t0 is None:
            continue
        near, far = f.ref_price, f.ref2_price
        if near is None or far is None:
            continue
        band_h = abs(near - far)
        if band_h <= 0:
            continue
        be = baseline_entry(opens, t0, f.side, far, band_h)
        if be is not None:
            base.append(be)
        ge = bopb_entry(opens, highs, lows, closes, t0, f.side, near, far, band_h)
        if ge is not None:
            bopb.append(ge)
        elif be is not None:
            ran_away.append(be)

    print(f"resolved: baseline={len(base)}  bopb={len(bopb)}  dropped(ran_away/failed)={len(ran_away)}\n")

    print(f"{'arm':9} {'view':11} {'n':>5} {'sum_ret':>9} {'sharpe':>8} {'win':>6}")
    print("-" * 52)
    pf_sharpe: dict[str, float] = {}
    pf_sum: dict[str, float] = {}
    pf_n: dict[str, int] = {}
    mean_eq: dict[str, float] = {}
    for name, entries in (("baseline", base), ("bopb", bopb), ("ran_away", ran_away)):
        eq = [r[0] for e in entries if (r := walk(opens, highs, lows, closes, e)) is not None]
        n, s, sh, w = _stats(eq)
        mean_eq[name] = (s / n) if n else 0.0
        print(f"{name:9} {'entry-qual':11} {n:>5} {s:>9.4f} {sh:>8.3f} {w:>6.2f}")
        pf = _portfolio(opens, highs, lows, closes, entries)
        n, s, sh, w = _stats(pf)
        net = sum(rr * LOT * closes[0] for rr in pf)
        pf_sharpe[name], pf_sum[name], pf_n[name] = sh, s, n
        print(f"{name:9} {'portfolio':11} {n:>5} {s:>9.4f} {sh:>8.3f} {w:>6.2f}   net~{net:.0f}JPY")

    # NULL: random equal-size subset of baseline breakouts (selection control).
    nb = pf_n["bopb"]
    base_pf_entries = base
    sharpes = []
    if 0 < nb <= len(base_pf_entries):
        for s in range(SEEDS):
            rng = np.random.default_rng(s)
            pick = [base_pf_entries[i] for i in rng.choice(len(base_pf_entries), size=nb, replace=False)]
            _, _, sh, _ = _stats(_portfolio(opens, highs, lows, closes, pick))
            sharpes.append(sh)
    null_mean = float(np.mean(sharpes)) if sharpes else 0.0
    null_sd = float(np.std(sharpes)) if sharpes else 0.0
    lift_z = (pf_sharpe["bopb"] - null_mean) / null_sd if null_sd > 0 else 0.0

    print(f"\nrandom equal-size-subset null ({SEEDS} seeds, portfolio): "
          f"null_sh {null_mean:+.3f} (sd {null_sd:.3f})  ->  bopb lift_z {lift_z:+.2f}")
    print(f"\nGATE: G1 bopb_pf_sh ({pf_sharpe['bopb']:+.3f}) >= baseline_pf_sh "
          f"({pf_sharpe['baseline']:+.3f})+0.05 AND bopb_sum ({pf_sum['bopb']:+.3f}) "
          f">= baseline_sum ({pf_sum['baseline']:+.3f}) ; G2 lift_z>=+1.0 ; G3 n_bopb>=30.")
    print(f"FALSIFIER: ran_away mean_eq ({mean_eq['ran_away']:+.5f}) vs bopb mean_eq "
          f"({mean_eq['bopb']:+.5f}) — if ran_away>=bopb, the gate drops the winners -> REJECT.")
    print("OOS reserved: do NOT touch the lockbox for keep/drop (run cycle WF once if gate passes).")


if __name__ == "__main__":
    main()
