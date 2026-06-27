"""Stage-0 probe: Brooks **High2 / Low2** (M2B / M2S) with-trend continuation on 1h BTC.

The one Brooks setup most likely to transfer here, because it is a *with-trend
continuation* — the only family that has ever cleared this repo's nulls (density
ride / vol_expansion / breakout), while every reversal/fade mechanism has died
(sweep_reclaim, stale_box_fade, JST-calendar, trend-following, zigzag_bounce).
Brooks' own guideline #7/#22/#28-30 ("counter-trend is certain ruin; continuation
works in a trend") is the same statement as those null results.

MECHANISM (causal, computed identically by anyone — no fitted line, no angle DOF):
  Trend regime from confirmed zigzag peaks (reuses trendline_fan_probe.confirmed_peaks):
    uptrend   = last confirmed HIGH > prior HIGH  AND  last confirmed LOW > prior LOW
    downtrend = mirror.
  Inside a trend, count pullback legs with a consecutive-bar state machine:
    In an uptrend pullback (price below the running swing high), an "up-poke"
    (high[t] > high[t-1]) ends a down-leg. H1 = first up-poke; H2 = the next
    up-poke AFTER an intervening lower-high (= two-leg ABC pullback, which is also
    Brooks' "minor trendline broke / counter-side briefly active" proxy). Mirror
    = Low1/Low2 in a downtrend.
  Three arms, strictly nested, to isolate what (if anything) adds edge:
    h1  — fire at the first up-poke (Brooks: too early on its own).
    h2  — fire at the second (the two-leg pullback, the core trade).
    m2b — h2 AND the pullback extreme touched the 20-EMA (Brooks M2B/M2S, the
          highest-confidence variant).

ENTRY (faithful Brooks stop-entry, inside the repo two-bar fill): candidate at the
  signal bar f; on bar f+1 fill ONLY if price trades through the signal-bar extreme
  (long: high[f+1] >= signal_high), entry = max(open[f+1], signal_high). A signal
  bar whose extreme is not taken out next bar expires unfilled (self-selecting, the
  point of a stop-entry). Set HL_STOP_ENTRY=0 to fall back to plain open[f+1].
EXIT = ATR trailing stop (the with-trend ride exit that lets winners run), walked
  bar-by-bar from open[f+2] under src/exit/rules.evaluate_exit, SL/trail-before-TP
  pessimistic — identical mechanics to swing_structure_probe / the live simulator.
Two views per arm: entry-quality (every fill walked independently) and portfolio
  (single-position, flat-only, skip-while-busy — the apples-to-apples slot view).

NULL (the repo's paired fill-order floor, regime-matched): random with-trend entry.
  For each arm we draw, over HL_SEEDS seeds, the SAME number of long/short fills as
  the arm has, at RANDOM bars drawn from the SAME trend regime (long pool = uptrend
  bars, short pool = downtrend bars), with the SAME stop-entry rule and SAME exit.
  This holds *trend exposure* constant and asks only whether the H2 leg-count TIMING
  beats random with-trend timing — the honest floor for an entry-selection sign
  (B&H is the wrong floor for an entry edge; see null_floor_sweep.py).

PRE-REGISTERED ACCEPT GATE (written before running; do not change after):
  On GMO_BTC_JPY 1h, IN-SAMPLE ONLY, build a production high2/low2 strategy ONLY if
  the m2b (or, if stronger, h2) arm's PORTFOLIO view clears ALL of:
    (G1) net Σreturn > 0 AND per-trade Sharpe >= +0.10, AND
    (G2) per-trade Sharpe beats the regime-matched random null mean by >= +1.0
         null-sd (lift z >= 1.0), AND
    (G3) n >= 30 portfolio fills (else too thin to read — flag, do not conclude).
FALSIFIER: if Sharpe ranks h1 >= h2 >= m2b, the two-leg count + EMA touch add
  nothing -> Brooks' leg-count does not transfer to 1h BTC; defer (report explicitly).
OOS HYGIENE: in-sample only. This probe never touches the lockbox OOS — selection
  during ideation must stay inside IS (MEMORY oos-hygiene). The held-out test is the
  cycle walk-forward / live-forward, run once, only if this gate passes.

Read-only: writes no DB, mutates no production sign/strategy code. Unregistered.
Run: uv run --env-file .env.bt python -m src.backtest.analysis.high2_low2_probe
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from src.backtest.analysis.trendline_fan_probe import confirmed_peaks
from src.backtest.sign_benchmark import split_lockbox
from src.core.types import Bar, ExitConfig, Side, Timeframe
from src.data.cache import load_cache
from src.exit.rules import OpenPosition, evaluate_exit
from src.indicators import atr, ema

# --- config ------------------------------------------------------------------
ATR_PERIOD = 14
EMA_PERIOD = 20            # Brooks' only indicator
SL_ATR = 2.0              # initial hard stop distance (x ATR at entry)
TRAIL_ATR = 2.0           # trailing stop distance (x ATR) from favourable extreme
TIME_STOP = 48            # bars (~2 days on 1h) — long, so the trail decides
FEE_RATE = float(os.getenv("FEE", "0.0002"))   # per side; 2 bp/side calm estimate
LOT = 0.001
STOP_ENTRY = os.getenv("HL_STOP_ENTRY", "1") != "0"
EXIT = ExitConfig(sl_atr_mult=SL_ATR, trail_atr_mult=TRAIL_ATR, time_stop_bars=TIME_STOP)
_TF = {"1m": Timeframe.M1, "5m": Timeframe.M5, "15m": Timeframe.M15, "1h": Timeframe.H1}


@dataclass(frozen=True, slots=True)
class Fire:
    """A High2/Low2 entry candidate (signal bar + the stop-entry extreme)."""

    bar: int
    side: Side
    sig: float   # signal-bar high (long) / low (short) — the stop-entry trigger


def bar_regime(highs: list[float], lows: list[float], size: int) -> list[int]:
    """Per-bar causal trend label: +1 uptrend, -1 downtrend, 0 none.

    Built from confirmed zigzag peaks, each applied only from its ``known_at`` bar
    (so the label at t uses no future information). Uptrend = the last two confirmed
    highs AND lows are both rising; downtrend = both falling.
    """
    n = len(highs)
    cpeaks = confirmed_peaks(highs, lows, size=size)
    by_known: dict[int, list] = {}
    for p in cpeaks:
        by_known.setdefault(p.known_at, []).append(p)
    seen_h: list[float] = []
    seen_l: list[float] = []
    reg = [0] * n
    cur = 0
    for t in range(n):
        for p in by_known.get(t, []):
            (seen_h if p.is_high else seen_l).append(p.price)
        if len(seen_h) >= 2 and len(seen_l) >= 2:
            if seen_h[-1] > seen_h[-2] and seen_l[-1] > seen_l[-2]:
                cur = 1
            elif seen_h[-1] < seen_h[-2] and seen_l[-1] < seen_l[-2]:
                cur = -1
        reg[t] = cur
    return reg


def build_fires(
    highs: list[float], lows: list[float], emas: list[float], reg: list[int]
) -> tuple[list[Fire], list[Fire], list[Fire]]:
    """Return (h1, h2, m2b) fires from the pullback leg-count state machine.

    Causal: every test at t uses only bars <= t and the causal regime label.
    """
    n = len(highs)
    h1: list[Fire] = []
    h2: list[Fire] = []
    m2b: list[Fire] = []

    # Uptrend pullback state.
    up_max = -1e30
    in_pb = pull_low = hc = saw_down = fired1 = fired2 = 0.0  # placeholders, set below
    in_pb = False
    pull_low = 1e30
    hc = 0
    saw_down = False
    fired1 = fired2 = False
    # Downtrend pullback state (mirror).
    dn_min = 1e30
    in_pb_d = False
    pull_high = -1e30
    lc = 0
    saw_up = False
    fired1_d = fired2_d = False
    prev = 0

    for t in range(1, n):
        r = reg[t]
        if r != prev:  # regime change -> reset both episodes
            up_max, in_pb, pull_low, hc, saw_down, fired1, fired2 = -1e30, False, 1e30, 0, False, False, False
            dn_min, in_pb_d, pull_high, lc, saw_up, fired1_d, fired2_d = 1e30, False, -1e30, 0, False, False, False
        prev = r

        if r == 1:  # ---- uptrend: hunt High1/High2 longs ----
            if highs[t] > up_max:  # new swing high / resume -> pullback resets
                up_max = highs[t]
                in_pb, pull_low, hc, saw_down, fired1, fired2 = False, 1e30, 0, False, False, False
            else:
                if not in_pb:
                    in_pb, pull_low, hc, saw_down, fired1, fired2 = True, lows[t], 0, False, False, False
                else:
                    pull_low = min(pull_low, lows[t])
                if highs[t] > highs[t - 1]:           # up-poke ends a down-leg
                    if hc == 0 or saw_down:
                        hc += 1
                        saw_down = False
                        if hc == 1 and not fired1:
                            h1.append(Fire(t, Side.LONG, highs[t]))
                            fired1 = True
                        elif hc == 2 and not fired2:
                            h2.append(Fire(t, Side.LONG, highs[t]))
                            if emas[t] > 0.0 and pull_low <= emas[t]:
                                m2b.append(Fire(t, Side.LONG, highs[t]))
                            fired2 = True
                elif highs[t] < highs[t - 1]:         # lower high = next down-leg
                    saw_down = True

        elif r == -1:  # ---- downtrend: hunt Low1/Low2 shorts ----
            if lows[t] < dn_min:
                dn_min = lows[t]
                in_pb_d, pull_high, lc, saw_up, fired1_d, fired2_d = False, -1e30, 0, False, False, False
            else:
                if not in_pb_d:
                    in_pb_d, pull_high, lc, saw_up, fired1_d, fired2_d = True, highs[t], 0, False, False, False
                else:
                    pull_high = max(pull_high, highs[t])
                if lows[t] < lows[t - 1]:
                    if lc == 0 or saw_up:
                        lc += 1
                        saw_up = False
                        if lc == 1 and not fired1_d:
                            h1.append(Fire(t, Side.SHORT, lows[t]))
                            fired1_d = True
                        elif lc == 2 and not fired2_d:
                            h2.append(Fire(t, Side.SHORT, lows[t]))
                            if emas[t] > 0.0 and pull_high >= emas[t]:
                                m2b.append(Fire(t, Side.SHORT, lows[t]))
                            fired2_d = True
                elif lows[t] > lows[t - 1]:
                    saw_up = True

    return h1, h2, m2b


def walk(
    opens: list[float], highs: list[float], lows: list[float], closes: list[float],
    fire: Fire, entry_atr: float, stop_entry: bool,
) -> tuple[float, int] | None:
    """Walk the ATR-trail exit; return (net_return_pct, exit_idx) or None.

    Two-bar fill at open[f+1]; with ``stop_entry`` the fill requires bar f+1 to
    trade through the signal-bar extreme (else the candidate expires unfilled).
    """
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
    exit_price = closes[-1]
    exit_idx = len(opens) - 1
    for j in range(f + 2, len(opens)):
        bar = Bar(timestamp=None, open=opens[j], high=highs[j], low=lows[j], close=closes[j], volume=0.0)  # type: ignore[arg-type]
        res = evaluate_exit(pos, bar, EXIT)
        if res is not None:
            exit_price, exit_idx = res[1], j
            break
        pos.bars_held += 1
    signed = fire.side.sign * (exit_price - entry) / entry
    return signed - 2.0 * FEE_RATE, exit_idx


def _stats(rets: list[float]) -> tuple[int, float, float, float]:
    if not rets:
        return 0, 0.0, 0.0, 0.0
    a = np.asarray(rets, dtype=float)
    std = float(a.std(ddof=1)) if a.size > 1 else 0.0
    sharpe = float(a.mean() / std) if std > 0.0 else 0.0
    return a.size, float(a.sum()), sharpe, float((a > 0.0).mean())


def _portfolio(
    opens, highs, lows, closes, atrs, fires: list[Fire], stop_entry: bool
) -> list[float]:
    """Flat-only single-position walk over ``fires`` (skip while a trade is open)."""
    out: list[float] = []
    free_until = -1
    for fr in fires:
        if fr.bar + 1 <= free_until:
            continue
        r = walk(opens, highs, lows, closes, fr, atrs[fr.bar], stop_entry)
        if r is None:
            continue
        out.append(r[0])
        free_until = r[1]
    return out


def _null(
    opens, highs, lows, closes, atrs, reg: list[int], arm: list[Fire],
    seeds: int, stop_entry: bool,
) -> tuple[float, float, float, float]:
    """Regime-matched random with-trend null: (sharpe_mean, sharpe_sd, sum_mean, sum_sd).

    Per seed, draw as many long/short entries as ``arm`` has, at random bars from
    the matching trend regime, with the same stop-entry + exit, then take the
    flat-only portfolio Sharpe. Isolates leg-count timing from trend exposure.
    """
    n = len(opens)
    long_pool = np.array([t for t in range(1, n - 1) if reg[t] == 1], dtype=int)
    short_pool = np.array([t for t in range(1, n - 1) if reg[t] == -1], dtype=int)
    n_long = sum(1 for f in arm if f.side is Side.LONG)
    n_short = sum(1 for f in arm if f.side is Side.SHORT)
    if (n_long and long_pool.size == 0) or (n_short and short_pool.size == 0):
        return 0.0, 0.0, 0.0, 0.0
    sharpes: list[float] = []
    sums: list[float] = []
    for s in range(seeds):
        rng = np.random.default_rng(s)
        picks: list[Fire] = []
        if n_long:
            for b in rng.choice(long_pool, size=n_long, replace=False) if n_long <= long_pool.size else long_pool:
                picks.append(Fire(int(b), Side.LONG, highs[int(b)]))
        if n_short:
            for b in rng.choice(short_pool, size=n_short, replace=False) if n_short <= short_pool.size else short_pool:
                picks.append(Fire(int(b), Side.SHORT, lows[int(b)]))
        picks.sort(key=lambda f: f.bar)
        pf = _portfolio(opens, highs, lows, closes, atrs, picks, stop_entry)
        nn, ss, sh, _ = _stats(pf)
        sharpes.append(sh)
        sums.append(ss)
    a, b = np.asarray(sharpes), np.asarray(sums)
    return float(a.mean()), float(a.std()), float(b.mean()), float(b.std())


def main() -> None:
    tf = _TF[os.getenv("HL_TF", "1h")]
    product = os.getenv("HL_PRODUCT", "GMO_BTC_JPY")
    size = int(os.getenv("HL_SIZE", "5"))
    seeds = int(os.getenv("HL_SEEDS", "40"))

    bars = load_cache(tf, product=product).bars
    is_b, _oos = split_lockbox(bars)  # IN-SAMPLE ONLY — OOS reserved (hygiene)
    df = load_cache(tf, product=product).to_frame().loc[: is_b[-1].timestamp]
    opens = df["open"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    closes = df["close"].tolist()
    atrs = [float(v) for v in atr(df, ATR_PERIOD).to_numpy()]
    emas = [float(v) for v in ema(df["close"], EMA_PERIOD).to_numpy()]

    print(f"{product} {tf.value} IN-SAMPLE: {len(df)} bars  {df.index[0]} -> {df.index[-1]}")
    reg = bar_regime(highs, lows, size)
    up_bars = sum(1 for r in reg if r == 1)
    dn_bars = sum(1 for r in reg if r == -1)
    print(f"swing size={size}  regime bars: up={up_bars} dn={dn_bars} "
          f"none={len(reg) - up_bars - dn_bars}  (exit ATR trail sl{SL_ATR}/trail{TRAIL_ATR}, "
          f"stop_entry={STOP_ENTRY})\n")

    h1, h2, m2b = build_fires(highs, lows, emas, reg)
    arms = {"h1": h1, "h2": h2, "m2b": m2b}
    print(f"fires: h1={len(h1)} h2={len(h2)} m2b={len(m2b)}\n")

    print(f"{'arm':5} {'view':11} {'n':>5} {'sum_ret':>9} {'sharpe':>8} {'win':>6}")
    print("-" * 48)
    pf_sharpe: dict[str, float] = {}
    pf_n: dict[str, int] = {}
    for name, fires in arms.items():
        eq = [r[0] for fr in fires if (r := walk(opens, highs, lows, closes, fr, atrs[fr.bar], STOP_ENTRY)) is not None]
        n, s, sh, w = _stats(eq)
        print(f"{name:5} {'entry-qual':11} {n:>5} {s:>9.4f} {sh:>8.3f} {w:>6.2f}")
        pf = _portfolio(opens, highs, lows, closes, atrs, fires, STOP_ENTRY)
        n, s, sh, w = _stats(pf)
        net = sum(rr * LOT * closes[0] for rr in pf)
        pf_sharpe[name], pf_n[name] = sh, n
        print(f"{name:5} {'portfolio':11} {n:>5} {s:>9.4f} {sh:>8.3f} {w:>6.2f}   net~{net:.0f}JPY")

    # Null comparison for the gate arm (m2b; report h2 too for the falsifier).
    print(f"\nregime-matched random null ({seeds} seeds, portfolio view):")
    print(f"{'arm':5} {'real_sh':>8} {'null_sh':>8} {'null_sd':>8} {'lift_z':>7} {'n':>5}")
    print("-" * 44)
    for name in ("h2", "m2b"):
        if not arms[name]:
            continue
        nsh, nsd, _nsum, _nss = _null(opens, highs, lows, closes, atrs, reg, arms[name], seeds, STOP_ENTRY)
        z = (pf_sharpe[name] - nsh) / nsd if nsd > 0 else 0.0
        print(f"{name:5} {pf_sharpe[name]:>8.3f} {nsh:>8.3f} {nsd:>8.3f} {z:>7.2f} {pf_n[name]:>5}")

    print("\nGATE (m2b/h2 portfolio): G1 net>0 & sharpe>=+0.10 ; "
          "G2 lift_z>=+1.0 ; G3 n>=30.")
    print("FALSIFIER: if sharpe h1>=h2>=m2b, leg-count adds nothing -> defer.")
    print("OOS reserved: do NOT touch the lockbox for keep/drop (run cycle WF once if gate passes).")


if __name__ == "__main__":
    main()
