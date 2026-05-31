"""Preliminary grid tune for ``zigzag_bounce`` (size / mid_size / tp / sl).

Exploratory only: with ~1 month of data this OVERFITS and has no train/test
hold-out — it is a sanity sweep to see which settings are even plausible, to be
re-run once months of history exist. Ranks combos by net total return (all
figures NET of fees) and shows trade count / Sharpe / win-rate / max DD.

Usage::

    uv run --env-file .env.bt python -m src.backtest.analysis.tune_zigzag_bounce --timeframe 1h
    uv run --env-file .env.bt python -m src.backtest.analysis.tune_zigzag_bounce --timeframe 5m --quick
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from loguru import logger

from src.backtest.metrics import portfolio_metrics
from src.config import get_settings
from src.core.types import Timeframe
from src.data.cache import load_cache
from src.logging_setup import configure_logging
from src.simulator import Simulator
from src.strategy.zigzag_bounce import ZigzagBounceStrategy

# Full grid (mid_size < size enforced below). tp/sl are multiples of the ZS band
# (one zigzag leg ~2.5% of price on 1h), so values >= ~1.0 rarely bind before the
# time stop — keep them fractional so TP/SL actually drive exits.
SIZES = [6, 7, 8, 10, 14]
MIDS = [3, 4]
TPS = [0.5, 0.7, 1.0]
SLS = [0.5, 0.7, 1.0]
MAX_BARS = [12, 24, 48, 72]  # "trade age" / time stop (bars)
# Reduced grid for slow (5m) runs.
QUICK_SIZES = [8, 10, 14]
QUICK_MIDS = [3, 4]
QUICK_TPS = [0.5, 0.7]
QUICK_SLS = [0.5, 0.7]
QUICK_MAXBARS = [24, 48]
# Level-matching toggles, swept only with --sweep-levels (else defaults: fixed
# tol_pct, same-type). (tol_leg_frac, reverse_levels, require_break).
LEG_FRACS: list[float | None] = [None, 0.25, 0.5]
REV_MODES: list[tuple[bool, bool]] = [(False, True), (True, True), (True, False)]
# MAD high-side leg clip for the ZS band, swept only with --sweep-winsor
# (else default off). None = off; values are k in MAD-sigmas (~3 = 3-sigma).
WINSOR_KS: list[float | None] = [None, 2.5, 3.0]
# Dominant-level lookback (bars), swept only with --sweep-dominant (else off).
# None = off; @1h: 96≈4d, 120≈5d, 168≈1wk, 240≈10d. NOTE 240 > widest window
# (180) enlarges warmup and drops early fires -- not apples-to-apples with off.
DOMINANT_WINDOWS: list[int | None] = [None, 96, 120, 168, 240]
# wall_match lookbacks, swept only with --sweep-wall (else off). None = wall_match
# off (today's extreme-based selection); ints enable wall_match with that window.
WALL_WINDOWS: list[int | None] = [None, 96, 120, 168, 180]


@dataclass(frozen=True, slots=True)
class Row:
    size: int
    mid: int
    tp: float
    sl: float
    max_bars: int
    leg_frac: float | None
    reverse: bool
    req_break: bool
    winsor: float | None
    dominant: int | None
    dom_rev: bool
    wall: int | None
    n_trades: int
    total_return: float
    sharpe: float
    win_rate: float
    max_dd: float


def _grid(
    quick: bool,
    sizes: list[int] | None = None,
    mids: list[int] | None = None,
    sweep_levels: bool = False,
    sweep_winsor: bool = False,
    sweep_dominant: bool = False,
    sweep_wall: bool = False,
) -> list[
    tuple[
        int, int, float, float, int, float | None, bool, bool, float | None,
        int | None, bool, int | None,
    ]
]:
    base_sizes, base_mids, tps, sls, mbs = (
        (QUICK_SIZES, QUICK_MIDS, QUICK_TPS, QUICK_SLS, QUICK_MAXBARS)
        if quick
        else (SIZES, MIDS, TPS, SLS, MAX_BARS)
    )
    legs = LEG_FRACS if sweep_levels else [None]
    revs = REV_MODES if sweep_levels else [(False, True)]
    winsors = WINSOR_KS if sweep_winsor else [None]
    # (dominant_window, dominant_reverse) modes: each non-None window gets both
    # reverse off/on; None stays single (reverse is a no-op without a window).
    if sweep_dominant:
        dom_modes: list[tuple[int | None, bool]] = [(None, False)]
        for d in DOMINANT_WINDOWS:
            if d is not None:
                dom_modes += [(d, False), (d, True)]
    else:
        dom_modes = [(None, False)]
    # wall_match lookbacks: None = off (extreme-based selection); int = on@window.
    walls = WALL_WINDOWS if sweep_wall else [None]
    return [
        (s, m, tp, sl, mb, leg, rev, brk, win, dom, drev, wall)
        for s in (sizes or base_sizes)
        for m in (mids or base_mids)
        if m < s
        for tp in tps
        for sl in sls
        for mb in mbs
        for leg in legs
        for (rev, brk) in revs
        for win in winsors
        for (dom, drev) in dom_modes
        for wall in walls
    ]


def tune(
    timeframe: Timeframe,
    *,
    quick: bool,
    top: int,
    sizes: list[int] | None = None,
    mids: list[int] | None = None,
    sweep_levels: bool = False,
    sweep_winsor: bool = False,
    sweep_dominant: bool = False,
    sweep_wall: bool = False,
) -> list[Row]:
    """Run the sweep and return rows sorted by net total return (desc)."""
    bars = load_cache(timeframe).bars
    if not bars:
        raise RuntimeError(f"No {timeframe.value} bars; collect history first.")
    combos = _grid(quick, sizes, mids, sweep_levels, sweep_winsor, sweep_dominant, sweep_wall)
    logger.info("Tuning zigzag_bounce on {} {} bars over {} combos",
                len(bars), timeframe.value, len(combos))

    rows: list[Row] = []
    for size, mid, tp, sl, mb, leg, rev, brk, win, dom, drev, wall in combos:
        strat = ZigzagBounceStrategy(
            size=size, mid_size=mid, tp_mult=tp, sl_mult=sl, max_bars=mb,
            tol_leg_frac=leg, reverse_levels=rev, require_break=brk,
            winsorize_k=win, dominant_window=dom, dominant_reverse=drev,
            wall_match=wall is not None, wall_window=wall,
        )
        trades = Simulator(strat).run(bars).trades
        m = portfolio_metrics(trades)
        rows.append(
            Row(size, mid, tp, sl, mb, leg, rev, brk, win, dom, drev, wall, m.n_trades,
                m.total_return, m.sharpe, m.win_rate, m.max_dd)
        )

    rows.sort(key=lambda r: r.total_return, reverse=True)
    return rows[:top]


def _print_table(title: str, rows: list[Row]) -> None:
    print(f"\n=== {title} ===")
    print(f"{'size':>4} {'mid':>3} {'tp':>4} {'sl':>4} {'age':>4} {'leg':>4} {'rev':>3} "
          f"{'brk':>3} {'win':>4} {'dom':>4} {'drv':>3} {'wall':>4} | {'trades':>6} "
          f"{'net_ret':>9} {'sharpe':>7} {'win%':>5} {'maxDD':>7}")
    for r in rows:
        leg = "-" if r.leg_frac is None else f"{r.leg_frac:.2f}"
        win = "-" if r.winsor is None else f"{r.winsor:.1f}"
        dom = "-" if r.dominant is None else f"{r.dominant}"
        wall = "-" if r.wall is None else f"{r.wall}"
        print(f"{r.size:>4} {r.mid:>3} {r.tp:>4.1f} {r.sl:>4.1f} {r.max_bars:>4} {leg:>4} "
              f"{('Y' if r.reverse else 'n'):>3} {('Y' if r.req_break else 'n'):>3} "
              f"{win:>4} {dom:>4} {('Y' if r.dom_rev else 'n'):>3} {wall:>4} | {r.n_trades:>6} "
              f"{r.total_return:>9.4f} {r.sharpe:>7.3f} {r.win_rate:>5.2f} {r.max_dd:>7.4f}")


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Grid-tune zigzag_bounce (exploratory).")
    parser.add_argument("--timeframe", choices=[tf.value for tf in Timeframe], default="1h")
    parser.add_argument("--quick", action="store_true", help="Reduced grid (for slow 5m).")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--min-trades", type=int, default=4,
                        help="Hide combos with fewer than this many trades.")
    parser.add_argument("--size", type=int, default=None, help="Restrict to one size.")
    parser.add_argument("--mid", type=int, default=None, help="Restrict to one mid_size.")
    parser.add_argument(
        "--sweep-levels", action="store_true",
        help="Also sweep tol_leg_frac {None,0.25,0.5} and reverse/break modes "
        "(9x combos — combine with --size/--mid to keep it tractable).",
    )
    parser.add_argument(
        "--sweep-winsor", action="store_true",
        help="Also sweep ZS-band MAD leg-clip winsorize_k {None,2.5,3.0} (3x combos).",
    )
    parser.add_argument(
        "--sweep-dominant", action="store_true",
        help="Also sweep dominant_window {None,96,120,168,240} x dominant_reverse "
        "{off,on} (9 modes; the `drv` column). Note 240 > widest window enlarges "
        "warmup (not apples-to-apples with off).",
    )
    parser.add_argument(
        "--sweep-wall", action="store_true",
        help="Also sweep wall_match: wall_window {off,96,120,168,180} (the `wall` "
        "column). wall_match replaces the extreme-based selection with nearest-wall.",
    )
    args = parser.parse_args()

    configure_logging(get_settings().log_level)
    rows = tune(
        Timeframe(args.timeframe),
        quick=args.quick,
        top=10_000,
        sizes=[args.size] if args.size else None,
        mids=[args.mid] if args.mid else None,
        sweep_levels=args.sweep_levels,
        sweep_winsor=args.sweep_winsor,
        sweep_dominant=args.sweep_dominant,
        sweep_wall=args.sweep_wall,
    )

    # Best tp/sl per (size, mid) so EVERY size is visible (not just the winners).
    best_by_pair: dict[tuple[int, int], Row] = {}
    for r in rows:
        key = (r.size, r.mid)
        if key not in best_by_pair or r.total_return > best_by_pair[key].total_return:
            best_by_pair[key] = r
    by_pair = sorted(best_by_pair.values(), key=lambda r: (r.size, r.mid))
    _print_table(
        f"best tp/sl per (size, mid) — {args.timeframe}, net of fees", by_pair
    )

    shown = [r for r in rows if r.n_trades >= args.min_trades][: args.top]
    _print_table(
        f"top combos — {args.timeframe} (>= {args.min_trades} trades, net of fees)",
        shown,
    )
    print("\nNOTE: exploratory, no train/test split, tiny sample — overfits. "
          "Re-run once months of history exist.")


if __name__ == "__main__":
    main()
