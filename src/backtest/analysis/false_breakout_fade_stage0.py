"""Stage-0: Brooks **false-breakout / trapped-trader FADE** on 1h BTC.

The single most-emphasized edge in docs/books/priceaction.md (Al Brooks) is *"most
breakouts are false; the failure is the trade"* (guidelines 8-10, 33-34; buckets f
& d). Every SHIPPED book here rides breakouts/continuation/vol-expansion that HOLD
(density_breakout, density_pullback, vol_expansion_ride). This probe trades the
literal COMPLEMENT set: breakouts that FAIL back through the broken level -> fade.
That makes it the most mechanistically ISOLATED Brooks family still unbuilt:

  - It is NOT the high2_low2 with-trend continuation (BUILT & KILLED, below null).
  - It is NOT the BOPB breakout-resume gate (BUILT & KILLED).
  - It is NOT the VPA climax/exhaustion-wick reversal (BUILT & KILLED 2026-06-28) --
    that fires on a volume+wick EXHAUSTION bar; this fires on a structural RECLAIM of
    a swing level (a trap), no volume term.
  - It is NOT stale-box-fade (KILLED) -- that faded breakouts that simply ran out of
    steam; this requires price to actually REVERSE BACK THROUGH the broken level.

A profitable fade book would be the portfolio's first genuine REVERSAL diversifier
(all live books are long-biased trend riders); the prior is brutal (every fade/
reversal mechanism in this repo has died), so the bar is the paired regime-matched
null, same as climax_reversal_stage0 / high2_low2.

MECHANISM (causal, no fitted line / no DOF beyond N,K):
  Up-breakout at bar b: high[b] > level_up = max(high[b-N : b]) (new N-bar high).
  FALSE breakout (short fade) = within K bars of b, a bar t closes back BELOW
    level_up (the broken resistance becomes the trap). Fire SHORT at t; stop-entry
    sell-stop 1 tick below low[t] (Brooks); ATR-trail ride down. Mirror: down-
    breakout that closes back ABOVE level_dn within K -> fade LONG.
  One pending breakout tracked per side; a fade (or a clean K-bar hold) resets it.

ENTRY/EXIT: two-bar fill at open[t+1] with the faithful stop-entry (reclaim bar's
  extreme must trade through, else expire); ATR trailing-stop ride -- identical
  mechanics to high2_low2_probe.walk (reused verbatim).

NULL (breakout-matched, the honest floor for this SELECTION sign): for each arm draw
  the SAME number of long/short fades at RANDOM bars from the matching POST-BREAKOUT
  pool (short pool = every bar within K bars after an up-breakout; long pool = mirror),
  same direction, same stop-entry, same exit, SEEDS seeds. This holds the "fade after
  a breakout" exposure constant and asks ONLY whether the RECLAIM selection (closed
  back through the level) beats "fade at a random post-breakout bar". If the sign only
  matches this null, the reclaim adds nothing over the breakout context alone (the
  high2_low2 / sweep_reclaim / climax failure mode).

PRE-REGISTERED ACCEPT GATE (written before running; do not change after):
  On GMO_BTC_JPY 1h IN-SAMPLE, treat an arm as a candidate sign ONLY if its PORTFOLIO
  view clears ALL of:
    (G1) net sum_ret > 0 AND per-trade Sharpe >= +0.10, AND
    (G2) Sharpe beats the breakout-matched random null mean by >= +1.0 sd (lift_z>=1.0),
    (G3) n >= 30 portfolio fills (else too thin to read -- flag, do not conclude).
FALSIFIER: if lift_z <= 0 (Sharpe <= breakout-matched null), the reclaim selection
  adds nothing over "fade any post-breakout bar" -> REJECT the Brooks false-breakout
  fade, confirming the dead-reversal/fade prior on 1h BTC.
OOS HYGIENE: in-sample only; the lockbox OOS is never touched.

Read-only, unregistered. Run:
  uv run --env-file .env.bt python -m src.backtest.analysis.false_breakout_fade_stage0
"""

from __future__ import annotations

import os

import numpy as np

from src.backtest.analysis.high2_low2_probe import (
    FEE_RATE,
    Fire,
    _portfolio,
    _stats,
    walk,
)
from src.backtest.sign_benchmark import split_lockbox
from src.core.types import Bar, ExitConfig, Side, Timeframe
from src.data.cache import load_cache
from src.exit.rules import OpenPosition, evaluate_exit
from src.indicators import atr

