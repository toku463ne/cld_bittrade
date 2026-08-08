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
from typing import Any

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


def _phantom_warning(fields: dict[str, Any]) -> str | None:
    """The phantom-slot warning for one heartbeat row, or None when there is nothing to say.

    Split out as a pure function because the honest message depends on THREE states that
    are easy to conflate — and a log line that misreports the book's state is the exact
    failure that hid the 2026-08-08 incident for a day.
    """
    n = fields.get("n_unadopted") or 0
    if not n:
        return None
    slots = fields["max_slots"]
    if fields.get("phantoms_ignored"):
        return (f"{n} desired position(s) have NO live 建玉 (phantoms), but their slots are "
                f"RELEASED by LIVE_IGNORE_PHANTOM_SLOTS — live exposure is still capped at "
                f"{slots} slot(s). Unset the flag once this reaches 0.")
    blocked = " — so the book can open NOTHING" if n >= slots else ""
    return (f"{n} of {slots} slot(s) held by phantoms (desired positions with NO live "
            f"建玉){blocked}. They free as they exit the replay, or set "
            f"LIVE_IGNORE_PHANTOM_SLOTS=1 to release them now.")


def _heartbeat_fields(strategy_name: str, symbol: str, slots: int | None,
                      state: LiveBookState, entries_allowed: bool) -> dict[str, Any]:
    """The DESIRED-book half of one heartbeat row.

    The live-side counts are filled in separately by :func:`live_executor.reconcile`
    (see :func:`main`) and default to ``None`` = "the exchange was never read this
    run", which is deliberately distinct from ``0`` = "read it, found nothing".
    Reading a bare ``n_open`` as the live position count is what hid the 2026-08-08
    mis-pairing for a day: it is the strategy's *intent*, and can include positions
    this account never opened.
    """
    price = state.last_price or 0.0
    return {
        "strategy": strategy_name,
        "symbol": symbol,
        "slots": slots,
        "max_slots": state.max_slots,
        "peak_notional": round(peak_exposure_jpy(symbol, state.max_slots, price)),
        "bar_time": str(state.last_bar_time),
        "close": state.last_price,
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
        # --- live side (None until the exchange is actually read) ---
        "n_live_open": None,   # 建玉 the account really holds
        "n_live_orders": None,
        "n_matched": None,     # desired positions paired to a real 建玉
        "n_unadopted": None,   # desired positions with NO 建玉 — phantoms; they hold a slot
        "n_live_only": None,   # 建玉 the strategy no longer wants — being closed
        "anomaly": None,
        "halted": False,
        "phantoms_ignored": False,  # LIVE_IGNORE_PHANTOM_SLOTS released a reserved slot
    }


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
    return state, entries_allowed


def _report(symbol: str, state: LiveBookState, *, live: bool,
            sync: dict[str, Any] | None = None) -> None:
    """Log the desired book, the live book, and the intended reconcile actions.

    Args:
        symbol: GMO leverage symbol.
        state: The strategy's desired book.
        live: Whether the exchange can be read at all.
        sync: Optional dict filled in place with the live-side counts, mirroring
            :func:`live_executor.reconcile` so a monitor-only book still gets a
            truthful heartbeat. No pairing runs here, so only the raw counts appear.
    """
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
    if sync is not None:
        sync.update(n_live_open=len(live_positions), n_live_orders=len(live_orders))
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
        # The heartbeat is written in `finally` so a book that throws mid-reconcile still
        # leaves a row carrying whatever the exchange read managed to learn. A silent gap
        # in heartbeat.jsonl is indistinguishable from "the timer never fired".
        state: LiveBookState | None = None
        entries_allowed = True
        sync: dict[str, Any] = {}
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
                          allow_entries=entries_allowed, sync=sync)
            else:
                if want_exec:
                    logger.warning("{} [{}]: {}-slot book > EXEC_MAX_SLOTS={} — MONITOR-ONLY here",
                                   name, symbol, book_slots, exec_max_slots())
                _report(symbol, state, live=True, sync=sync)
        except Exception as e:  # noqa: BLE001 — one book failing must not kill the rest
            logger.error("{} [{}] failed: {}", name, symbol, e)
        finally:
            if state is not None:
                fields = _heartbeat_fields(name, symbol, slots, state, entries_allowed)
                fields.update(sync)
                snapshot(fields)
                warning = _phantom_warning(fields)
                if warning:
                    logger.warning("{} [{}]: {}", name, symbol, warning)


if __name__ == "__main__":
    main()
