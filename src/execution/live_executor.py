"""One-slot live executor — reconcile the desired book to the GMO exchange.

Stateless: each run derives everything from (a) the strategy's desired book
(:meth:`MultiSimulator.live_state`) and (b) the live GMO positions/orders. With
**one slot** the live state is 0-or-1 position, so reconciliation is simple and
robust to missed cycles. It computes a list of actions and **only performs them
when ``execute=True``** — otherwise it just logs intended actions, so the same code
is the dry-run.

Safety:
- Hard min-lot size cap lives in the client (:meth:`GmoClient.send_order`).
- **Anomaly halt**: if the exchange shows >1 position or an oversized position
  (something this bot would never create), it logs CRITICAL and takes NO actions.
- **Kill switch**: a ``KILL`` file in the repo root (or ``KILL_SWITCH=1``) →
  cancel everything and flatten, then stop.
- Resting **exit orders** make price-based fills exchange-handled INTRABAR at the
  exact strategy levels (OCO-style): a STOP close-order at the ratchet stop and a
  LIMIT close-order at the take-profit target. The hourly reconcile maintains them
  (surgical stop update keeps the TP), cancels the leftover after one fills, and
  handles the non-price exits (time-stop / strategy-flat) by market close.

The order-request shapes are GMO-spec + mocked-tested; the FIRST live ``execute``
run confirms them (same as the manual round-trip).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger

from src.core.types import Side
from src.execution.gmo_client import LEVERAGE_MIN_SIZE, GmoClient
from src.simulator.multi_simulator import LiveBookState

_STOP_MOVE_FRAC = 0.001  # re-place the protective stop only if it moved > 0.1%


def kill_switch_active(repo_root: Path | None = None) -> bool:
    """True if ``KILL_SWITCH=1`` or a ``KILL`` file exists in the repo root."""
    if os.environ.get("KILL_SWITCH", "").strip() in {"1", "true", "yes", "on"}:
        return True
    root = repo_root or Path(__file__).resolve().parents[2]
    return (root / "KILL").exists()


def _close_side(position_side: str) -> str:
    """Side of the order that CLOSES a position (opposite of its side)."""
    return "SELL" if position_side.upper() == "BUY" else "BUY"


def reconcile(symbol: str, state: LiveBookState, client: GmoClient, *, execute: bool) -> list[str]:
    """Compute (and, if ``execute``, perform) the actions to match desired -> live.

    Args:
        symbol: GMO leverage symbol (e.g. ``XRP_JPY``).
        state: The strategy's desired book (1-slot).
        client: A GMO client — read for the live state; order-capable iff ``execute``.
        execute: When ``True`` actually send orders; else log intended actions only.

    Returns:
        Human-readable action descriptions (what was done / would be done).
    """
    min_lot = LEVERAGE_MIN_SIZE.get(symbol, 0.0)
    actions: list[str] = []

    def do(desc: str, fn: Callable[..., Any]) -> None:
        tag = "EXEC" if execute else "DRY-RUN"
        logger.info("  [{}] {}", tag, desc)
        actions.append(desc)
        if execute:
            fn()

    positions = client.get_open_positions(symbol)
    orders = client.get_active_orders(symbol)

    # --- kill switch: flatten everything, then stop ---
    if kill_switch_active():
        logger.warning("KILL SWITCH ACTIVE — cancelling orders and flattening {}", symbol)
        if orders:
            do(f"cancel ALL orders {symbol}", lambda: client.cancel_bulk(symbol))
        for p in positions:
            pid, sz, side = int(p["positionId"]), float(p["size"]), str(p["side"])
            do(f"KILL close pos {pid} {side} {sz}",
               lambda pid=pid, sz=sz, side=side: client.close_position(
                   symbol, pid, _close_side(side), sz, execution_type="MARKET"))
        return actions

    # --- anomaly halt: a state this bot can't have created ---
    if len(positions) > 1 or any(float(p.get("size", 0)) > min_lot * 1.5 for p in positions):
        logger.critical("ANOMALY {}: {} positions / oversized — HALTING, no actions taken",
                        symbol, len(positions))
        return ["HALT: anomalous live state"]

    desired = state.positions[0] if state.positions else None
    live = positions[0] if positions else None
    open_orders = [o for o in orders if str(o.get("settleType", "")).upper() == "OPEN"]
    close_orders = [o for o in orders if str(o.get("settleType", "")).upper() == "CLOSE"]

    if live is not None:
        live_side = Side.LONG if str(live["side"]).upper() == "BUY" else Side.SHORT
        pid, psize = int(live["positionId"]), float(live["size"])
        if desired is not None and desired.side == live_side:
            # Holding — maintain resting exits so price-based fills are exchange-handled
            # INTRABAR at the exact strategy levels (an OCO-style stop + TP pair).
            close_s = _close_side(live["side"])
            # 1. protective STOP at the ratchet stop (surgical update keeps the TP).
            want = desired.current_stop
            if want is not None:
                stop_o = next((o for o in close_orders if str(o.get("executionType")).upper() == "STOP"), None)
                if stop_o is None:
                    def _place_stop(want: float = want) -> None:
                        client.close_position(symbol, pid, close_s, psize, execution_type="STOP", price=want)

                    do(f"place protective STOP close {symbol} {close_s} @ {want:.6g}", _place_stop)
                elif abs(float(stop_o["price"]) - want) / want > _STOP_MOVE_FRAC:
                    sid = int(stop_o["orderId"])

                    def _replace_stop(want: float = want, sid: int = sid) -> None:
                        client.cancel_order(sid)  # surgical: leaves the TP in place
                        client.close_position(symbol, pid, close_s, psize, execution_type="STOP", price=want)

                    do(f"ratchet STOP -> {want:.6g} (cancel {sid} + replace)", _replace_stop)
            # 2. take-profit LIMIT at the target (fixed at entry — place once, no update).
            if desired.target is not None:
                tp = desired.target
                tp_o = next((o for o in close_orders if str(o.get("executionType")).upper() == "LIMIT"), None)
                if tp_o is None:
                    def _place_tp(tp: float = tp) -> None:
                        client.close_position(symbol, pid, close_s, psize, execution_type="LIMIT", price=tp)

                    do(f"place TP LIMIT close {symbol} {close_s} @ {tp:.6g}", _place_tp)
            if want is None and desired.target is None:
                logger.info("  HOLD {} {} pos {} — no stop/TP from strategy", symbol, live_side.name, pid)
        else:
            # Strategy has exited (or flipped) — cancel orders + market-close.
            if orders:
                do(f"cancel orders {symbol} (exiting)", lambda: client.cancel_bulk(symbol))
            do(f"CLOSE pos {pid} {live_side.name} (strategy exit)",
               lambda: client.close_position(symbol, pid, _close_side(live["side"]), psize, execution_type="MARKET"))
    else:
        # Flat. First clean up any leftover CLOSE order — after a resting stop or TP
        # filled intrabar (position gone), its OCO partner is left dangling.
        if close_orders:
            do(f"cancel leftover close order(s) {symbol} (position already closed)",
               lambda: client.cancel_bulk(symbol))
        # Then place the desired entry if any, else clean up stray entry orders.
        entry: tuple[Side, str, float | None] | None = None
        if state.working_orders:
            sig, price, _ = state.working_orders[0]
            entry = (sig.side, "LIMIT", price)
        elif state.pending_entries:
            entry = (state.pending_entries[0].side, "MARKET", None)
        if entry is not None:
            side, etype, eprice = entry
            gmo_side = "BUY" if side == Side.LONG else "SELL"
            if not any(str(o.get("side")).upper() == gmo_side for o in open_orders):
                pr = f" @ {eprice:.6g}" if eprice is not None else ""
                do(f"place {etype} entry {symbol} {gmo_side}{pr}",
                   lambda: client.send_order(symbol, gmo_side, execution_type=etype, price=eprice))
            for o in open_orders:  # cancel an entry on the wrong side
                if str(o.get("side")).upper() != gmo_side:
                    do(f"cancel stale entry {o.get('orderId')}", lambda: client.cancel_bulk(symbol))
                    break
        elif open_orders:
            do(f"cancel stale entry order(s) {symbol} (no signal)", lambda: client.cancel_bulk(symbol))

    if not actions:
        logger.info("  {} in sync (desired == live)", symbol)
    return actions
