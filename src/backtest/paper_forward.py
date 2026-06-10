"""Forward (lockbox) paper-trade evaluator for a shipped strategy.

`density_pullback` passed the ship gate, but its exit was tuned on the full 5y and
both ship gates were revised during that work — so per ``evaluation_criteria.md`` §6.5
the only *honest* final estimate is performance on data the strategy never touched.
This runner freezes a **lockbox boundary** at the tuning-data cutoff and scores the
strategy on **bars strictly after it** — the genuine forward record, which accrues as
fresh GMO data is imported (``python -m src.data.import_gmo``). It is *paper*: it runs
the normal simulator, places no orders, and reads only the public backtest data.

Honesty rules baked in:

- The boundary is a frozen constant (the cache's last bar at lockbox creation), so the
  forward set can only grow and is never silently re-tuned.
- The strategy still sees full history for warm-up; only trades **entered after the
  boundary** and the **post-boundary equity path** are scored.
- Below a minimum sample (trades and calendar span) the verdict is withheld
  ("ACCRUING") — a forward test confirms nothing until it has enough data.

Re-run as data accrues::

    uv run --env-file .env.bt python -m src.data.import_gmo --from <recent> --to <today> --timeframe 1h
    uv run --env-file .env.bt python -m src.backtest.paper_forward --strategy density_pullback --product GMO_BTC_JPY
"""

from __future__ import annotations

import argparse

import pandas as pd
from loguru import logger

from src.backtest.metrics import annualized_sharpe_from_levels, portfolio_metrics
from src.core.types import Timeframe
from src.data.cache import load_cache
from src.logging_setup import configure_logging
from src.simulator.multi_simulator import MultiSimulator
from src.strategy.registry import get_strategy

# Frozen lockbox boundaries, PER STRATEGY: the last bar present in the cache when each
# strategy's CURRENT logic was declared ship=True (its tuning cutoff). Bars at or before a
# strategy's boundary are "seen"; only bars strictly after it count as forward.
# DO NOT move an existing entry — moving it re-tunes that strategy's test. A strategy whose
# shipped LOGIC materially changes earns a NEW (later) boundary at its re-ship cutoff, so its
# forward record never overlaps the data its new logic was selected on.
# Keys are either a strategy name (applies on the default/BTC product) or a
# (strategy, product) pair for product-specific records — looked up most-specific first.
LOCKBOX_BOUNDARIES: dict[str | tuple[str, str], tuple[pd.Timestamp, str]] = {
    # density_pullback RE-ship (max_base_bars=64 stale-box gate adopted 2026-06-11 after
    # ETH replication): the 64 cell was selected on BTC data through the 2026-06-07 22:00
    # cache cutoff, so the forward clock RESTARTS there (the prior 2026-06-02 record, ~5
    # days, was sacrificed at adoption — clocks were cheap).
    "density_pullback": (pd.Timestamp("2026-06-07 22:00:00+09:00"), "2026-06-11"),
    # vol_expansion_ride RE-ship (skip_contra_extreme=1 two-sided-burst filter): the contra
    # filter was selected on a walk-forward over data through the 2026-06-07 22:00 cache
    # cutoff, so the forward clock restarts there (re-frozen 2026-06-10). Earlier bars were
    # seen by that selection.
    "vol_expansion_ride": (pd.Timestamp("2026-06-07 22:00:00+09:00"), "2026-06-10"),
    # combo_dp_ver (shared 12-slot book of the two above): re-frozen 2026-06-11 with the dp
    # component's max_base_bars=64 adoption (same data cutoff — no newer BTC bars were seen).
    # This is the book that would actually trade live.
    "combo_dp_ver": (pd.Timestamp("2026-06-07 22:00:00+09:00"), "2026-06-11"),
    # density_pullback on GMO_ETH_JPY (per-PRODUCT key): the transfer-test promote decision
    # (2026-06-11) and the max_base=64 ETH replication both consumed ETH data through the
    # 2026-06-10 23:00 ETH cache end, so its forward clock starts there.
    ("density_pullback", "GMO_ETH_JPY"): (pd.Timestamp("2026-06-10 23:00:00+09:00"), "2026-06-11"),
}
# Fallback for any strategy without an explicit entry (the original density boundary).
DEFAULT_LOCKBOX: tuple[pd.Timestamp, str] = (pd.Timestamp("2026-06-02 05:00:00+09:00"), "2026-06-07")

