"""Stage-0 probe: Kojiro (Turtle) **half-rise trailing stop** vs the shipped
density_breakout ride exit, on density_breakout's OWN in-sample fires.

WHY THIS PROBE (sign-debate 2026-06-28 on docs/books/kojiro.md):
  The book's thesis is that the entry only locates the edge; the year's P&L is
  decided by money/position management — i.e. the EXIT. This repo's own findings
  agree: the breakout entry is a coin-flip three independent ways (HH/HL swing
  breakout net-neg; density entry-horizon DR <=0.50 at every horizon; volume-wall
  breakouts DR<0.50), and density_breakout's docstring records "the edge is pure
  payoff asymmetry at the ride horizon (exit/position-mgmt)". So the ONE Kojiro
  primitive with a non-dead prior is the EXIT, and the half-rise trail (raise the
  stop by HALF of each advance, p.62-64/p.104) is genuinely untested here.

  The debate's Critic killed the Proposer's first design (test on a fresh Donchian
  entry): (a) the slot-skipping portfolio view makes "same fires" FALSE across exit
  arms (different exit bars -> different skip set -> different trade population), and
  (b) a Donchian path distribution does not transfer to the density book the result
  would deploy on. The Judge accepted the Critic's reformulation, and added the
  decisive prior: density_breakout SHIPS WITH NO TRAIL (`trail_atr_mult=None`) —
  its own 5y GMO 1h tuning found "any trail hurts (it clips the trend winners a ride
  exists to capture); removing it lifted both IS and OOS Sharpe." The half-rise
  ratchet is a (looser) member of that rejected trailing family, so the prior is
  NEGATIVE — but the half-rise mechanic itself is untested and is looser than the
  2xATR trail that was rejected, so one cheap Stage-0 read is warranted before
  closing it out.

DESIGN (per the Judge's accepted reformulation):
  - Entry set = density_breakout's OWN fires (the deployment book), built with the
    SHIPPED config (DensityBreakoutSign defaults), IN-SAMPLE ONLY.
  - Walk EVERY fire INDEPENDENTLY (the genuinely-paired entry-quality view; never
    the slot-skipping portfolio view for the gate). Same entries, same fills across
    all arms -> the ONLY thing that varies is the exit (one knob, eval_criteria 6.6).
  - Two-bar fill at open[f+1] (repo rule). Fill price + far-edge structural stop
    distance (`sl_abs`) computed EXACTLY as DensityBreakoutStrategy.on_bar does, so
    the initial entry RISK is identical across arms.
  - Exit arm A (BASELINE = shipped): far-edge structural `sl_abs` + 120-bar time
    stop, NO trail. evaluate_exit, SL-before-TP pessimistic.
  - Exit arm B (PROPOSED): same initial `sl_abs` hard stop, PLUS the Kojiro
    half-rise ratchet on top (N = ATR at entry): rush-to-breakeven in 0.5N steps
    while the stop is below entry, then trail at half-pace (raise 0.5N per 1.0N
    advance). Never lowers the stop. Same 120-bar time stop.
  - Exit arm C (CONTEXT, the rejected family): same `sl_abs` + a 2xATR trail —
    the trailing variant density tuning already rejected, for calibration.

GATE (pre-registered; do NOT change after running). On GMO_BTC_JPY 1h IN-SAMPLE,
paired entry-quality view, treat the half-rise exit as worth a real density A/B
ONLY if arm B clears BOTH:
  (G1) DeltaSharpe(B - A) >= +0.05  (the project's pre-registered A/B materiality), AND
  (G2) the 95% paired-bootstrap CI lower bound on DeltaSharpe(B - A) > 0.
FALSIFIER: if DeltaSharpe(B - A) <= 0 OR the CI lower bound <= 0, the half-rise is
  just another member of the trailing family density_breakout already found harmful
  -> REJECT; the Kojiro exit is closed out at Stage-0 (mirroring how the entry and
  reversal sides of the book-mining arc were closed).
OOS HYGIENE: in-sample only; the lockbox OOS is NEVER touched. A pass authorizes a
  human-run density_pullback/density_breakout exit A/B via the cycle walk-forward
  (equity Sharpe vs B&H both splits + quarter consistency) — OUTSIDE this probe.

Read-only: writes no DB, mutates no production sign/strategy/exit code. Unregistered.
Run: uv run --env-file .env.bt python -m src.backtest.analysis.kojiro_halfrise_trail_stage0
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from src.backtest.sign_benchmark import split_lockbox
from src.core.types import Bar, ExitConfig, Side, Timeframe
from src.data.cache import load_cache
from src.exit.rules import OpenPosition, evaluate_exit
from src.indicators import atr
from src.signs.density_breakout import DensityBreakoutSign

# --- config (shipped density_breakout defaults) -------------------------------
ATR_PERIOD = 14
SL_BUFFER = 0.10            # DensityBreakoutStrategy default far-edge buffer
MAX_BARS = 120             # shipped time stop (~5 days on 1h)
FEE_RATE = float(os.getenv("FEE", "0.0002"))   # per side; 2 bp/side calm estimate
LOT = 0.001
TRAIL_C_ATR = 2.0          # arm-C context trail (the rejected family)
N_BOOT = int(os.getenv("KJ_BOOT", "2000"))
_TF = {"1m": Timeframe.M1, "5m": Timeframe.M5, "15m": Timeframe.M15, "1h": Timeframe.H1}


@dataclass(frozen=True, slots=True)
class Fire:
    """A density_breakout entry candidate with its far-edge structural stop."""

    bar: int          # positional index of the signal (breakout) bar
    side: Side
    price: float      # signal-bar close (the strategy's stop-distance anchor)
    sl_abs: float     # absolute far-edge structural stop DISTANCE (price units)


def _sl_abs(side: Side, price: float, near: float, far: float) -> float:
    """Far-edge structural stop distance, identical to DensityBreakoutStrategy.on_bar."""
    band_h = abs(near - far)
    if side is Side.LONG:
        sl = (price - far) + SL_BUFFER * band_h
    else:
        sl = (far - price) + SL_BUFFER * band_h
    return max(sl, SL_BUFFER * band_h)


def build_fires(df, atrs: list[float]) -> list[Fire]:
    """Density_breakout fires (shipped config) mapped to positional indices."""
    sign = DensityBreakoutSign()  # shipped defaults
    pos_of = {ts: i for i, ts in enumerate(df.index)}
    out: list[Fire] = []
    for fe in sign.detect(df):
        i = pos_of.get(fe.fired_at)
        if i is None or fe.ref_price is None or fe.ref2_price is None:
            continue
        if i + 1 >= len(atrs) or atrs[i] <= 0.0:
            continue
        out.append(Fire(i, fe.side, float(fe.price),
                        _sl_abs(fe.side, float(fe.price), fe.ref_price, fe.ref2_price)))
    return out


def _entry(opens, highs, lows, fire: Fire) -> float | None:
    """Two-bar fill at open[f+1]."""
    f = fire.bar
    if f + 1 >= len(opens):
        return None
    return opens[f + 1]


def walk_baseline(opens, highs, lows, closes, fire: Fire, trail_mult: float | None) -> float | None:
    """Arm A (trail_mult=None) / arm C (trail_mult set): shipped evaluate_exit walk.

    Far-edge structural sl_abs + optional ATR trail + 120-bar time stop, walked
    bar-by-bar from open[f+2], SL/trail-before-TP pessimistic (repo convention).
    """
    entry = _entry(opens, highs, lows, fire)
    if entry is None:
        return None
    f = fire.bar
    entry_atr = _ATRS[fire.bar]
    cfg = ExitConfig(sl_abs=fire.sl_abs, trail_atr_mult=trail_mult, time_stop_bars=MAX_BARS)
    pos = OpenPosition(side=fire.side, entry_price=entry, entry_atr=entry_atr)
    exit_price = closes[-1]
    for j in range(f + 2, len(opens)):
        bar = Bar(timestamp=None, open=opens[j], high=highs[j], low=lows[j], close=closes[j], volume=0.0)  # type: ignore[arg-type]
        res = evaluate_exit(pos, bar, cfg)
        if res is not None:
            exit_price = res[1]
            break
        pos.bars_held += 1
    return fire.side.sign * (exit_price - entry) / entry - 2.0 * FEE_RATE


def walk_halfrise(opens, highs, lows, closes, fire: Fire) -> float | None:
    """Arm B: same initial far-edge structural stop + the Kojiro half-rise ratchet.

    N = ATR at entry. Long (mirror for short):
      - initial hard stop = entry - sl_abs (identical to arm A's entry risk).
      - rush-to-breakeven: while stop < entry and fav_ext >= last_raise + 0.5N:
            stop += 0.5N ; last_raise += 0.5N
      - half-pace trail: while stop >= entry and fav_ext >= last_raise + 1.0N:
            stop += 0.5N ; last_raise += 1.0N
      - stop never lowers. Same intra-bar convention as evaluate_exit (update the
        favourable extreme, raise the stop, THEN test the stop) + 120-bar time stop.
    """
    entry = _entry(opens, highs, lows, fire)
    if entry is None:
        return None
    f = fire.bar
    N = _ATRS[fire.bar]
    if N <= 0.0:
        return None
    long = fire.side is Side.LONG
    stop = entry - fire.sl_abs if long else entry + fire.sl_abs
    last_raise = entry
    fav = entry
    exit_price = closes[-1]
    held = 0
    for j in range(f + 2, len(opens)):
        hi, lo, cl = highs[j], lows[j], closes[j]
        # 1. update favourable extreme, then raise the ratchet (evaluate_exit order).
        if long:
            fav = max(fav, hi)
            while True:
                if stop < entry:
                    if fav >= last_raise + 0.5 * N:
                        stop += 0.5 * N
                        last_raise += 0.5 * N
                        continue
                else:
                    if fav >= last_raise + 1.0 * N:
                        stop += 0.5 * N
                        last_raise += 1.0 * N
                        continue
                break
            if lo <= stop:                       # stop hit (pessimistic)
                exit_price = stop
                break
        else:
            fav = min(fav, lo)
            while True:
                if stop > entry:
                    if fav <= last_raise - 0.5 * N:
                        stop -= 0.5 * N
                        last_raise -= 0.5 * N
                        continue
                else:
                    if fav <= last_raise - 1.0 * N:
                        stop -= 0.5 * N
                        last_raise -= 1.0 * N
                        continue
                break
            if hi >= stop:
                exit_price = stop
                break
        # 2. time stop.
        if held >= MAX_BARS:
            exit_price = cl
            break
        held += 1
    return fire.side.sign * (exit_price - entry) / entry - 2.0 * FEE_RATE


def _stats(rets: np.ndarray) -> tuple[int, float, float, float, float]:
    """(n, sum, sharpe, win_frac, mean_r)."""
    if rets.size == 0:
        return 0, 0.0, 0.0, 0.0, 0.0
    std = float(rets.std(ddof=1)) if rets.size > 1 else 0.0
    sharpe = float(rets.mean() / std) if std > 0.0 else 0.0
    return rets.size, float(rets.sum()), sharpe, float((rets > 0.0).mean()), float(rets.mean())


def _sharpe(a: np.ndarray) -> float:
    s = float(a.std(ddof=1)) if a.size > 1 else 0.0
    return float(a.mean() / s) if s > 0.0 else 0.0


def main() -> None:
    global _ATRS
    tf = _TF[os.getenv("KJ_TF", "1h")]
    product = os.getenv("KJ_PRODUCT", "GMO_BTC_JPY")

    cache = load_cache(tf, product=product)
    is_b, _oos = split_lockbox(cache.bars)  # IN-SAMPLE ONLY — OOS reserved (hygiene)
    df = cache.to_frame().loc[: is_b[-1].timestamp]
    opens = df["open"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    closes = df["close"].tolist()
    _ATRS = [float(v) for v in atr(df, ATR_PERIOD).to_numpy()]

    print(f"{product} {tf.value} IN-SAMPLE: {len(df)} bars  {df.index[0]} -> {df.index[-1]}")
    fires = build_fires(df, _ATRS)
    nl = sum(1 for f in fires if f.side is Side.LONG)
    print(f"density_breakout fires (shipped config): {len(fires)}  (long={nl} short={len(fires) - nl})\n")

    # Paired entry-quality view: walk EVERY fire under each arm (same fills).
    arms = {
        "A_shipped(no-trail)": lambda fr: walk_baseline(opens, highs, lows, closes, fr, None),
        "B_halfrise":          lambda fr: walk_halfrise(opens, highs, lows, closes, fr),
        "C_2xATRtrail":        lambda fr: walk_baseline(opens, highs, lows, closes, fr, TRAIL_C_ATR),
    }
    # Keep only fires that produce a fill under ALL arms (true paired set).
    paired: dict[str, list[float]] = {k: [] for k in arms}
    for fr in fires:
        rs = {k: fn(fr) for k, fn in arms.items()}
        if any(v is None for v in rs.values()):
            continue
        for k, v in rs.items():
            paired[k].append(v)  # type: ignore[arg-type]

    px0 = closes[0]
    print(f"{'arm':22} {'n':>5} {'sum_ret':>9} {'sharpe':>8} {'win':>6} {'mean_r':>9} {'net~JPY':>9}")
    print("-" * 72)
    vecs: dict[str, np.ndarray] = {}
    for k in arms:
        a = np.asarray(paired[k], dtype=float)
        vecs[k] = a
        n, s, sh, w, mr = _stats(a)
        net = sum(rr * LOT * px0 for rr in a)
        print(f"{k:22} {n:>5} {s:>9.4f} {sh:>8.3f} {w:>6.2f} {mr:>9.5f} {net:>9.0f}")

    A, B = vecs["A_shipped(no-trail)"], vecs["B_halfrise"]
    n = A.size
    d_sharpe = _sharpe(B) - _sharpe(A)

    # Paired bootstrap CI on DeltaSharpe(B - A): resample fire indices, recompute
    # both arms' Sharpe on the SAME resampled indices (preserves pairing).
    rng = np.random.default_rng(0)
    boots = np.empty(N_BOOT, dtype=float)
    for i in range(N_BOOT):
        idx = rng.integers(0, n, size=n)
        boots[i] = _sharpe(B[idx]) - _sharpe(A[idx])
    lo, hi = float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))

    print(f"\nPAIRED exit A/B (entry-quality, n={n}):")
    print(f"  DeltaSharpe(B_halfrise - A_shipped) = {d_sharpe:+.4f}")
    print(f"  95% paired-bootstrap CI            = [{lo:+.4f}, {hi:+.4f}]  ({N_BOOT} boots)")
    print(f"  context: C_2xATRtrail - A_shipped  = {_sharpe(vecs['C_2xATRtrail']) - _sharpe(A):+.4f}")

    g1 = d_sharpe >= 0.05
    g2 = lo > 0.0
    print("\nGATE (pre-registered): G1 DeltaSharpe>=+0.05 ; G2 bootstrap CI lower bound>0.")
    print(f"  G1 {'PASS' if g1 else 'FAIL'}   G2 {'PASS' if g2 else 'FAIL'}  ->  "
          f"{'WORTH A REAL DENSITY A/B' if (g1 and g2) else 'REJECT (half-rise adds nothing over the shipped no-trail ride)'}")
    print("FALSIFIER: DeltaSharpe<=0 OR CI lower bound<=0 -> Kojiro exit closed out at Stage-0.")
    print("OOS reserved: lockbox NOT touched; a pass earns a human-run cycle walk-forward A/B only.")


if __name__ == "__main__":
    main()
