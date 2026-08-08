"""Multi-slot live executor — reconcile the desired book to the GMO exchange.

Stateless: each run derives everything from (a) the strategy's desired book
(:meth:`MultiSimulator.live_state`) and (b) the live GMO positions/orders. Nothing is
persisted between runs, so a missed cycle, a restart or a manual intervention costs
nothing — the next cycle recomputes the whole picture from the exchange. It computes a
list of actions and **only performs them when ``execute=True``**; otherwise it just logs
intended actions, so the same code is the dry-run.

Holding up to N positions changes three things versus the original 1-slot executor:

1. **Identity.** Desired positions carry no exchange ``positionId``, so they are paired
   with live 建玉 by sorting both sides on keys that never change for a position's life
   (desired ``(entry_time, entry_price)`` vs live ``(timestamp, price)``) and zipping.
   Recomputed from scratch every cycle — see :func:`_match_positions`.
2. **Cancels must be surgical.** A symbol-wide :meth:`GmoClient.cancel_bulk` would strip
   every other slot's protective stop, so it is reachable **only** under the kill switch;
   everything else cancels explicit order ids.
3. **Entries and holdings coexist.** Entry placement is no longer confined to a flat
   book, and the free-slot arithmetic now counts resting entry orders as exposure.

Safety:
- Hard min-lot size cap lives in the client (:meth:`GmoClient.send_order`).
- **Anomaly halt**: a live state this bot could not have created (more positions than
  slots, an oversized or stub-sized position, an unknown symbol) logs CRITICAL and takes
  NO actions. ``LIVE_DRAIN_OK=1`` downgrades the over-slots case to drain mode so
  shrinking a book winds it down instead of freezing it.
- **Kill switch**: a ``KILL`` file in the repo root (or ``KILL_SWITCH=1``) → cancel
  everything and flatten, then stop.
- **Every action failure is recorded.** ``do()`` never lets an order rejection vanish:
  the failure is logged (CRITICAL for protective actions) and written to the order log.
- **One resting exit per position** — GMO reserves the whole 建玉 on the first settle
  order (confirmed live 2026-08-06: the second returned ``ERR-200``), so the backtest's
  OCO stop+target pair is not available here. The protective STOP takes the slot and
  fills INTRABAR at the exact ratchet level; the take-profit is realised at the hourly
  reconcile instead (the sim drops the position on the bar its target is touched, and
  the next reconcile market-closes it), as are the non-price exits (time-stop /
  strategy-flat). The take-profit is therefore 1h-granular, not intrabar.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from src.core.types import Side
from src.execution.gmo_client import LEVERAGE_MIN_SIZE, GmoClient
from src.execution.order_log import record
from src.execution.risk import entry_budget
from src.simulator.multi_simulator import DesiredPosition, LiveBookState

_STOP_MOVE_FRAC = 0.001  # re-place the protective stop only if it moved > 0.1%
_ENTRY_MOVE_FRAC = 0.001  # treat a resting entry as "still the desired one" within 0.1%
_HARD_SLOT_CEILING = 8  # config can never authorise more live slots than this


def kill_switch_active(repo_root: Path | None = None) -> bool:
    """True if ``KILL_SWITCH=1`` or a ``KILL`` file exists in the repo root."""
    if os.environ.get("KILL_SWITCH", "").strip() in {"1", "true", "yes", "on"}:
        return True
    root = repo_root or Path(__file__).resolve().parents[2]
    return (root / "KILL").exists()


def _close_side(position_side: str) -> str:
    """Side of the order that CLOSES a position (opposite of its side)."""
    return "SELL" if position_side.upper() == "BUY" else "BUY"


def _drain_ok() -> bool:
    """True if ``LIVE_DRAIN_OK=1`` — downgrade the over-slots halt to drain mode."""
    return os.environ.get("LIVE_DRAIN_OK", "").strip() in {"1", "true", "yes", "on"}


def effective_slots(state: LiveBookState) -> int:
    """The slot count this executor will act on.

    ``state.max_slots`` comes from the strategy class (``density_pullback`` = 12) unless
    ``AUTO_BOOKS`` overrides it, so it is a *configuration* value, not an authorisation.
    Clamp it so a mis-typed book can never authorise an unbounded live book.
    """
    return max(1, min(state.max_slots, _HARD_SLOT_CEILING))


def _reserved(p: dict[str, Any]) -> float:
    """Position quantity already committed to resting settle orders (GMO ``orderdSize``)."""
    try:
        return float(p.get("orderdSize", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _anomaly_reason(
    symbol: str, positions: list[dict[str, Any]], slots: int, min_lot: float
) -> tuple[str | None, bool]:
    """Detect a live state this bot cannot have created.

    Args:
        symbol: GMO leverage symbol.
        positions: Live open positions.
        slots: The book's effective concurrency cap.
        min_lot: The symbol's minimum lot.

    Returns:
        ``(reason, drainable)`` — ``reason`` None when the state is sane. ``drainable``
        marks the one case that a deliberate book *shrink* produces, which
        ``LIVE_DRAIN_OK=1`` may downgrade to wind-down instead of a freeze.
    """
    if min_lot <= 0:
        return f"{symbol} is not in the permitted leverage set (no min lot)", False
    sizes = []
    for p in positions:
        # A row we cannot address or classify is the most dangerous kind: it is real
        # exposure that _match_positions would drop on the floor (it buckets by
        # BUY/SELL), leaving it neither maintained nor closed. Refuse to proceed.
        if _position_id(p) is None:
            return f"{symbol}: position row without a usable positionId ({p!r})", False
        if str(p.get("side", "")).upper() not in {"BUY", "SELL"}:
            return (f"{symbol}: position {_position_id(p)} has unrecognised side "
                    f"{p.get('side')!r}"), False
        try:
            sizes.append(float(p.get("size", 0.0)))
        except (TypeError, ValueError):
            return f"{symbol}: unparseable position size {p.get('size')!r}", False
    if any(s > min_lot * 1.5 for s in sizes):
        return f"{symbol}: oversized position (> {min_lot * 1.5:g})", False
    if any(s < min_lot * 0.9 for s in sizes):
        # A partial fill or a manual part-close leaves a stub below the minimum
        # tradeable unit — it cannot be closed cleanly, so stop and let a human look.
        return f"{symbol}: undersized position stub (< {min_lot * 0.9:g})", False
    if sum(sizes) > slots * min_lot * 1.5:
        return f"{symbol}: aggregate size {sum(sizes):g} over the {slots}-slot budget", False
    if len(positions) > slots:
        return f"{symbol}: {len(positions)} positions > {slots} slot(s)", True
    return None, False


@dataclass(slots=True)
class Pairing:
    """Desired book matched against the live book, per side."""

    matched: list[tuple[DesiredPosition, dict[str, Any]]] = field(default_factory=list)
    live_only: list[dict[str, Any]] = field(default_factory=list)  # strategy exited → close
    desired_only: list[DesiredPosition] = field(default_factory=list)  # out of sync → slot taken


def _live_sort_key(p: dict[str, Any]) -> tuple[str, float]:
    """Immutable ordering key for a live position: (open timestamp, entry price)."""
    try:
        price = float(p.get("price", 0.0) or 0.0)
    except (TypeError, ValueError):
        price = 0.0
    return str(p.get("timestamp", "") or ""), price


def _match_positions(
    desired: list[DesiredPosition], live: list[dict[str, Any]]
) -> Pairing:
    """Pair desired against live positions, per side, by sort-and-zip.

    Both keys — desired ``(entry_time, entry_price)`` and live ``(timestamp, price)`` —
    are fixed for a position's whole life, so every cycle reproduces the same pairing
    without any stored state. A persisted slot→positionId map would be authoritative
    only while correct and would go wrong exactly at restarts and manual interventions.

    The failure mode is bounded: if two same-side positions are swapped, each gets the
    other's stop/target. Both levels still rest, so aggregate risk is unchanged — and
    the sim makes same-bar same-side positions genuinely interchangeable anyway
    (``random_hedge._stop`` is keyed ``(entry_idx, side)``, so they share a stop).

    Args:
        desired: The strategy's desired positions.
        live: Live GMO open positions.

    Returns:
        A :class:`Pairing`.
    """
    out = Pairing()
    for side, gmo_side in ((Side.LONG, "BUY"), (Side.SHORT, "SELL")):
        d = sorted((p for p in desired if p.side is side),
                   key=lambda p: (p.entry_time, p.entry_price))
        lv = sorted((p for p in live if str(p.get("side", "")).upper() == gmo_side),
                    key=_live_sort_key)
        for dp, lp in zip(d, lv):
            out.matched.append((dp, lp))
        out.desired_only.extend(d[len(lv):])
        out.live_only.extend(lv[len(d):])
    return out


def _assign_close_orders(
    matched: list[tuple[DesiredPosition, dict[str, Any]]],
    live_only: list[dict[str, Any]],
    close_orders: list[dict[str, Any]],
) -> tuple[dict[int, dict[str, dict[str, Any]]], list[dict[str, Any]]]:
    """Attribute each resting CLOSE order to the position it protects.

    GMO's activeOrders response does not name the settle target, so attribution is by
    **exit slot**: each paired position offers at most one ``STOP`` slot and one
    ``LIMIT`` slot, on the side that would close it. An order claims a free slot of its
    own ``(close side, executionType)``; price only *disambiguates* when several
    same-side positions compete for it.

    Price is deliberately not a hard gate. The ratchet recomputes only every
    ``recalc_bars``, so a resting stop is routinely far from the newly desired level —
    that drift is exactly what this executor exists to correct, not evidence the order
    belongs to someone else. Positions being closed (``live_only``) offer wildcard slots
    so their resting exits are attributed too, and can therefore be cancelled *before*
    the market close rather than left to fire mid-flight. An orphan is an order with
    **no slot to claim**: its position is gone (the OCO partner of an exit that filled
    intrabar), or the strategy no longer wants an exit of that type.

    Assignment is best-first over all candidate (order, slot) pairs by *relative* price
    distance, not order-by-order. Greedy-in-price-order mis-assigns whenever a stale stop
    happens to sit nearer another slot's level than its own.

    Args:
        matched: Desired/live pairs from :func:`_match_positions`.
        live_only: Live positions with no desired counterpart (about to be closed).
        close_orders: Live orders with ``settleType == "CLOSE"``.

    Returns:
        ``({positionId: {"STOP": order, "LIMIT": order}}, orphan_orders)``.
    """
    # Exit slots: (positionId, type, expected close side, desired level or None=wildcard).
    slots: list[tuple[int, str, str, float | None]] = []
    for dp, lp in matched:
        try:
            pid = int(lp["positionId"])
        except (KeyError, TypeError, ValueError):
            continue
        cs = _close_side(str(lp.get("side", "")))
        if dp.current_stop is not None:
            slots.append((pid, "STOP", cs, dp.current_stop))
        if dp.target is not None:
            slots.append((pid, "LIMIT", cs, dp.target))
    for lp in live_only:
        try:
            pid = int(lp["positionId"])
        except (KeyError, TypeError, ValueError):
            continue
        cs = _close_side(str(lp.get("side", "")))
        slots.append((pid, "STOP", cs, None))
        slots.append((pid, "LIMIT", cs, None))

    # Candidate edges, cheapest first. inf = a wildcard (or unusable level): still a valid
    # home for the order, but only after every priced match has been made.
    edges: list[tuple[float, int, int]] = []
    for oi, o in enumerate(close_orders):
        etype = str(o.get("executionType", "")).upper()
        oside = str(o.get("side", "")).upper()
        px = _order_price(o)
        for si, (_pid, t, cs, level) in enumerate(slots):
            if t != etype or (oside and cs and oside != cs):
                continue
            dist = abs(px - level) / level if level is not None and level > 0 else float("inf")
            edges.append((dist, oi, si))
    edges.sort()

    assigned: dict[int, dict[str, dict[str, Any]]] = {}
    used_orders: set[int] = set()
    used_slots: set[int] = set()
    for _dist, oi, si in edges:
        if oi in used_orders or si in used_slots:
            continue
        used_orders.add(oi)
        used_slots.add(si)
        pid, etype, _cs, _level = slots[si]
        assigned.setdefault(pid, {})[etype] = close_orders[oi]
    orphans = [o for i, o in enumerate(close_orders) if i not in used_orders]
    return assigned, orphans


def _order_price(o: dict[str, Any]) -> float:
    """Parse an order's price, or 0.0 when absent/unparseable."""
    try:
        return float(o.get("price", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _order_id(o: dict[str, Any]) -> int | None:
    """Parse an order id, or None when absent/unparseable."""
    try:
        return int(o["orderId"])
    except (KeyError, TypeError, ValueError):
        return None


def _position_id(p: dict[str, Any]) -> int | None:
    """Parse a position id, or None when absent/unparseable."""
    try:
        return int(p["positionId"])
    except (KeyError, TypeError, ValueError):
        return None


def _maintain_exits(
    symbol: str,
    dp: DesiredPosition,
    lp: dict[str, Any],
    exits: dict[str, dict[str, Any]],
    last_price: float | None,
    client: GmoClient,
    do: Callable[..., bool],
) -> None:
    """Keep ONE live position's protective STOP (ratcheted) and TP in sync with ``dp``.

    Args:
        symbol: GMO leverage symbol.
        dp: The desired position paired to ``lp``.
        lp: The live GMO position.
        exits: This position's attributed CLOSE orders, keyed ``"STOP"`` / ``"LIMIT"``.
        last_price: Last closed-bar close — the market reference for the clamp.
        client: GMO client.
        do: The action runner from :func:`reconcile`.
    """
    pid, psize = int(lp["positionId"]), float(lp["size"])
    live_side = Side.LONG if str(lp["side"]).upper() == "BUY" else Side.SHORT
    close_s = _close_side(str(lp["side"]))
    want = dp.current_stop
    stop_o, tp_o = exits.get("STOP"), exits.get("LIMIT")

    # Realisable-fill clamp (mirrors the sim's min/max(stop, bar.open)): the ratchet stop
    # is recomputed only every ``recalc_bars``, so on a recalc it can land on the WRONG
    # side of the market — above market for a long's protective sell-stop, below for a
    # short. A resting STOP there is impossible / triggers instantly, and the strategy's
    # intent is to EXIT NOW. Translate to a market close rather than send a phantom STOP.
    # ``want > 0`` guards the clamp against nonsensical stop data: a 0/negative stop on a
    # SHORT is trivially "below market" and would market-close a healthy position.
    breached = want is not None and want > 0 and last_price is not None and (
        (live_side is Side.LONG and want >= last_price)
        or (live_side is Side.SHORT and want <= last_price)
    )
    if breached:
        assert want is not None and last_price is not None  # narrowed by `breached`
        ids = [i for i in (_order_id(o) for o in exits.values()) if i is not None]
        if ids:
            do(f"cancel exits {ids} for pos {pid} (trail through market)",
               lambda ids=ids: client.cancel_orders(ids))
        do(f"CLOSE pos {pid} {live_side.name} (trail stop {want:.6g} through market "
           f"{last_price:.6g})",
           lambda pid=pid, close_s=close_s, psize=psize: client.close_position(
               symbol, pid, close_s, psize, execution_type="MARKET"), critical=True)
        return

    # GMO reserves position quantity per settle order (``orderdSize``). If quantity is
    # committed but no resting order could be attributed to this position, another send
    # would either be rejected or double up — do nothing this cycle and let orphan
    # cleanup converge it.
    reserved = _reserved(lp)
    if reserved > 0 and not exits:
        logger.warning(
            "{} pos {}: {:g} of {:g} reserved by an unattributable settle order — "
            "placing nothing this cycle", symbol, pid, reserved, psize)
        return

    # 1. Protective STOP at the ratchet stop (surgical update keeps the TP).
    if want is not None and want <= 0:
        logger.warning("{} pos {}: nonsensical stop {:g} from the strategy — not placing "
                       "a protective STOP this cycle", symbol, pid, want)
    elif want is not None:
        if stop_o is None:
            do(f"place protective STOP close {symbol} {close_s} @ {want:.6g} (pos {pid})",
               lambda want=want, pid=pid, close_s=close_s, psize=psize: client.close_position(
                   symbol, pid, close_s, psize, execution_type="STOP", price=want),
               critical=True)
        else:
            try:
                cur = float(stop_o["price"])
            except (KeyError, TypeError, ValueError):
                cur = float("nan")  # unreadable price -> cannot trust it, replace it
            moved = cur != cur or abs(cur - want) / want > _STOP_MOVE_FRAC
            sid = _order_id(stop_o)
            if moved and sid is None:
                # Without an id we cannot cancel it, so the ratchet cannot happen and the
                # position silently wears a stale stop. That must never pass quietly.
                logger.warning("{} pos {}: resting STOP has no usable orderId — cannot "
                               "ratchet {:g} -> {:.6g}; CHECK THE EXCHANGE",
                               symbol, pid, cur, want)
            elif moved and sid is not None:
                def _replace(want: float = want, sid: int = sid, pid: int = pid,
                             close_s: str = close_s, psize: float = psize) -> None:
                    client.cancel_order(sid)  # cancel FIRST — never leave two stops resting
                    client.close_position(symbol, pid, close_s, psize,
                                          execution_type="STOP", price=want)

                do(f"ratchet STOP -> {want:.6g} (pos {pid}: cancel {sid} + replace)",
                   _replace, critical=True)

    # 2. Take-profit LIMIT at the target — but only if the STOP has not claimed the slot.
    #
    #    GMO permits exactly ONE resting settle order per 建玉. Confirmed live on
    #    2026-08-06 07:05 (BTC pos 289850034): the STOP was accepted, and the TP that
    #    followed came back `ERR-200 "There are open positions that the settlement
    #    quantity exceeds the settable quantity"` — the first settle order reserves the
    #    whole position (``orderdSize``). So the OCO pair the backtest assumes is not
    #    available on this venue.
    #
    #    Protection wins the slot: a take-profit rests only when the strategy wants no
    #    stop at all. Otherwise the target is realised at the hourly reconcile — the sim
    #    drops the position on the bar its target is touched, and the next reconcile
    #    market-closes it. That makes the take-profit **1h-granular instead of intrabar**,
    #    a real backtest-vs-live deviation recorded in docs/deploy.md. Never invert this
    #    priority: resting the TP would leave the position unprotected between bars.
    if dp.target is not None and tp_o is None:
        if want is not None:
            logger.info("  {} pos {}: TP {:.6g} not rested — the STOP holds the venue's "
                        "single settle slot; target realised at the hourly reconcile",
                        symbol, pid, dp.target)
        elif reserved >= psize:
            logger.info("  {} pos {}: TP {:.6g} not rested — quantity already reserved",
                        symbol, pid, dp.target)
        else:
            tp = dp.target
            do(f"place TP LIMIT close {symbol} {close_s} @ {tp:.6g} (pos {pid})",
               lambda tp=tp, pid=pid, close_s=close_s, psize=psize: client.close_position(
                   symbol, pid, close_s, psize, execution_type="LIMIT", price=tp))

    if want is None and dp.target is None:
        logger.info("  HOLD {} {} pos {} — no stop/TP from strategy", symbol,
                    live_side.name, pid)


def _entry_plan(
    state: LiveBookState, open_orders: list[dict[str, Any]]
) -> tuple[list[tuple[Side, str, float | None]], list[dict[str, Any]], int]:
    """Split desired entries into (to place, stale live orders to cancel, already resting).

    Desired order mirrors the simulator so the live book fills the trades the backtest
    measured: ``pending_entries`` (market, filled at step 2 of ``_simulate``) first, then
    ``working_orders`` (resting limits, step 3).

    Args:
        state: The desired book.
        open_orders: Live orders with ``settleType == "OPEN"``.

    Returns:
        ``(to_place, stale_orders, n_kept)`` — ``to_place`` is NOT yet truncated to the
        slot/margin budget; ``stale_orders`` always is cancelled (cleanup is never
        rationed).
    """
    desired: list[tuple[Side, str, float | None]] = [
        (s.side, "MARKET", None) for s in state.pending_entries
    ] + [(sig.side, "LIMIT", price) for sig, price, _expiry in state.working_orders]

    unused = list(open_orders)
    to_place: list[tuple[Side, str, float | None]] = []
    n_kept = 0
    for side, etype, price in desired:
        gmo_side = "BUY" if side is Side.LONG else "SELL"
        hit = None
        if etype == "LIMIT" and price is not None and price > 0:
            for o in unused:
                if str(o.get("side", "")).upper() != gmo_side:
                    continue
                try:
                    opx = float(o.get("price", "nan"))
                except (TypeError, ValueError):
                    continue
                if opx == opx and abs(opx - price) / price <= _ENTRY_MOVE_FRAC:
                    hit = o
                    break
        if hit is not None:
            unused.remove(hit)  # already resting at the right level — leave it alone
            n_kept += 1
        else:
            to_place.append((side, etype, price))
    return to_place, unused, n_kept


def reconcile(symbol: str, state: LiveBookState, client: GmoClient, *, execute: bool) -> list[str]:
    """Compute (and, if ``execute``, perform) the actions to match desired -> live.

    Args:
        symbol: GMO leverage symbol (e.g. ``XRP_JPY``).
        state: The strategy's desired book (up to ``state.max_slots`` positions).
        client: A GMO client — read for the live state; order-capable iff ``execute``.
        execute: When ``True`` actually send orders; else log intended actions only.

    Returns:
        Human-readable action descriptions (what was done / would be done). A failed
        action is included as ``"FAILED: <desc> (<error>)"``.
    """
    min_lot = LEVERAGE_MIN_SIZE.get(symbol, 0.0)
    slots = effective_slots(state)
    actions: list[str] = []

    def do(desc: str, fn: Callable[..., Any], *, critical: bool = False) -> bool:
        """Run one action, recording it whether it succeeds or fails.

        ``record()`` used to run only after ``fn()`` returned, and ``auto_trader``
        swallows per-book exceptions — so a rejected order left no trace anywhere. With N
        positions a silent failure would also abort every remaining position's
        maintenance, so failures are contained here and reported instead.
        """
        tag = "EXEC" if execute else "DRY-RUN"
        logger.info("  [{}] {}", tag, desc)
        if not execute:
            actions.append(desc)
            record(symbol, desc, execute=False, result=None)
            return True
        try:
            result = fn()
        except Exception as e:  # noqa: BLE001 - an order failure must never be silent
            log = logger.critical if critical else logger.warning
            log("ACTION FAILED {}: {} -> {}", symbol, desc, e)
            actions.append(f"FAILED: {desc} ({e})")
            record(symbol, f"FAILED: {desc}", execute=True, result=f"ERROR: {e}")
            return False
        actions.append(desc)
        record(symbol, desc, execute=True, result=result)
        return True

    positions = client.get_open_positions(symbol)
    orders = client.get_active_orders(symbol)

    # --- kill switch: flatten everything, then stop ---
    if kill_switch_active():
        logger.warning("KILL SWITCH ACTIVE — cancelling orders and flattening {}", symbol)
        if orders:
            do(f"cancel ALL orders {symbol}", lambda: client.cancel_bulk(symbol))
        for p in positions:
            # Deliberately defensive: the kill switch runs BEFORE the anomaly check, so
            # it is the one path that must cope with rows the check would have rejected.
            # One unaddressable row must never stop the others from being flattened.
            pid = _position_id(p)
            side = str(p.get("side", "")).upper()
            try:
                sz = float(p.get("size", 0.0))
            except (TypeError, ValueError):
                sz = 0.0
            if pid is None or side not in {"BUY", "SELL"} or sz <= 0:
                logger.critical("KILL {}: cannot close unaddressable position row {!r} — "
                                "CLOSE IT BY HAND", symbol, p)
                actions.append(f"KILL: unaddressable position {p!r} — close by hand")
                record(symbol, f"KILL: unaddressable position {p!r}", execute=execute)
                continue
            do(f"KILL close pos {pid} {side} {sz}",
               lambda pid=pid, sz=sz, side=side: client.close_position(
                   symbol, pid, _close_side(side), sz, execution_type="MARKET"), critical=True)
        return actions

    # --- anomaly halt: a state this bot can't have created ---
    reason, drainable = _anomaly_reason(symbol, positions, slots, min_lot)
    draining = False
    if reason is not None:
        if drainable and _drain_ok():
            logger.warning("DRAINING {}: {} — LIVE_DRAIN_OK set: maintaining exits and "
                           "closing unmatched, no new entries", symbol, reason)
            draining = True
        else:
            logger.critical("ANOMALY {}: {} — HALTING, no actions taken", symbol, reason)
            return [f"HALT: {reason}"]

    pairing = _match_positions(state.positions, positions)
    close_orders = [o for o in orders if str(o.get("settleType", "")).upper() == "CLOSE"]
    open_orders = [o for o in orders if str(o.get("settleType", "")).upper() == "OPEN"]
    # Anything that is neither falls through both buckets: never cancelled, never counted
    # against a slot — a resting order the bot has forgotten about that can still FILL.
    # Deliberately NOT auto-cancelled: an unclassifiable order may be a human's, and
    # cancelling on a misunderstanding could remove someone's protection. Say it loudly.
    unknown = [o for o in orders
               if str(o.get("settleType", "")).upper() not in {"OPEN", "CLOSE"}]
    if unknown:
        logger.warning("{}: {} resting order(s) with an unrecognised settleType — NOT "
                       "managed by the bot, review by hand: {}",
                       symbol, len(unknown), [_order_id(o) for o in unknown])
    exits_by_pid, orphan_closes = _assign_close_orders(pairing.matched, pairing.live_only,
                                                       close_orders)

    # --- 1. maintain each held position's exits ---
    for dp, lp in pairing.matched:
        pid = int(lp["positionId"])
        _maintain_exits(symbol, dp, lp, exits_by_pid.get(pid, {}), state.last_price,
                        client, do)

    # --- 2. close positions the strategy has exited (or flipped out of) ---
    for lp in pairing.live_only:
        pid, psize = int(lp["positionId"]), float(lp["size"])
        live_side = Side.LONG if str(lp["side"]).upper() == "BUY" else Side.SHORT
        ids = [i for i in (_order_id(o) for o in exits_by_pid.get(pid, {}).values())
               if i is not None]
        if ids:
            do(f"cancel exits {ids} for pos {pid} (exiting)",
               lambda ids=ids: client.cancel_orders(ids))
        do(f"CLOSE pos {pid} {live_side.name} (strategy exit)",
           lambda pid=pid, lp=lp, psize=psize: client.close_position(
               symbol, pid, _close_side(str(lp["side"])), psize, execution_type="MARKET"),
           critical=True)

    # --- 3. orphaned CLOSE orders (the OCO partner of an exit that already filled) ---
    orphan_ids = [i for i in (_order_id(o) for o in orphan_closes) if i is not None]
    if orphan_ids:
        do(f"cancel orphan close order(s) {orphan_ids} {symbol}",
           lambda ids=orphan_ids: client.cancel_orders(ids))

    # --- 4. out-of-sync report ---
    # The strategy may hold positions this account never opened (it entered while we were
    # dry-run / the box was down / a cycle was missed). We do NOT adopt them mid-flight —
    # entering now at an arbitrary price is a different trade from the one the backtest
    # measured — but their slots count as TAKEN so we never fill a slot the strategy
    # itself declined (MultiSimulator only fills while ``len(book) < max_slots``).
    if pairing.desired_only:
        n = len(pairing.desired_only)
        msg = (f"OUT OF SYNC {symbol}: strategy holds {n} position(s) this account does "
               f"not (entered while dry-run/down) — NOT adopting mid-flight.")
        if n >= max(1, slots // 2):
            logger.warning(msg)
        else:
            logger.info("  " + msg)

    # --- 5. entries ---
    to_place, stale_open, n_kept = _entry_plan(state, open_orders)
    stale_ids = [i for i in (_order_id(o) for o in stale_open) if i is not None]
    if stale_ids:
        do(f"cancel stale entry order(s) {stale_ids} {symbol} (no signal / wrong level)",
           lambda ids=stale_ids: client.cancel_orders(ids))

    if draining:
        room = 0
        why = "draining"
    else:
        # Two independent bounds: the strategy's own book (a slot it declined must never
        # be filled live) and live exposure (positions + resting entries are both risk).
        room = max(0, min(slots - len(state.positions),
                          slots - (len(positions) + n_kept)))
        n_allowed, why = entry_budget(symbol, room, state.last_price, client)
        room = n_allowed
    if to_place and room < len(to_place):
        logger.info("  {} placing {} of {} desired entr(ies) — {}",
                    symbol, room, len(to_place), why)
    for side, etype, price in to_place[:room]:
        gmo_side = "BUY" if side is Side.LONG else "SELL"
        pr = f" @ {price:.6g}" if price is not None else ""
        do(f"place {etype} entry {symbol} {gmo_side}{pr}",
           lambda gmo_side=gmo_side, etype=etype, price=price: client.send_order(
               symbol, gmo_side, execution_type=etype, price=price))

    if not actions:
        if pairing.desired_only and not positions:
            logger.info("  {} no actions — out of sync (see warning above)", symbol)
        else:
            logger.info("  {} in sync (desired == live)", symbol)
    return actions
