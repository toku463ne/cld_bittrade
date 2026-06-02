"""Faithful composite-walk probe: anchored-trendline-fan entries vs ZsTpSl.

Authorized by the /sign-debate cycle (2026-06-02) on the proposal to replace
`zigzag_trendline`'s line drawing with a *stateful anchored fan*: the outstanding
(extreme) same-type confirmed peak is a sticky first anchor A; lines fan out A->B
to each successive same-type confirmed peak B; price retests of those lines are
the entries. The debate's decisive open question (judge falsifier) is the TOUCH
TIMING rule:

  Arm "first" — fire on the FIRST actionable touch of the line.
  Arm "half"  — fire only on a touch at least span/2 bars past B
                (= the user's "take the position after half of the 2 point bars",
                 which is the `min_touch_frac=0.5` gate already on record in
                 benchmark.md as moving IS Sharpe -0.249 -> -0.795 vs this exit).

Both arms share the SAME fan, so the comparison isolates the timing rule.

What "faithful" means here (rubric § 5.9): each fire is walked bar-by-bar under
the LIVE ZsTpSl exit from open[fire+1] (two-bar fill), SL-before-TP pessimistic,
time-stop at max_bars — identical to src/simulator/simulator.py. Two views per
arm: (1) entry-quality — every fire walked independently (isolates timing);
(2) portfolio — single-position flat-only, skip-while-busy (honors slot
contention, § 5.12), the apples-to-apples match for run_cycle's IS Sharpe.

PRE-REGISTERED ACCEPT GATE (write before running, do not change after):
  Build production fan detector ONLY if, on GMO_BTC_JPY 5m, the "first" arm's
  portfolio view clears BOTH:
    (G1) net PnL > 0, AND
    (G2) per-trade Sharpe >= +0.10  (materially above the current model's IS
         Sharpe of -0.086, per evaluation_criteria.md § 3 EV materiality).
SIGN-FLIP FALSIFIER:
  If instead the "half" arm's Sharpe >= the "first" arm's Sharpe, the historical
  finding (span/2 wait hurts) is OVERTURNED and rule 4 (touch-after-half) is
  vindicated — report that explicitly.
frac_acted note: report n fires per arm; a < ~30-trade portfolio view is too thin
  to read Sharpe from (§ 5.1) — flag rather than conclude.

Read-only: writes no DB, mutates no production sign/strategy code.
Run: uv run --env-file .env.bt python -m src.backtest.analysis.trendline_fan_probe
"""

from __future__ import annotations

import bisect
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from src.core.types import Side, Timeframe
from src.data.cache import load_cache
from src.exit.base import ExitContext
from src.exit.rules import OpenPosition, evaluate_exit
from src.exit.zs_tp_sl import ZsTpSl

# --- config (mirrors zigzag_trendline / ZsTpSl defaults) ---------------------
SIZE = 5
MID = 3
WINDOW_BARS = 120
TOL_PCT = 0.005
CROSS_TOL = 0.005
CROSS_AFTER_FRAC = 2.0 / 3.0
MIN_SEP = 2
VALID_FRAC = 1.0
MIN_ANGLE_PCT = 0.0005
# Break tolerance: a bar is "over" the line only if its extreme pokes past it by
# more than this fraction (tight — a real poke through, separate from the wider
# TOL_PCT touch band). Used for both interior and forward break detection.
BREAK_TOL = 0.0015
# Interior break: this many consecutive "over" bars BETWEEN the anchors rejects
# the line as not a trendline (a peak poked through it).
INTERIOR_BREAK_BARS = 2
# Forward break: this many consecutive "over" bars past B marks the line broken
# (user rule, 2026-06-02 — a later peak poking through kills it).
BREAK_OVER_BARS = 3
N_LEGS = 6
FEE_RATE = 0.001
LOT = 0.001
EXIT = ZsTpSl(tp_mult=1.0, sl_mult=1.0, alpha=0.3, min_legs=3, fallback_pct=0.01, max_bars=48)


@dataclass(frozen=True, slots=True)
class CPeak:
    """A causally-confirmed zigzag peak (known `size` bars after it forms)."""

    idx: int
    is_high: bool
    price: float
    known_at: int


