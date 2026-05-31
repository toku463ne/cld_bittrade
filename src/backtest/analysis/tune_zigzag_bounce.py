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


@dataclass(frozen=True, slots=True)
class Row:
    size: int
    mid: int
    tp: float
    sl: float
    max_bars: int
    n_trades: int
    total_return: float
    sharpe: float
    win_rate: float
    max_dd: float


def _grid(quick: bool) -> list[tuple[int, int, float, float, int]]:
    sizes, mids, tps, sls, mbs = (
        (QUICK_SIZES, QUICK_MIDS, QUICK_TPS, QUICK_SLS, QUICK_MAXBARS)
        if quick
        else (SIZES, MIDS, TPS, SLS, MAX_BARS)
    )
    return [
        (s, m, tp, sl, mb)
        for s in sizes
        for m in mids
        if m < s
        for tp in tps
        for sl in sls
        for mb in mbs
    ]


def tune(timeframe: Timeframe, *, quick: bool, top: int) -> list[Row]:
    """Run the sweep and return rows sorted by net total return (desc)."""
    bars = load_cache(timeframe).bars
    if not bars:
        raise RuntimeError(f"No {timeframe.value} bars; collect history first.")
    combos = _grid(quick)
    logger.info("Tuning zigzag_bounce on {} {} bars over {} combos",
                len(bars), timeframe.value, len(combos))

    rows: list[Row] = []
    for size, mid, tp, sl, mb in combos:
        strat = ZigzagBounceStrategy(
            size=size, mid_size=mid, tp_mult=tp, sl_mult=sl, max_bars=mb
        )
        trades = Simulator(strat).run(bars).trades
        m = portfolio_metrics(trades)
        rows.append(
            Row(size, mid, tp, sl, mb, m.n_trades, m.total_return, m.sharpe,
                m.win_rate, m.max_dd)
        )

    rows.sort(key=lambda r: r.total_return, reverse=True)
    return rows[:top]


def _print_table(title: str, rows: list[Row]) -> None:
    print(f"\n=== {title} ===")
    print(f"{'size':>4} {'mid':>3} {'tp':>4} {'sl':>4} {'age':>4} | {'trades':>6} "
          f"{'net_ret':>9} {'sharpe':>7} {'win%':>5} {'maxDD':>7}")
    for r in rows:
        print(f"{r.size:>4} {r.mid:>3} {r.tp:>4.1f} {r.sl:>4.1f} {r.max_bars:>4} | "
              f"{r.n_trades:>6} {r.total_return:>9.4f} {r.sharpe:>7.3f} "
              f"{r.win_rate:>5.2f} {r.max_dd:>7.4f}")


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Grid-tune zigzag_bounce (exploratory).")
    parser.add_argument("--timeframe", choices=[tf.value for tf in Timeframe], default="1h")
    parser.add_argument("--quick", action="store_true", help="Reduced grid (for slow 5m).")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--min-trades", type=int, default=4,
                        help="Hide combos with fewer than this many trades.")
    args = parser.parse_args()

    configure_logging(get_settings().log_level)
    rows = tune(Timeframe(args.timeframe), quick=args.quick, top=10_000)

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
