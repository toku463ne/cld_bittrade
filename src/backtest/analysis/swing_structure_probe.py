"""Faithful composite-walk probe: swing-structure (HH/HL) entry + ATR trail exit.

Replaces the abandoned trendline approach (too many DOF — a small angle change
flipped bounce/break/no-touch). This entry compares confirmed zigzag peaks by
PRICE LEVEL, not by a fitted line, so it is computed identically by anyone and
has no angle to hand-tune:

  uptrend   = last confirmed HIGH > prior HIGH  AND  last confirmed LOW > prior LOW
  downtrend = last confirmed HIGH < prior HIGH  AND  last confirmed LOW < prior LOW

Two entry arms (the open A/B):
  "pullback" — fire the moment a new confirmed HIGHER-LOW becomes known inside an
               uptrend (the dip held → go long for the next leg); mirror for short.
  "breakout" — fire when price first closes ABOVE the last confirmed swing high
               inside an uptrend (structure-gated continuation); mirror for short.

Exit = ATR trailing stop (the trend-following exit): initial stop SL_ATR×ATR,
trail by TRAIL_ATR×ATR from the favourable extreme, long time-stop — lets winners
run, unlike the symmetric ZsTpSl bracket that clipped them. Walked bar-by-bar
from open[fire+1] (two-bar fill), SL/trail-before-TP pessimistic, exactly as
src/simulator/simulator.py. Two views per arm: entry-quality (every fire walked
independently) and portfolio (single-position flat-only, skip-while-busy).

PRE-REGISTERED ACCEPT GATE (write before running; do not change after):
  Promote to a production strategy ONLY if, on GMO_BTC_JPY 5m, the better arm's
  PORTFOLIO view clears BOTH:
    (G1) net Σreturn > 0, AND
    (G2) per-trade Sharpe >= +0.10.
COMPARISON BASELINE: the trendline fan probe's best arm was first/portfolio
  Sharpe -0.153 (net negative). Beating 0 here is the whole point of switching to
  trend-following + trailing.
FALSIFIER: if BOTH arms are net-negative on 5m, trend-following-on-5m is also
  fee-dominated; defer to GMO 1h (still importing) before any further work.
frac_acted: report n per arm; a < ~30-trade portfolio view is too thin (§ 5.1).

Read-only: no DB writes, no production sign/strategy changes.
Run: uv run --env-file .env.bt python -m src.backtest.analysis.swing_structure_probe
"""

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from src.core.types import Bar, ExitConfig, Side, Timeframe
from src.data.cache import load_cache
from src.exit.rules import OpenPosition, evaluate_exit
from src.indicators import atr
from src.backtest.analysis.trendline_fan_probe import CPeak, confirmed_peaks

# --- config ------------------------------------------------------------------
ATR_PERIOD = 14
SL_ATR = 2.0      # initial hard stop distance (× ATR at entry)
TRAIL_ATR = 2.0   # trailing stop distance (× ATR) from the favourable extreme
TIME_STOP = 288   # bars (~1 day on 5m) — long, so the trail decides
# Per-side taker slippage (FX_BTC_JPY is commission-free; this models half-spread).
# Override with env FEE to sweep cost; default 2 bps/side (calm-market estimate).
FEE_RATE = float(os.getenv("FEE", "0.0002"))
LOT = 0.001
EXIT = ExitConfig(
    sl_atr_mult=SL_ATR, trail_atr_mult=TRAIL_ATR, time_stop_bars=TIME_STOP
)


@dataclass(frozen=True, slots=True)
class Fire:
    """A swing-structure entry candidate."""

    bar: int
    side: Side


def build_fires(
    highs: list[float], lows: list[float], closes: list[float], cpeaks: list[CPeak]
) -> tuple[list[Fire], list[Fire]]:
    """Return (pullback fires, breakout fires) from the HH/HL swing structure.

    Causal: a confirmed peak is only used from its ``known_at`` bar onward, and
    every close test uses only ``closes[<= t]``.
    """
    n = len(highs)
    by_known: dict[int, list[CPeak]] = defaultdict(list)
    for p in cpeaks:
        by_known[p.known_at].append(p)

    seen_h: list[CPeak] = []
    seen_l: list[CPeak] = []
    pullback: list[Fire] = []
    breakout: list[Fire] = []
    prev_close: float | None = None

    for t in range(n):
        # 1. New confirmed peaks become known at t → update structure + pullback.
        for p in by_known.get(t, []):
            (seen_h if p.is_high else seen_l).append(p)
            if len(seen_h) < 2 or len(seen_l) < 2:
                continue
            up = seen_h[-1].price > seen_h[-2].price and seen_l[-1].price > seen_l[-2].price
            dn = seen_h[-1].price < seen_h[-2].price and seen_l[-1].price < seen_l[-2].price
            # Pullback fires when the freshly-confirmed peak is the held swing:
            # a higher-low in an uptrend (long) / a lower-high in a downtrend.
            if not p.is_high and up:
                pullback.append(Fire(t, Side.LONG))
            elif p.is_high and dn:
                pullback.append(Fire(t, Side.SHORT))

        # 2. Breakout: a fresh close through the last swing high/low, structure-gated.
        if prev_close is not None and len(seen_h) >= 2 and len(seen_l) >= 2:
            up = seen_h[-1].price > seen_h[-2].price and seen_l[-1].price > seen_l[-2].price
            dn = seen_h[-1].price < seen_h[-2].price and seen_l[-1].price < seen_l[-2].price
            cl = closes[t]
            if up and prev_close <= seen_h[-1].price < cl:
                breakout.append(Fire(t, Side.LONG))
            elif dn and prev_close >= seen_l[-1].price > cl:
                breakout.append(Fire(t, Side.SHORT))
        prev_close = closes[t]

    return pullback, breakout