MIN_FWD_TRADES = 20  # below this, a forward Sharpe is too noisy to read
MIN_FWD_DAYS = 60  # and the span must cover a couple of months


def run(strategy_name: str, tf: Timeframe, *, product: str | None) -> None:
    """Score ``strategy_name`` on the post-lockbox forward bars; withhold if scant."""
    cache = load_cache(tf, product=product)
    bars = cache.bars
    if not bars:
        raise RuntimeError("no bars in cache")
    ppy = (365 * 24 * 3600) / tf.seconds
    # Most-specific first: (strategy, product) -> strategy -> default.
    boundary, frozen_on = (
        LOCKBOX_BOUNDARIES.get((strategy_name, product or ""))
        or LOCKBOX_BOUNDARIES.get(strategy_name)
        or DEFAULT_LOCKBOX
    )

    # Index of the first forward bar (strictly after the frozen boundary).
    fwd_start = next(
        (i for i, b in enumerate(bars) if pd.Timestamp(b.timestamp) > boundary),
        len(bars),
    )
    n_fwd_bars = len(bars) - fwd_start
    fwd_days = n_fwd_bars * tf.seconds / 86400.0
    logger.info(
        "{} forward/lockbox: boundary {} (frozen {}); cache ends {}",
        strategy_name, boundary, frozen_on, bars[-1].timestamp,
    )
    logger.info("  forward bars: {} (~{:.1f} days)", n_fwd_bars, fwd_days)

    # Run the strategy over the FULL series (full warm-up/history); score only the
    # forward slice of the equity path and trades entered after the boundary.
    res = MultiSimulator(get_strategy(strategy_name)).run(bars)
    fwd_curve = res.equity_curve[fwd_start:]
    fwd_trades = [t for t in res.trades if pd.Timestamp(t.entry_time) > boundary]

    es = annualized_sharpe_from_levels(fwd_curve, ppy) if len(fwd_curve) >= 3 else 0.0
    bh = annualized_sharpe_from_levels(
        [b.close for b in bars[fwd_start:]], ppy, pct=True
    ) if n_fwd_bars >= 3 else 0.0
    m = portfolio_metrics(fwd_trades) if fwd_trades else None

    logger.info("  forward trades (entered post-boundary): {}", len(fwd_trades))
    if m is not None:
        logger.info(
            "  forward eqSharpe {:+.3f} vs B&H {:+.3f} | ret {:+.4f} | DD {:.4f} | DR {:.3f}",
            es, bh, m.total_return, m.max_dd, m.win_rate,
        )

    enough = len(fwd_trades) >= MIN_FWD_TRADES and fwd_days >= MIN_FWD_DAYS
    if not enough:
        logger.warning(
            "  VERDICT: ACCRUING — need >= {} trades AND >= {} days (have {} / {:.0f}). "
            "Re-import fresh data and re-run; no confirmation until then.",
            MIN_FWD_TRADES, MIN_FWD_DAYS, len(fwd_trades), fwd_days,
        )
        return
    confirmed = es >= bh
    logger.info(
        "  VERDICT: {} — forward eqSharpe {:+.3f} {} B&H {:+.3f}",
        "CONFIRMED" if confirmed else "NOT CONFIRMED",
        es, ">=" if confirmed else "<", bh,
    )


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Forward/lockbox paper-trade evaluator.")
    parser.add_argument("--strategy", default="density_pullback")
    parser.add_argument("--timeframe", choices=[tf.value for tf in Timeframe], default="1h")
    parser.add_argument("--product", default=None)
    args = parser.parse_args()
    configure_logging()
    run(args.strategy, Timeframe(args.timeframe), product=args.product)


if __name__ == "__main__":
    main()
