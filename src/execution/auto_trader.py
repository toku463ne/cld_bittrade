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

import argparse
import os
from collections import Counter

from loguru import logger

from src.config import get_settings
from src.core.types import Side
from src.execution.gmo_client import (
    LEVERAGE_MIN_SIZE,
    gmo_account_client_from_settings,
    gmo_trading_client_from_settings,
)
from src.execution.live_bars import recent_bars
from src.execution.live_executor import reconcile
from src.execution.order_log import snapshot
from src.execution.risk import book_within_notional_cap, peak_exposure_jpy
from src.logging_setup import configure_logging
from src.simulator import MultiSimulator
from src.simulator.multi_simulator import LiveBookState
from src.strategy.registry import get_strategy

# Default books (PC/full): density_pullback = the BTC book; density_pullback_xrp = the
# XRP variant. (ETH dropped: redundant — see portfolio.md. combo_dp_ver dropped as the
# BTC book 2026-06-20: its only lift over plain density_pullback was the vol_expansion
# leg, which is OOS-dead once the trail phantom-fill is fixed — see the head-to-head in
# portfolio.md / trail-recalc-phantom-fill.) Override per-deploy with the AUTO_BOOKS env
# var, "name:symbol[:slots],...". e.g. prod first trade:
#   AUTO_BOOKS=density_pullback_xrp:XRP_JPY:1   (one slot, min size).
DEFAULT_BOOKS: list[tuple[str, str, int | None]] = [
    ("density_pullback", "BTC_JPY", None),
    ("density_pullback_xrp", "XRP_JPY", None),
]


def exec_max_slots() -> int:
    """Largest book the executor is authorised to trade this deploy (``EXEC_MAX_SLOTS``).

    Defaults to **1** — byte-for-byte today's behaviour — so raising the live slot count
    is a deliberate env change per rollout step, never a side effect of new code.
    """
    try:
        return max(1, int(os.environ.get("EXEC_MAX_SLOTS", "1")))
    except ValueError:
        logger.warning("EXEC_MAX_SLOTS={!r} is not an int — falling back to 1",
                       os.environ.get("EXEC_MAX_SLOTS"))
        return 1


def _books() -> list[tuple[str, str, int | None]]:
    """Parse AUTO_BOOKS (``name:symbol[:slots],...``), else the defaults.

    **Fails soft on purpose.** This runs before the per-book try in :func:`main`, so
    raising here would abort the whole run — and the safety-critical job of the trader is
    maintaining exits on positions that are already open. A config typo must never be the
    reason a live position stops being managed. Bad entries are therefore logged CRITICAL
    and dropped, or clamped to the safest interpretation, and the remaining books run.

    When ``EXEC_MAX_SLOTS > 1`` an omitted ``:slots`` would silently inherit the strategy
    class default (``density_pullback`` = 12), which must never decide a live book's size.
    Such an entry is **clamped to 1 slot** — the conservative reading that still keeps the
    book's positions maintained. If the live account holds more than that, the executor's
    anomaly halt catches it loudly rather than trading on a guess.

    Returns:
        The usable books; possibly empty if every entry was unusable.
    """
    raw = os.environ.get("AUTO_BOOKS", "").strip()
    if not raw:
        return DEFAULT_BOOKS
    cap = exec_max_slots()
    out: list[tuple[str, str, int | None]] = []
    for item in raw.split(","):
        parts = item.split(":")
        if len(parts) < 2 or not parts[0] or not parts[1]:
            logger.critical("AUTO_BOOKS entry {!r} is malformed (need name:symbol[:slots])"
                            " — SKIPPED, this book is NOT being managed", item)
            continue
        slots: int | None = None
        if len(parts) > 2 and parts[2]:
            try:
                slots = int(parts[2])
            except ValueError:
                logger.critical("AUTO_BOOKS entry {!r} has a non-numeric slot count — "
                                "SKIPPED, this book is NOT being managed", item)
                continue
            if slots < 1:
                logger.critical("AUTO_BOOKS entry {!r} has slots < 1 — SKIPPED", item)
                continue
        if slots is None and cap > 1:
            logger.critical(
                "AUTO_BOOKS entry {!r} omits :slots while EXEC_MAX_SLOTS={} — CLAMPING "
                "this book to 1 slot. The strategy default would otherwise decide the "
                "live book's size. Set the slot count explicitly.", item, cap)
            slots = 1
        out.append((parts[0], parts[1], slots))
    if not out:
        logger.critical("AUTO_BOOKS={!r} yielded no usable book — NOTHING is being "
                        "managed this run (open positions keep only the exits already "
                        "resting on the exchange)", raw)
    return out