def walk_exit(
    opens: list[float], highs: list[float], lows: list[float], closes: list[float],
    fire: Fire, entry_atr: float,
) -> tuple[float, int] | None:
    """Walk the ATR trailing exit from open[fire+1]; return (return_pct_net, exit_idx)."""
    f = fire.bar
    if f + 1 >= len(opens) or entry_atr <= 0.0:
        return None
    entry = opens[f + 1]
    pos = OpenPosition(side=fire.side, entry_price=entry, entry_atr=entry_atr)
    exit_price = closes[-1]
    exit_idx = len(opens) - 1
    for j in range(f + 2, len(opens)):
        bar = Bar(timestamp=None, open=opens[j], high=highs[j], low=lows[j], close=closes[j], volume=0.0)  # type: ignore[arg-type]
        res = evaluate_exit(pos, bar, EXIT)
        if res is not None:
            exit_price = res[1]
            exit_idx = j
            break
        pos.bars_held += 1
    signed = fire.side.sign * (exit_price - entry) / entry
    return signed - 2.0 * FEE_RATE, exit_idx


def _stats(rets: list[float]) -> tuple[int, float, float, float]:
    if not rets:
        return 0, 0.0, 0.0, 0.0
    a = np.array(rets, dtype=float)
    std = float(a.std(ddof=1)) if a.size > 1 else 0.0
    sharpe = float(a.mean() / std) if std > 0.0 else 0.0
    return a.size, float(a.sum()), sharpe, float((a > 0.0).mean())


_TF = {"1m": Timeframe.M1, "5m": Timeframe.M5, "15m": Timeframe.M15, "1h": Timeframe.H1}


def main() -> None:
    tf = _TF[os.getenv("SWING_TF", "5m")]
    product = os.getenv("SWING_PRODUCT", "GMO_BTC_JPY")
    df = load_cache(tf, product=product).to_frame()
    opens = df["open"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    closes = df["close"].tolist()
    atrs = [float(v) for v in atr(df, ATR_PERIOD).to_numpy()]
    print(f"{product} {tf.value}: {len(df)} bars  {df.index[0]} -> {df.index[-1]}")

    size = int(os.getenv("SWING_SIZE", "5"))
    cpeaks = confirmed_peaks(highs, lows, size=size)
    pullback, breakout = build_fires(highs, lows, closes, cpeaks)
    print(f"swing size={size}  confirmed peaks={len(cpeaks)}  fires: "
          f"pullback={len(pullback)} breakout={len(breakout)}  "
          f"(exit: ATR trail sl{SL_ATR}/trail{TRAIL_ATR})\n")

    print(f"{'arm':10} {'view':12} {'n':>5} {'sum_ret':>9} {'sharpe':>8} {'win':>6}")
    print("-" * 54)
    for name, fires in (("pullback", pullback), ("breakout", breakout)):
        eq: list[float] = []
        for fr in fires:
            r = walk_exit(opens, highs, lows, closes, fr, atrs[fr.bar])
            if r is not None:
                eq.append(r[0])
        n, s, sh, w = _stats(eq)
        print(f"{name:10} {'entry-qual':12} {n:>5} {s:>9.4f} {sh:>8.3f} {w:>6.2f}")
        pf: list[float] = []
        free_until = -1
        for fr in fires:
            if fr.bar + 1 <= free_until:
                continue
            r = walk_exit(opens, highs, lows, closes, fr, atrs[fr.bar])
            if r is None:
                continue
            pf.append(r[0])
            free_until = r[1]
        n, s, sh, w = _stats(pf)
        net = sum(rr * LOT * closes[0] for rr in pf)
        print(f"{name:10} {'portfolio':12} {n:>5} {s:>9.4f} {sh:>8.3f} {w:>6.2f}"
              f"   net~{net:.0f}JPY")
    print("\nGate: promote only if better arm's portfolio has net>0 AND sharpe>=+0.10.")
    print("Baseline to beat: trendline fan first/portfolio sharpe -0.153 (net<0).")


if __name__ == "__main__":
    main()