# Brooks: fade/trap trades are SCALPS (quick TP, breakeven-fast), NOT rides. The
# default arm rides (reuses high2_low2.walk); this scalp config is the faithful fade
# exit -- a fixed ~1xATR TP / 1xATR SL with a short time-stop.
SCALP = ExitConfig(
    tp_atr_mult=float(os.getenv("FB_TP_ATR", "1.0")),
    sl_atr_mult=float(os.getenv("FB_SL_ATR", "1.0")),
    time_stop_bars=int(os.getenv("FB_SCALP_TIME", "12")),
)
EXIT_MODE = os.getenv("FB_EXIT", "ride")  # "ride" (ATR-trail) | "scalp" (fixed TP/SL)

# Grid: (breakout lookback N, max bars to fail K). Kept small + pre-registered.
CONFIGS = [
    (int(n), int(k))
    for n, k in (
        pair.split(":")
        for pair in os.getenv("FB_CONFIGS", "20:3,20:5,10:3,10:5").split(",")
    )
]
SEEDS = int(os.getenv("HL_SEEDS", "40"))
STOP_ENTRY = os.getenv("HL_STOP_ENTRY", "1") != "0"


def build_fires(
    highs: list[float], lows: list[float], closes: list[float], n_lb: int, k_max: int
) -> tuple[list[Fire], list[Fire], np.ndarray, np.ndarray]:
    """Return (short_fades, long_fades, short_pool, long_pool).

    A SHORT fade fires when, within ``k_max`` bars of an up-breakout, a bar closes
    back below the broken level. ``short_pool`` = every bar that sits within k_max
    bars after an up-breakout (the breakout-matched null pool); long mirror.
    Causal: every test at t uses only bars <= t.
    """
    n = len(highs)
    shorts: list[Fire] = []
    longs: list[Fire] = []
    short_pool: list[int] = []
    long_pool: list[int] = []

    up_level = None       # broken resistance of the pending up-breakout
    up_age = 0
    dn_level = None       # broken support of the pending down-breakout
    dn_age = 0

    for t in range(n_lb, n - 1):
        prior_hi = max(highs[t - n_lb:t])
        prior_lo = min(lows[t - n_lb:t])

        # --- pending up-breakout: hunt the short fade ---
        if up_level is not None:
            short_pool.append(t)
            if closes[t] < up_level:                       # reversed back through -> trap
                shorts.append(Fire(t, Side.SHORT, lows[t]))
                up_level = None
            else:
                up_age += 1
                if up_age > k_max:
                    up_level = None
        # --- pending down-breakout: hunt the long fade ---
        if dn_level is not None:
            long_pool.append(t)
            if closes[t] > dn_level:
                longs.append(Fire(t, Side.LONG, highs[t]))
                dn_level = None
            else:
                dn_age += 1
                if dn_age > k_max:
                    dn_level = None

        # --- arm a new breakout (only if no pending one on that side) ---
        if up_level is None and highs[t] > prior_hi:
            up_level, up_age = prior_hi, 0
        if dn_level is None and lows[t] < prior_lo:
            dn_level, dn_age = prior_lo, 0

    return shorts, longs, np.asarray(short_pool, dtype=int), np.asarray(long_pool, dtype=int)


def _swalk(opens, highs, lows, closes, fire: Fire, entry_atr: float, stop_entry: bool):
    """Scalp walk: faithful Brooks fade exit (fixed TP/SL, short time-stop)."""
    f = fire.bar
    if f + 1 >= len(opens) or entry_atr <= 0.0:
        return None
    if stop_entry:
        if fire.side is Side.LONG:
            if highs[f + 1] < fire.sig:
                return None
            entry = max(opens[f + 1], fire.sig)
        else:
            if lows[f + 1] > fire.sig:
                return None
            entry = min(opens[f + 1], fire.sig)
    else:
        entry = opens[f + 1]
    pos = OpenPosition(side=fire.side, entry_price=entry, entry_atr=entry_atr)
    exit_price, exit_idx = closes[-1], len(opens) - 1
    for j in range(f + 2, len(opens)):
        bar = Bar(timestamp=None, open=opens[j], high=highs[j], low=lows[j], close=closes[j], volume=0.0)  # type: ignore[arg-type]
        res = evaluate_exit(pos, bar, SCALP)
        if res is not None:
            exit_price, exit_idx = res[1], j
            break
        pos.bars_held += 1
    signed = fire.side.sign * (exit_price - entry) / entry
    return signed - 2.0 * FEE_RATE, exit_idx


def _sportfolio(opens, highs, lows, closes, atrs, fires: list[Fire], stop_entry: bool) -> list[float]:
    """Flat-only single-position walk under the scalp exit."""
    out: list[float] = []
    free_until = -1
    for fr in fires:
        if fr.bar + 1 <= free_until:
            continue
        r = _swalk(opens, highs, lows, closes, fr, atrs[fr.bar], stop_entry)
        if r is None:
            continue
        out.append(r[0])
        free_until = r[1]
    return out