def _desired(strategy_name: str, symbol: str, slots: int | None) -> tuple[LiveBookState, bool]:
    """Replay the strategy on recent closed bars -> its current desired book.

    Returns:
        ``(state, entries_allowed)``. ``entries_allowed`` is False when the book's peak
        occupancy would breach ``MAX_BOOK_NOTIONAL_JPY`` — the book is still reconciled
        (exits, ratchets, cleanup) but opens nothing new.
    """
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

    # Exposure ceiling. A breach must STOP NEW EXPOSURE, not abandon the book: skipping
    # it would leave already-open positions without a ratchet or orphan cleanup, and an
    # exposure cap that strands live positions is worse than the exposure it prevents.
    # (Same reasoning as the fail-soft AUTO_BOOKS parsing above.) The likely trigger is
    # raising :slots without raising the cap — e.g. BTC at 6 slots peaks near 61k JPY.
    entries_allowed, msg = book_within_notional_cap(symbol, state.max_slots, bars[-1].close)
    if entries_allowed:
        logger.info("  {}", msg)
    else:
        logger.critical("EXPOSURE CAP {}: {} — maintaining existing positions but "
                        "placing NO new entries. Raise MAX_BOOK_NOTIONAL_JPY or lower "
                        ":slots.", symbol, msg)
    # Per-run heartbeat — the desired book even when flat, for dense offline analysis.
    snapshot({
        "strategy": strategy_name,
        "symbol": symbol,
        "slots": slots,
        "max_slots": state.max_slots,
        "peak_notional": round(peak_exposure_jpy(symbol, state.max_slots, bars[-1].close)),
        "bar_time": str(state.last_bar_time),
        "close": bars[-1].close,
        "n_open": len(state.positions),
        "n_pending": len(state.pending_entries),
        "n_resting": len(state.working_orders),
        "positions": [
            {"side": p.side.name, "entry": p.entry_price, "stop": p.current_stop,
             "target": p.target, "held": p.bars_held}
            for p in state.positions
        ],
        "resting": [{"side": s.side.name, "price": pr} for s, pr, _ in state.working_orders],
        "entries_allowed": entries_allowed,
    })
    return state, entries_allowed


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
    """Reconcile each book to the exchange (dry-run unless --execute + ALLOW_ORDERS)."""
    ap = argparse.ArgumentParser(description="Auto-trader: reconcile desired book to GMO.")
    ap.add_argument("--execute", action="store_true",
                    help="Actually place/cancel/close orders (needs USE_LIVE_API + ALLOW_ORDERS). "
                         "Books up to EXEC_MAX_SLOTS (default 1) execute; larger ones are dry-run.")
    args = ap.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    want_exec = args.execute and settings.allow_orders
    if args.execute and not settings.allow_orders:
        logger.warning("--execute given but ALLOW_ORDERS=false -> DRY-RUN reconcile (no orders).")
    logger.warning("AUTO-TRADER ({}) — live_read={}", "EXECUTE" if want_exec else "DRY-RUN", settings.use_live_api)

    # Belt-and-braces: _books() already fails soft, but this call sits outside the
    # per-book try below, so ANY escape here would kill the run and stop every book
    # being maintained — the one outcome this loop must never have.
    try:
        books = _books()
    except Exception as e:  # noqa: BLE001 - config parsing must not abort the run
        logger.critical("AUTO_BOOKS parsing failed ({}) — NO books this run", e)
        books = []

    for name, symbol, slots in books:
        try:
            state, entries_allowed = _desired(name, symbol, slots)
            if not settings.use_live_api:
                _report(symbol, state, live=False)  # no exchange read possible
                continue
            # Authorise off state.max_slots (what the sim actually ran), never the parsed
            # `slots` — a book with no explicit count would otherwise slip past on None.
            book_slots = state.max_slots
            if book_slots <= exec_max_slots():
                exec_here = want_exec
                client = gmo_trading_client_from_settings() if exec_here else gmo_account_client_from_settings()
                reconcile(symbol, state, client, execute=exec_here,
                          allow_entries=entries_allowed)
            else:
                if want_exec:
                    logger.warning("{} [{}]: {}-slot book > EXEC_MAX_SLOTS={} — MONITOR-ONLY here",
                                   name, symbol, book_slots, exec_max_slots())
                _report(symbol, state, live=True)
        except Exception as e:  # noqa: BLE001 — one book failing must not kill the rest
            logger.error("{} [{}] failed: {}", name, symbol, e)


if __name__ == "__main__":
    main()