def confirmed_peaks(
    highs: list[float], lows: list[float], size: int = SIZE
) -> list[CPeak]:
    """Confirmed peaks in chronological order, each with its causal known_at bar.

    A bar c is a confirmed high if highs[c] is the max of [c-size, c+size]; it
    becomes knowable at c+size. Mirrors detect_peaks' confirmed rule without the
    global merge (sufficient for anchors and leg sizing in a probe). ``size`` is
    the swing scale — larger = fewer, more structural swings.
    """
    n = len(highs)
    out: list[CPeak] = []
    for c in range(size, n - size):
        lo, hi = c - size, c + size + 1
        if highs[c] == max(highs[lo:hi]):
            out.append(CPeak(c, True, highs[c], c + size))
        elif lows[c] == min(lows[lo:hi]):
            out.append(CPeak(c, False, lows[c], c + size))
    return out


def _leg_table(cpeaks: list[CPeak]) -> tuple[list[int], list[float]]:
    """(known_at, leg_size) for consecutive confirmed peaks — ZsTpSl input."""
    kn: list[int] = []
    legs: list[float] = []
    for k in range(1, len(cpeaks)):
        kn.append(cpeaks[k].known_at)
        legs.append(abs(cpeaks[k].price - cpeaks[k - 1].price))
    return kn, legs


def _legs_at(kn: list[int], legs: list[float], bar: int) -> tuple[float, ...]:
    """Last N_LEGS leg sizes known at `bar` (oldest-first)."""
    j = bisect.bisect_right(kn, bar)
    return tuple(legs[max(0, j - N_LEGS) : j])


@dataclass(frozen=True, slots=True)
class Fire:
    """A line-retest entry candidate."""

    bar: int
    side: Side
    anchor_a: int  # outstanding anchor idx (re-anchor tracking)


@dataclass(frozen=True, slots=True)
class Line:
    """Geometry of one fan trendline, for visual inspection (see fan viewer)."""

    a_idx: int
    a_price: float
    b_idx: int
    b_price: float
    slope: float
    is_high: bool
    proj_hi: int  # last live proj (bars past B)
    broken_at: int  # bar where the line was broken, or -1
    first_touch: int  # first touch bar, or -1
    half_touch: int  # first touch with proj >= span/2, or -1


@dataclass(frozen=True, slots=True)
class ScanResult:
    """Per-line scan output (touches + where/whether it broke)."""

    slope: float
    first_touch: int
    half_touch: int
    broken_at: int
    last_live: int  # last bar the line was still valid


