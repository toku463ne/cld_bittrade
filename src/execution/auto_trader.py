"""Auto-trader — DRY-RUN: compute the desired book and the actions to reconcile it.

Each run (cron hourly), for every configured book it: pulls recent closed GMO bars,
replays the strategy to its **current desired state** (open positions + ratchet
stops/targets, pending market entries, resting limit orders), reads the **live**
GMO positions/orders, and logs the **intended actions** to make the exchange match
the desired state. It is **dry-run only** — it places no orders. This is the safe
way to watch the loop's logic against the real market before granting it order power.

Run (read-only; needs USE_LIVE_API=true for the live-position comparison, else the
desired book is still computed and the live side shows "n/a")::

    uv run --env-file .env.dev python -m src.execution.auto_trader

Live execution (placing/cancelling via the verified gmo_client primitives) is the
next iteration, behind the same USE_LIVE_API + ALLOW_ORDERS + --execute gates.
"""

from __future__ import annotations

import os
from collections import Counter

from loguru import logger

from src.config import get_settings
from src.core.types import Side
from src.execution.gmo_client import LEVERAGE_MIN_SIZE, gmo_account_client_from_settings
from src.execution.live_bars import recent_bars
from src.logging_setup import configure_logging
from src.simulator import MultiSimulator
from src.simulator.multi_simulator import LiveBookState
from src.strategy.registry import get_strategy

# Default books (PC/full): combo_dp_ver = dp+ver shared BTC book; density_pullback_xrp
# = the XRP variant. (ETH dropped: redundant — see portfolio.md.) Override per-deploy
# with the AUTO_BOOKS env var, "name:symbol[:slots],...". e.g. prod first trade:
#   AUTO_BOOKS=density_pullback_xrp:XRP_JPY:1   (one slot, min size).
DEFAULT_BOOKS: list[tuple[str, str, int | None]] = [
    ("combo_dp_ver", "BTC_JPY", None),
    ("density_pullback_xrp", "XRP_JPY", None),
]


def _books() -> list[tuple[str, str, int | None]]:
    """Parse AUTO_BOOKS (``name:symbol[:slots],...``), else the defaults."""
    raw = os.environ.get("AUTO_BOOKS", "").strip()
    if not raw:
        return DEFAULT_BOOKS
    out: list[tuple[str, str, int | None]] = []
    for item in raw.split(","):
        parts = item.split(":")
        if len(parts) < 2:
            raise ValueError(f"bad AUTO_BOOKS entry {item!r} (need name:symbol[:slots])")
        slots = int(parts[2]) if len(parts) > 2 and parts[2] else None
        out.append((parts[0], parts[1], slots))
    return out


def _desired(strategy_name: str, symbol: str, slots: int | None) -> LiveBookState:
    """Replay the strategy on recent closed bars -> its current desired book."""
    bars = recent_bars(symbol)
    if not bars:
        raise RuntimeError(f"no bars fetched for {symbol}")
    strat = get_strategy(strategy_name)
    if slots is not None:
        strat.max_slots = slots  # per-deploy concurrency cap (e.g. 1 for the first trade)
    state = MultiSimulator(strat, size=LEVERAGE_MIN_SIZE.get(symbol, 0.001)).live_state(bars)
    logger.info("{} [{}]: {} bars to {}; desired book = {} open, {} pending, {} resting",
                strategy_name, symbol, len(bars), bars[-1].timestamp,
                len(state.positions), len(state.pending_entries), len(state.working_orders))
    return state


def _report(symbol: str, state: LiveBookState, *, live: bool) -> None:
    """Log the desired book, the live book, and the intended reconcile actions."""
    last_idx = "now"
    # --- desired ---
    for p in state.positions:
        logger.info("  DESIRED hold {} {} entry@{:.4g} stop@{} tp@{} held={}bar",
                    symbol, p.side.name, p.entry_price,
                    f"{p.current_stop:.4g}" if p.current_stop else "-",
                    f"{p.target:.4g}" if p.target else "-", p.bars_held)
    for sig in state.pending_entries:
        logger.info("  DESIRED entry (next-bar MARKET) {} {}", symbol, sig.side.name)
    for sig, price, _exp in state.working_orders:
        logger.info("  DESIRED resting LIMIT {} {} @ {:.4g}", symbol, sig.side.name, price)

    desired_pos = Counter(p.side for p in state.positions)

    # --- live + diff ---
    if not live:
        logger.info("  LIVE: n/a (USE_LIVE_API=false) — desired book only")
        return
    client = gmo_account_client_from_settings()
    live_positions = client.get_open_positions(symbol)
    live_orders = client.get_active_orders(symbol)
    live_pos = Counter(
        Side.LONG if str(p.get("side")).upper() == "BUY" else Side.SHORT for p in live_positions
    )
    logger.info("  LIVE {}: {} positions, {} active orders", symbol, len(live_positions), len(live_orders))
    for side in (Side.LONG, Side.SHORT):
        d, lv = desired_pos.get(side, 0), live_pos.get(side, 0)
        if d > lv:
            logger.info("  ACTION[dry-run] {} {}: OPEN {} more (entries via the orders above)",
                        symbol, side.name, d - lv)
        elif lv > d:
            logger.info("  ACTION[dry-run] {} {}: CLOSE {} (strategy no longer wants them)",
                        symbol, side.name, lv - d)
        else:
            logger.info("  OK {} {}: desired == live ({})", symbol, side.name, d)
    n_desired_orders = len(state.pending_entries) + len(state.working_orders)
    if n_desired_orders != len(live_orders):
        logger.info("  ACTION[dry-run] {}: reconcile orders (desired {} vs live {})",
                    symbol, n_desired_orders, len(live_orders))
    _ = last_idx


def main() -> None:
    """Compute + log the desired book and reconcile actions for all books (dry-run)."""
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.warning("AUTO-TRADER DRY-RUN — computes intended actions, places NO orders.")
    live = settings.use_live_api
    for name, symbol, slots in _books():
        try:
            state = _desired(name, symbol, slots)
            _report(symbol, state, live=live)
        except Exception as e:  # noqa: BLE001 — one book failing must not kill the rest
            logger.error("{} [{}] failed: {}", name, symbol, e)


if __name__ == "__main__":
    main()