# Active walk/portfolio selected by FB_EXIT.
_WALK = _swalk if EXIT_MODE == "scalp" else walk
_PORT = _sportfolio if EXIT_MODE == "scalp" else _portfolio


def _null(
    opens, highs, lows, closes, atrs,
    short_pool: np.ndarray, long_pool: np.ndarray, n_short: int, n_long: int,
) -> tuple[float, float]:
    """Breakout-matched random fade null: (sharpe_mean, sharpe_sd) over SEEDS seeds."""
    if (n_short and short_pool.size < n_short) or (n_long and long_pool.size < n_long):
        return 0.0, 0.0
    sharpes: list[float] = []
    for s in range(SEEDS):
        rng = np.random.default_rng(s)
        picks: list[Fire] = []
        if n_short:
            for b in rng.choice(short_pool, size=n_short, replace=False):
                picks.append(Fire(int(b), Side.SHORT, lows[int(b)]))
        if n_long:
            for b in rng.choice(long_pool, size=n_long, replace=False):
                picks.append(Fire(int(b), Side.LONG, highs[int(b)]))
        picks.sort(key=lambda f: f.bar)
        sharpes.append(_stats(_PORT(opens, highs, lows, closes, atrs, picks, STOP_ENTRY))[2])
    a = np.asarray(sharpes)
    return float(a.mean()), float(a.std())


_TF = {"1m": Timeframe.M1, "5m": Timeframe.M5, "15m": Timeframe.M15, "1h": Timeframe.H1}


def main() -> None:
    product = os.getenv("HL_PRODUCT", "GMO_BTC_JPY")
    tf = _TF[os.getenv("FB_TF", "1h")]
    bars = load_cache(tf, product=product).bars
    is_b, _oos = split_lockbox(bars)  # IN-SAMPLE ONLY (hygiene)
    df = load_cache(tf, product=product).to_frame().loc[: is_b[-1].timestamp]
    opens = df["open"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    closes = df["close"].tolist()
    atrs = [float(v) for v in atr(df, 14).to_numpy()]

    exit_desc = (f"SCALP fixed TP{SCALP.tp_atr_mult}/SL{SCALP.sl_atr_mult}/time{SCALP.time_stop_bars}"
                 if EXIT_MODE == "scalp" else "RIDE ATR-trail sl2/trail2/time48")
    print(f"{product} {tf.value} IN-SAMPLE: {len(df)} bars  {df.index[0]} -> {df.index[-1]}")
    print(f"  fade exit = {exit_desc}, stop_entry={STOP_ENTRY}, null seeds={SEEDS}\n")
    print(f"{'N':>3} {'K':>3} {'arm':6} {'view':11} {'n':>5} {'sum_ret':>9} {'sharpe':>8} {'win':>6} {'lift_z':>7}")
    print("-" * 70)

    for n_lb, k_max in CONFIGS:
        shorts, longs, sp, lp = build_fires(highs, lows, closes, n_lb, k_max)
        combined = sorted(shorts + longs, key=lambda f: f.bar)
        for arm_name, fires in (("short", shorts), ("long", longs), ("both", combined)):
            eq = [r[0] for fr in fires
                  if (r := _WALK(opens, highs, lows, closes, fr, atrs[fr.bar], STOP_ENTRY)) is not None]
            en, es, esh, ew = _stats(eq)
            pf = _PORT(opens, highs, lows, closes, atrs, fires, STOP_ENTRY)
            pn, ps, psh, pw = _stats(pf)
            ns = sum(1 for f in fires if f.side is Side.SHORT)
            nl = sum(1 for f in fires if f.side is Side.LONG)
            nmean, nsd = _null(opens, highs, lows, closes, atrs, sp, lp, ns, nl)
            z = (psh - nmean) / nsd if nsd > 0 else 0.0
            print(f"{n_lb:>3} {k_max:>3} {arm_name:6} {'entry-qual':11} {en:>5} {es:>9.4f} {esh:>8.3f} {ew:>6.2f} {'-':>7}")
            print(f"{n_lb:>3} {k_max:>3} {arm_name:6} {'portfolio':11} {pn:>5} {ps:>9.4f} {psh:>8.3f} {pw:>6.2f} {z:>7.2f}"
                  f"   (null_sh {nmean:+.3f}±{nsd:.3f})")
        print()

    print("GATE (per arm portfolio): G1 net>0 & sharpe>=+0.10 ; G2 lift_z>=+1.0 ; G3 n>=30.")
    print("FALSIFIER: lift_z<=0 -> reclaim selection adds nothing over 'fade any post-breakout bar' -> REJECT.")
    print("OOS reserved: lockbox untouched.")


if __name__ == "__main__":
    main()