def _scan_line(
    highs: list[float], lows: list[float], closes: list[float], n: int,
    a: CPeak, b: CPeak, *, is_high: bool,
) -> ScanResult | None:
    """Scan one A->B line forward for touches and breaks, or None if not a line.

    Touch vs break are SEPARATE tolerances (this is the fix for "the line passes
    under a peak yet isn't broken"):
    - a bar is **OVER** the line if its extreme pierces past it by more than
      BREAK_TOL (a real poke through — tight, ~0.15%).
    - a **touch** is the extreme reaching the line from the approach side within
      the wider TOL_PCT band WITHOUT going over (i.e. came up to resistance / down
      to support and did not break it).

    A line is rejected outright (not a trendline) if a run of >= INTERIOR_BREAK_BARS
    interior bars are OVER it — a peak pokes through BETWEEN the two anchors. Going
    forward it is live until a run of >= BREAK_OVER_BARS bars go OVER it.
    """
    span = b.idx - a.idx
    if span < MIN_SEP:
        return None
    slope = (b.price - a.price) / span
    if (is_high and slope >= 0.0) or (not is_high and slope <= 0.0):
        return None
    if abs(slope) / b.price < MIN_ANGLE_PCT:
        return None

    def over(idx_: int, line_v: float) -> bool:
        """True if bar idx_'s extreme pokes OVER the line by more than BREAK_TOL."""
        return (
            highs[idx_] > line_v * (1.0 + BREAK_TOL)
            if is_high
            else lows[idx_] < line_v * (1.0 - BREAK_TOL)
        )

    # Interior validity: no peak may poke through BETWEEN the two anchors.
    run = 0
    for i in range(a.idx + 1, b.idx):
        if over(i, a.price + slope * (i - a.idx)):
            run += 1
            if run >= INTERIOR_BREAK_BARS:
                return None
        else:
            run = 0

    proj_lo, proj_hi = SIZE, int(VALID_FRAC * span)
    half_lo = max(proj_lo, span // 2)
    first_t = half_t = broken = -1
    last_live = b.idx
    over_run = 0
    for proj in range(proj_lo, proj_hi + 1):
        t = b.idx + proj
        if t >= n:
            break
        line_t = b.price + slope * proj
        if over(t, line_t):
            over_run += 1
            if over_run >= BREAK_OVER_BARS:
                broken = t - over_run + 1  # first bar of the over-run
                break
            continue  # pierced bar: not a touch, line not extended past it
        over_run = 0
        last_live = t
        # Touch: reached the line from the approach side within TOL_PCT, not over.
        band = TOL_PCT * line_t
        ext = highs[t] if is_high else lows[t]
        if abs(ext - line_t) <= band:
            if first_t < 0:
                first_t = t
            if half_t < 0 and proj >= half_lo:
                half_t = t
            if first_t >= 0 and half_t >= 0:
                break
    return ScanResult(slope, first_t, half_t, broken, last_live)


def _iter_lines(
    highs: list[float], lows: list[float], closes: list[float], cpeaks: list[CPeak]
) -> Iterator[tuple[CPeak, CPeak, ScanResult]]:
    """Yield (A, B, scan) for every valid fan line — the single source of truth.

    For each confirmed peak B, anchor A is the outstanding (extreme) same-type
    confirmed peak within the trailing WINDOW_BARS before B (auto-re-anchors when
    a new extreme appears). Both the probe (:func:`build_fan_fires`) and the
    viewer (:func:`fan_lines`) consume this, so they never drift.
    """
    n = len(highs)
    for is_high in (True, False):
        idxs = [p.idx for p in cpeaks if p.is_high == is_high]
        pks = [p for p in cpeaks if p.is_high == is_high]
        for bk, b in enumerate(pks):
            w0 = b.idx - WINDOW_BARS
            lo_pos = bisect.bisect_left(idxs, w0)
            cand = pks[lo_pos:bk]
            if not cand:
                continue
            a = max(cand, key=lambda p: p.price) if is_high else min(cand, key=lambda p: p.price)
            sc = _scan_line(highs, lows, closes, n, a, b, is_high=is_high)
            if sc is not None:
                yield a, b, sc


def build_fan_fires(
    highs: list[float], lows: list[float], closes: list[float], cpeaks: list[CPeak]
) -> tuple[list[Fire], list[Fire], int]:
    """Generate (first-touch fires, half-touch fires, n_lines) from the fan."""
    first: list[Fire] = []
    half: list[Fire] = []
    n_lines = 0
    for a, b, sc in _iter_lines(highs, lows, closes, cpeaks):
        n_lines += 1
        side = Side.SHORT if b.is_high else Side.LONG
        if sc.first_touch >= 0:
            first.append(Fire(sc.first_touch, side, a.idx))
        if sc.half_touch >= 0:
            half.append(Fire(sc.half_touch, side, a.idx))
    first.sort(key=lambda f: f.bar)
    half.sort(key=lambda f: f.bar)
    return first, half, n_lines


def fan_lines(
    highs: list[float], lows: list[float], closes: list[float], cpeaks: list[CPeak]
) -> list[Line]:
    """Same fan as :func:`build_fan_fires`, but each line's geometry (for the viewer)."""
    return [
        Line(a.idx, a.price, b.idx, b.price, sc.slope, b.is_high,
             sc.last_live - b.idx, sc.broken_at, sc.first_touch, sc.half_touch)
        for a, b, sc in _iter_lines(highs, lows, closes, cpeaks)
    ]


def walk_exit(
    opens: list[float], highs: list[float], lows: list[float], closes: list[float],
    fire: Fire, legs: tuple[float, ...],
) -> tuple[float, int] | None:
    """Walk ZsTpSl from open[fire+1] bar-by-bar; return (return_pct_net, exit_idx).

    Matches src/simulator/simulator.py: fill at open[fire+1], first exit check at
    fire+2 (entry bar not evaluated), bars_held incremented after each no-exit bar.
    """
    f = fire.bar
    if f + 1 >= len(opens):
        return None
    entry = opens[f + 1]
    cfg = EXIT.exit_config(ExitContext(side=fire.side, entry_price=closes[f], zs_history=legs))
    pos = OpenPosition(side=fire.side, entry_price=entry, entry_atr=0.0)

    from src.core.types import Bar  # local import keeps module load light

    exit_price = closes[-1]
    exit_idx = len(opens) - 1
    for j in range(f + 2, len(opens)):
        bar = Bar(timestamp=None, open=opens[j], high=highs[j], low=lows[j], close=closes[j], volume=0.0)  # type: ignore[arg-type]
        res = evaluate_exit(pos, bar, cfg)
        if res is not None:
            exit_price = res[1]
            exit_idx = j
            break
        pos.bars_held += 1
    signed = fire.side.sign * (exit_price - entry) / entry
    return signed - 2.0 * FEE_RATE, exit_idx


def _stats(rets: list[float]) -> tuple[int, float, float, float]:
    """(n, net_pnl_jpy_proxy, sharpe, win_rate). PnL proxy = sum(ret)·notional≈."""
    if not rets:
        return 0, 0.0, 0.0, 0.0
    a = np.array(rets, dtype=float)
    std = float(a.std(ddof=1)) if a.size > 1 else 0.0
    sharpe = float(a.mean() / std) if std > 0.0 else 0.0
    win = float((a > 0.0).mean())
    return a.size, float(a.sum()), sharpe, win


def main() -> None:
    df = load_cache(Timeframe.M5, product="GMO_BTC_JPY").to_frame()
    opens = df["open"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    closes = df["close"].tolist()
    print(f"GMO 5m: {len(df)} bars  {df.index[0]} -> {df.index[-1]}")

    cpeaks = confirmed_peaks(highs, lows)
    kn, legs_tbl = _leg_table(cpeaks)
    first, half, n_lines = build_fan_fires(highs, lows, closes, cpeaks)
    n_anchors = len({f.anchor_a for f in first})
    print(f"confirmed peaks={len(cpeaks)}  fan lines={n_lines}  "
          f"distinct anchors(first)={n_anchors}")
    print(f"fires: first-touch={len(first)}  half-touch={len(half)}\n")

    print(f"{'arm':10} {'view':12} {'n':>5} {'sum_ret':>9} {'sharpe':>8} {'win':>6}")
    print("-" * 54)
    for name, fires in (("first", first), ("half", half)):
        # (1) entry-quality: every fire walked independently.
        eq: list[float] = []
        for fr in fires:
            r = walk_exit(opens, highs, lows, closes, fr, _legs_at(kn, legs_tbl, fr.bar))
            if r is not None:
                eq.append(r[0])
        n, s, sh, w = _stats(eq)
        print(f"{name:10} {'entry-qual':12} {n:>5} {s:>9.4f} {sh:>8.3f} {w:>6.2f}")
        # (2) portfolio: single-position flat-only, skip while busy.
        pf: list[float] = []
        free_until = -1
        for fr in fires:
            if fr.bar + 1 <= free_until:
                continue
            r = walk_exit(opens, highs, lows, closes, fr, _legs_at(kn, legs_tbl, fr.bar))
            if r is None:
                continue
            pf.append(r[0])
            free_until = r[1]
        n, s, sh, w = _stats(pf)
        net_jpy = sum(rr * LOT * closes[0] for rr in pf)  # rough JPY scale
        print(f"{name:10} {'portfolio':12} {n:>5} {s:>9.4f} {sh:>8.3f} {w:>6.2f}"
              f"   net~{net_jpy:.0f}JPY")
    print("\nGate: build detector only if first/portfolio has net>0 AND sharpe>=+0.10.")
    print("Falsifier: if half/portfolio sharpe >= first/portfolio sharpe, the "
          "span/2-wait is vindicated.")


if __name__ == "__main__":
    main()
