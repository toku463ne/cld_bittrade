"""Tests for the multi-slot live executor (mocked client; no network)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from loguru import logger

from src.core.types import Side, Signal
from src.execution.live_executor import reconcile
from src.simulator.multi_simulator import DesiredPosition, LiveBookState

_T = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolate_order_log(tmp_path: Path, monkeypatch: Any) -> None:
    """Point the order log at a tmp file so tests don't touch the real logs/."""
    monkeypatch.setenv("ORDER_LOG", str(tmp_path / "orders.jsonl"))


class _FakeClient:
    """Records order calls; returns the configured positions/orders."""

    def __init__(self, positions: list[dict[str, Any]], orders: list[dict[str, Any]],
                 margin: dict[str, Any] | None = None) -> None:
        self._positions = positions
        self._orders = orders
        self._margin = margin
        self.calls: list[str] = []

    def get_open_positions(self, symbol: str) -> list[dict[str, Any]]:
        return self._positions

    def get_active_orders(self, symbol: str) -> list[dict[str, Any]]:
        return self._orders

    def send_order(self, symbol: str, side: str, **kw: Any) -> str:
        px = kw.get("price")
        tail = f" @ {px:g}" if isinstance(px, (int, float)) else ""
        self.calls.append(f"send_order {side} {kw.get('execution_type')}{tail}")
        return "OID"

    def close_position(self, symbol: str, pid: int, side: str, size: float, **kw: Any) -> str:
        px = kw.get("price")
        tail = f" @ {px:g}" if isinstance(px, (int, float)) else ""
        self.calls.append(f"close {pid} {side} {kw.get('execution_type')}{tail}")
        return "OID"

    def cancel_bulk(self, symbol: str) -> None:
        self.calls.append("cancel_bulk")

    def cancel_order(self, order_id: int) -> None:
        self.calls.append(f"cancel_order {order_id}")

    def cancel_orders(self, order_ids: list[int]) -> None:
        self.calls.append(f"cancel_orders {sorted(int(o) for o in order_ids)}")


class _MarginClient(_FakeClient):
    """A client that exposes get_margin — the entry budget only engages for these."""

    def get_margin(self) -> dict[str, Any]:
        if self._margin is None:
            raise RuntimeError("margin API down")
        return self._margin


def _state(positions: list[DesiredPosition], working: list[Any] = [], pending: list[Signal] = [],
           last_price: float | None = None, max_slots: int = 1) -> LiveBookState:
    return LiveBookState(positions=positions, pending_entries=pending, working_orders=working,
                         last_bar_time=_T, last_price=last_price, max_slots=max_slots)


def _pos(side: Side, stop: float | None = 170.0, *, entry: float = 180.0,
         hours: int = 0, target: float | None = None) -> DesiredPosition:
    return DesiredPosition(side=side, entry_time=_T + timedelta(hours=hours), entry_price=entry,
                           current_stop=stop, target=target, bars_held=3, time_stop_bars=120)


def _live(pid: int, side: str, *, size: str = "10", price: str = "180.0",
          hours: int = 0, reserved: str | None = None) -> dict[str, Any]:
    """A live GMO 建玉 row: positionId + the immutable (timestamp, price) sort key."""
    row: dict[str, Any] = {"positionId": pid, "side": side, "size": size, "price": price,
                           "timestamp": (_T + timedelta(hours=hours)).isoformat()}
    if reserved is not None:
        row["orderdSize"] = reserved
    return row


def _close_order(oid: int, etype: str, price: str, side: str) -> dict[str, Any]:
    return {"orderId": oid, "settleType": "CLOSE", "executionType": etype,
            "price": price, "side": side}


def _sig(side: Side) -> Signal:
    return Signal(side=side, timestamp=_T, price=179.0)


def test_flat_with_resting_limit_places_entry() -> None:
    state = _state([], working=[(_sig(Side.SHORT), 179.5, 999)])
    c = _FakeClient(positions=[], orders=[])
    reconcile("XRP_JPY", state, c, execute=True)
    assert c.calls == ["send_order SELL LIMIT @ 179.5"]


def test_dry_run_places_nothing() -> None:
    state = _state([], working=[(_sig(Side.SHORT), 179.5, 999)])
    c = _FakeClient(positions=[], orders=[])
    acts = reconcile("XRP_JPY", state, c, execute=False)
    assert c.calls == []  # nothing sent
    assert any("entry" in a for a in acts)  # but the intended action is reported


def test_holding_places_protective_stop() -> None:
    state = _state([_pos(Side.SHORT, stop=185.0)])
    live = [{"positionId": 7, "side": "SELL", "size": "10"}]
    c = _FakeClient(positions=live, orders=[])
    reconcile("XRP_JPY", state, c, execute=True)
    assert c.calls == ["close 7 BUY STOP @ 185"]  # SELL position -> BUY stop to close


def test_holding_with_current_stop_no_dup() -> None:
    state = _state([_pos(Side.SHORT, stop=185.0)])
    live = [{"positionId": 7, "side": "SELL", "size": "10"}]
    orders = [{"orderId": 1, "settleType": "CLOSE", "executionType": "STOP", "price": "185.0", "side": "BUY"}]
    c = _FakeClient(positions=live, orders=orders)
    reconcile("XRP_JPY", state, c, execute=True)
    assert c.calls == []  # stop already at the right level, no TP target


def test_stop_wins_the_venues_single_settle_slot_over_the_tp() -> None:
    # GMO reserves the whole 建玉 on the FIRST settle order, so the OCO pair the backtest
    # assumes is unavailable. Confirmed live 2026-08-06 07:05 (BTC pos 289850034): the
    # STOP was accepted, the TP that followed returned ERR-200 "settlement quantity
    # exceeds the settable quantity". Protection must win the slot — inverting this would
    # leave the position unprotected between bars.
    pos = DesiredPosition(side=Side.SHORT, entry_time=_T, entry_price=180.0,
                          current_stop=185.0, target=170.0, bars_held=3, time_stop_bars=120)
    live = [{"positionId": 7, "side": "SELL", "size": "10"}]
    c = _FakeClient(positions=live, orders=[])
    reconcile("XRP_JPY", _state([pos]), c, execute=True)
    assert c.calls == ["close 7 BUY STOP @ 185"]  # no TP attempt -> no guaranteed ERR-200


def test_ratchet_uses_surgical_cancel_keeps_tp() -> None:
    pos = DesiredPosition(side=Side.SHORT, entry_time=_T, entry_price=180.0,
                          current_stop=182.0, target=170.0, bars_held=9, time_stop_bars=120)
    live = [{"positionId": 7, "side": "SELL", "size": "10"}]
    orders = [
        {"orderId": 11, "settleType": "CLOSE", "executionType": "STOP", "price": "185.0", "side": "BUY"},
        {"orderId": 12, "settleType": "CLOSE", "executionType": "LIMIT", "price": "170.0", "side": "BUY"},
    ]
    c = _FakeClient(positions=live, orders=orders)
    reconcile("XRP_JPY", _state([pos]), c, execute=True)
    # stop moved 185 -> 182: surgical cancel of the stop only (not bulk), re-place; TP untouched
    assert c.calls == ["cancel_order 11", "close 7 BUY STOP @ 182"]


def test_flat_cancels_leftover_close_order() -> None:
    # position closed intrabar via a resting stop/TP; its OCO partner dangles -> cancel
    orders = [{"orderId": 9, "settleType": "CLOSE", "executionType": "LIMIT", "price": "170.0", "side": "BUY"}]
    c = _FakeClient(positions=[], orders=orders)
    reconcile("XRP_JPY", _state([]), c, execute=True)
    # surgical: only the orphan's id, never a symbol-wide bulk cancel
    assert c.calls == ["cancel_orders [9]"]


def test_long_stop_through_market_clamps_to_market_close() -> None:
    # Phantom-fill case from the live heartbeat: a long's ratchet sell-stop recalcs
    # ABOVE market (peak - tiny band). It's impossible to rest there -> market close.
    pos = DesiredPosition(side=Side.LONG, entry_time=_T, entry_price=10460115.0,
                          current_stop=10743479.0, target=None, bars_held=49, time_stop_bars=120)
    live = [{"positionId": 7, "side": "BUY", "size": "0.001"}]
    c = _FakeClient(positions=live, orders=[])
    reconcile("BTC_JPY", _state([pos], last_price=10526968.0), c, execute=True)
    assert c.calls == ["close 7 SELL MARKET"]  # NOT a phantom STOP above market


def test_long_stop_through_market_cancels_resting_orders_first() -> None:
    pos = DesiredPosition(side=Side.LONG, entry_time=_T, entry_price=10460115.0,
                          current_stop=10743479.0, target=None, bars_held=49, time_stop_bars=120)
    live = [{"positionId": 7, "side": "BUY", "size": "0.001"}]
    orders = [{"orderId": 11, "settleType": "CLOSE", "executionType": "STOP", "price": "10427841.0", "side": "SELL"}]
    c = _FakeClient(positions=live, orders=orders)
    reconcile("BTC_JPY", _state([pos], last_price=10526968.0), c, execute=True)
    assert c.calls == ["cancel_orders [11]", "close 7 SELL MARKET"]


def test_short_stop_through_market_clamps_to_market_close() -> None:
    # Mirror for a short: protective BUY-stop recalcs BELOW market -> exit now.
    pos = DesiredPosition(side=Side.SHORT, entry_time=_T, entry_price=180.0,
                          current_stop=175.0, target=None, bars_held=49, time_stop_bars=120)
    live = [{"positionId": 7, "side": "SELL", "size": "10"}]
    c = _FakeClient(positions=live, orders=[])
    reconcile("XRP_JPY", _state([pos], last_price=176.0), c, execute=True)
    assert c.calls == ["close 7 BUY MARKET"]


def test_normal_stop_below_market_still_places_stop() -> None:
    # Clamp must NOT fire for a healthy long stop below market.
    pos = DesiredPosition(side=Side.LONG, entry_time=_T, entry_price=180.0,
                          current_stop=170.0, target=None, bars_held=3, time_stop_bars=120)
    live = [{"positionId": 7, "side": "BUY", "size": "10"}]
    c = _FakeClient(positions=live, orders=[])
    reconcile("XRP_JPY", _state([pos], last_price=181.0), c, execute=True)
    assert c.calls == ["close 7 SELL STOP @ 170"]


def test_no_last_price_falls_back_to_stop_placement() -> None:
    # Without a market reference (last_price=None) keep prior behaviour: place the STOP.
    pos = DesiredPosition(side=Side.LONG, entry_time=_T, entry_price=180.0,
                          current_stop=185.0, target=None, bars_held=49, time_stop_bars=120)
    live = [{"positionId": 7, "side": "BUY", "size": "10"}]
    c = _FakeClient(positions=live, orders=[])
    reconcile("XRP_JPY", _state([pos], last_price=None), c, execute=True)
    assert c.calls == ["close 7 SELL STOP @ 185"]


def test_strategy_exit_closes_position() -> None:
    state = _state([])  # desired flat
    live = [{"positionId": 7, "side": "SELL", "size": "10"}]
    c = _FakeClient(positions=live, orders=[])
    reconcile("XRP_JPY", state, c, execute=True)
    assert c.calls == ["close 7 BUY MARKET"]


def test_anomaly_two_positions_halts() -> None:
    live = [{"positionId": 1, "side": "BUY", "size": "10"}, {"positionId": 2, "side": "SELL", "size": "10"}]
    c = _FakeClient(positions=live, orders=[])
    acts = reconcile("XRP_JPY", _state([]), c, execute=True)  # 1-slot book, 2 live
    assert c.calls == [] and len(acts) == 1 and acts[0].startswith("HALT:")


def test_kill_switch_flattens(monkeypatch: Any) -> None:
    monkeypatch.setenv("KILL_SWITCH", "1")
    live = [{"positionId": 9, "side": "BUY", "size": "10"}]
    c = _FakeClient(positions=live, orders=[{"orderId": 1, "settleType": "OPEN"}])
    reconcile("XRP_JPY", _state([_pos(Side.LONG)]), c, execute=True)
    assert "cancel_bulk" in c.calls and any("close 9 SELL MARKET" == x for x in c.calls)


# --- desired-holds / live-flat: the 2026-07-02 divergence (order 8663330572) ---------
#
# The strategy entered XRP LONG on the 07-01 16:00 bar while the box was still dry-run,
# so live never held it. On the next hourly cycle the desired book was {1 open position,
# 1 resting LIMIT} — but MultiSimulator can never fill that working order (its only slot
# is taken: it fills a working order only while ``len(book) < max_slots``). The executor,
# reading "live flat", sent it anyway. It escaped a phantom fill only because XRP rallied.


def test_slot_blocked_resting_order_is_not_sent_when_strategy_already_holds() -> None:
    # 1-slot book, strategy holds its one position, live flat -> the resting entry is for
    # a slot the strategy itself cannot fill. Send nothing.
    state = _state([_pos(Side.LONG)], working=[(_sig(Side.LONG), 171.996, 999)])
    c = _FakeClient(positions=[], orders=[])
    acts = reconcile("XRP_JPY", state, c, execute=True)
    assert c.calls == []
    assert not any("entry" in a for a in acts)


def test_slot_blocked_pending_market_entry_is_not_sent() -> None:
    state = _state([_pos(Side.SHORT)], pending=[_sig(Side.SHORT)])
    c = _FakeClient(positions=[], orders=[])
    reconcile("XRP_JPY", state, c, execute=True)
    assert c.calls == []


def test_slot_blocked_cancels_a_phantom_entry_order_already_resting() -> None:
    # A slot-blocked entry sent by an earlier (buggy) run must be cleaned up, not renewed.
    state = _state([_pos(Side.LONG)], working=[(_sig(Side.LONG), 171.996, 999)])
    c = _FakeClient(positions=[], orders=[{"orderId": 8663330572, "settleType": "OPEN", "side": "BUY"}])
    acts = reconcile("XRP_JPY", state, c, execute=True)
    assert c.calls == ["cancel_orders [8663330572]"]
    assert any("cancel stale entry" in a for a in acts)


def test_free_slot_still_places_entry_while_holding() -> None:
    # Multi-slot book with a spare slot: the entry is legitimate and must still be sent.
    state = _state([_pos(Side.LONG)], working=[(_sig(Side.LONG), 171.996, 999)], max_slots=2)
    c = _FakeClient(positions=[], orders=[])
    reconcile("XRP_JPY", state, c, execute=True)
    assert c.calls == ["send_order BUY LIMIT @ 171.996"]


def test_desired_holds_live_flat_warns_instead_of_claiming_in_sync() -> None:
    state = _state([_pos(Side.LONG)])  # holding in shadow, nothing to place
    c = _FakeClient(positions=[], orders=[])
    lines: list[str] = []
    sink = logger.add(lines.append, level="WARNING")
    try:
        acts = reconcile("XRP_JPY", state, c, execute=True)
    finally:
        logger.remove(sink)
    assert c.calls == [] and acts == []
    assert any("OUT OF SYNC" in line for line in lines)


# ===================== multi-slot: pairing and per-position attribution ==============
#
# Desired positions carry no exchange positionId, so they are paired with live 建玉 by
# sorting both sides on keys fixed for a position's life and zipping. These tests pin
# that each position gets ITS OWN stop — a count-only check would pass while every
# position wore the wrong level.


def _three_longs() -> tuple[list[DesiredPosition], list[dict[str, Any]]]:
    desired = [_pos(Side.LONG, stop=100.0, entry=180.0, hours=0),
               _pos(Side.LONG, stop=101.0, entry=181.0, hours=1),
               _pos(Side.LONG, stop=102.0, entry=182.0, hours=2)]
    live = [_live(1, "BUY", price="180.0", hours=0),
            _live(2, "BUY", price="181.0", hours=1),
            _live(3, "BUY", price="182.0", hours=2)]
    return desired, live


def test_each_position_gets_its_own_stop() -> None:
    desired, live = _three_longs()
    c = _FakeClient(positions=live, orders=[])
    reconcile("XRP_JPY", _state(desired, max_slots=3, last_price=190.0), c, execute=True)
    assert c.calls == ["close 1 SELL STOP @ 100",
                       "close 2 SELL STOP @ 101",
                       "close 3 SELL STOP @ 102"]


def test_pairing_is_invariant_to_input_order() -> None:
    desired, live = _three_longs()
    c = _FakeClient(positions=list(reversed(live)), orders=[])
    reconcile("XRP_JPY", _state(list(reversed(desired)), max_slots=3, last_price=190.0),
              c, execute=True)
    assert c.calls == ["close 1 SELL STOP @ 100",
                       "close 2 SELL STOP @ 101",
                       "close 3 SELL STOP @ 102"]


def test_same_bar_same_side_positions_are_interchangeable() -> None:
    # The sim keys its ratchet on (entry_idx, side), so same-bar same-side positions
    # genuinely SHARE a stop — ties must resolve, not crash.
    desired = [_pos(Side.LONG, stop=100.0), _pos(Side.LONG, stop=100.0)]
    live = [_live(1, "BUY"), _live(2, "BUY")]
    c = _FakeClient(positions=live, orders=[])
    reconcile("XRP_JPY", _state(desired, max_slots=2, last_price=190.0), c, execute=True)
    assert c.calls == ["close 1 SELL STOP @ 100", "close 2 SELL STOP @ 100"]


def test_desired_more_than_live_takes_the_slot_and_places_no_entry() -> None:
    # Strategy holds 3, account holds 2 (one entered while down). Not adopted, but all
    # three slots count as taken -> the resting entry is for a slot the sim can't fill.
    desired, live = _three_longs()
    c = _FakeClient(positions=live[:2], orders=[])
    state = _state(desired, working=[(_sig(Side.LONG), 171.0, 999)], max_slots=3,
                   last_price=190.0)
    acts = reconcile("XRP_JPY", state, c, execute=True)
    assert c.calls == ["close 1 SELL STOP @ 100", "close 2 SELL STOP @ 101"]
    assert not any("entry" in a for a in acts)


def test_live_more_than_desired_closes_only_the_unmatched() -> None:
    desired, live = _three_longs()
    c = _FakeClient(positions=live, orders=[])
    reconcile("XRP_JPY", _state(desired[:2], max_slots=3, last_price=190.0), c, execute=True)
    # positions 1 and 2 keep their stops; the unmatched third is market-closed
    assert c.calls == ["close 1 SELL STOP @ 100", "close 2 SELL STOP @ 101",
                       "close 3 SELL MARKET"]


# ===================== multi-slot: cancels must be surgical =========================


def test_ratchet_on_one_slot_leaves_the_other_untouched() -> None:
    desired = [_pos(Side.LONG, stop=100.0, entry=180.0, hours=0),
               _pos(Side.LONG, stop=101.0, entry=181.0, hours=1)]
    live = [_live(1, "BUY", price="180.0", hours=0), _live(2, "BUY", price="181.0", hours=1)]
    orders = [_close_order(11, "STOP", "90.0", "SELL"),    # slot 1: stale, must ratchet
              _close_order(22, "STOP", "101.0", "SELL")]   # slot 2: already correct
    c = _FakeClient(positions=live, orders=orders)
    reconcile("XRP_JPY", _state(desired, max_slots=2, last_price=190.0), c, execute=True)
    assert c.calls == ["cancel_order 11", "close 1 SELL STOP @ 100"]
    assert not any("22" in call for call in c.calls)  # slot 2's order never touched


def test_strategy_exit_of_one_slot_leaves_the_other_protected() -> None:
    desired = [_pos(Side.LONG, stop=100.0, entry=180.0, hours=0)]
    live = [_live(1, "BUY", price="180.0", hours=0), _live(2, "BUY", price="181.0", hours=1)]
    orders = [_close_order(11, "STOP", "100.0", "SELL"),   # slot 1: correct, keep
              _close_order(22, "STOP", "95.0", "SELL")]    # slot 2: exits with it
    c = _FakeClient(positions=live, orders=orders)
    reconcile("XRP_JPY", _state(desired, max_slots=2, last_price=190.0), c, execute=True)
    assert c.calls == ["cancel_orders [22]", "close 2 SELL MARKET"]


def test_trail_clamp_on_one_slot_leaves_the_other() -> None:
    desired = [_pos(Side.LONG, stop=195.0, entry=180.0, hours=0),   # stop ABOVE market
               _pos(Side.LONG, stop=101.0, entry=181.0, hours=1)]   # healthy
    live = [_live(1, "BUY", price="180.0", hours=0), _live(2, "BUY", price="181.0", hours=1)]
    orders = [_close_order(11, "STOP", "90.0", "SELL"), _close_order(22, "STOP", "101.0", "SELL")]
    c = _FakeClient(positions=live, orders=orders)
    reconcile("XRP_JPY", _state(desired, max_slots=2, last_price=190.0), c, execute=True)
    assert c.calls == ["cancel_orders [11]", "close 1 SELL MARKET"]


def test_cancel_bulk_is_unreachable_outside_the_kill_switch() -> None:
    desired, live = _three_longs()
    orders = [_close_order(11, "STOP", "90.0", "SELL"),
              {"orderId": 77, "settleType": "OPEN", "side": "BUY", "price": "9.0"}]
    scenarios = [
        (_state(desired, max_slots=3, last_price=190.0), live, orders),        # holding
        (_state(desired[:1], max_slots=3, last_price=190.0), live, orders),    # partial exit
        (_state([], max_slots=3, last_price=190.0), live, orders),             # full exit
        (_state([], working=[(_sig(Side.LONG), 171.0, 999)], max_slots=3), [], orders),  # flat
        (_state(desired, max_slots=3, last_price=195.0), live, []),            # clamp
    ]
    for state, pos, ords in scenarios:
        c = _FakeClient(positions=pos, orders=ords)
        reconcile("XRP_JPY", state, c, execute=True)
        assert "cancel_bulk" not in c.calls, c.calls


def test_kill_switch_closes_every_position_distinctly(monkeypatch: Any) -> None:
    # Guards against a late-binding closure closing the same 建玉 three times.
    monkeypatch.setenv("KILL_SWITCH", "1")
    live = [_live(1, "BUY"), _live(2, "BUY"), _live(3, "SELL")]
    c = _FakeClient(positions=live, orders=[{"orderId": 1, "settleType": "OPEN"}])
    reconcile("XRP_JPY", _state([], max_slots=3), c, execute=True)
    assert c.calls == ["cancel_bulk", "close 1 SELL MARKET", "close 2 SELL MARKET",
                       "close 3 BUY MARKET"]


# ===================== duplicate-settle protection ==================================


def test_reserved_quantity_with_no_attributable_order_places_nothing() -> None:
    # GMO says the quantity is committed to a settle order we cannot attribute — adding
    # another would double up or be rejected. Do nothing; orphan cleanup converges it.
    desired = [_pos(Side.LONG, stop=100.0)]
    live = [_live(1, "BUY", reserved="10")]
    c = _FakeClient(positions=live, orders=[])
    reconcile("XRP_JPY", _state(desired, max_slots=1, last_price=190.0), c, execute=True)
    assert c.calls == []


def test_tp_not_retried_once_the_stop_reserves_the_quantity() -> None:
    # P1 unresolved: if GMO allows only ONE settle order per position, the TP leg must
    # stop being retried every cycle instead of failing forever.
    desired = [_pos(Side.LONG, stop=100.0, target=250.0)]
    live = [_live(1, "BUY", reserved="10")]
    orders = [_close_order(11, "STOP", "100.0", "SELL")]
    c = _FakeClient(positions=live, orders=orders)
    reconcile("XRP_JPY", _state(desired, max_slots=1, last_price=190.0), c, execute=True)
    assert c.calls == []  # stop is correct; TP skipped, not re-attempted


def test_tp_never_attempted_while_a_stop_is_wanted_even_with_free_quantity() -> None:
    # Attempting it would be a guaranteed ERR-200 on EVERY new position — a FAILED line
    # per entry, which trains the operator to ignore the audit trail.
    desired = [_pos(Side.LONG, stop=100.0, target=250.0)]
    live = [_live(1, "BUY", reserved="0")]
    c = _FakeClient(positions=live, orders=[])
    reconcile("XRP_JPY", _state(desired, max_slots=1, last_price=190.0), c, execute=True)
    assert c.calls == ["close 1 SELL STOP @ 100"]


def test_orphan_close_order_cancelled_without_touching_the_healthy_slot() -> None:
    desired = [_pos(Side.LONG, stop=100.0)]           # no target -> no LIMIT slot
    live = [_live(1, "BUY")]
    orders = [_close_order(11, "STOP", "100.0", "SELL"),   # attributed, correct
              _close_order(12, "LIMIT", "250.0", "SELL")]  # no slot to claim -> orphan
    c = _FakeClient(positions=live, orders=orders)
    reconcile("XRP_JPY", _state(desired, max_slots=1, last_price=190.0), c, execute=True)
    assert c.calls == ["cancel_orders [12]"]


def test_stale_stop_far_from_the_new_level_is_ratcheted_not_orphaned() -> None:
    # A 48-bar recalc moves the stop a long way; that drift is what this executor
    # corrects. It must never be read as "this order belongs to someone else".
    desired = [_pos(Side.LONG, stop=150.0)]
    live = [_live(1, "BUY")]
    orders = [_close_order(11, "STOP", "90.0", "SELL")]  # 40% away
    c = _FakeClient(positions=live, orders=orders)
    reconcile("XRP_JPY", _state(desired, max_slots=1, last_price=190.0), c, execute=True)
    assert c.calls == ["cancel_order 11", "close 1 SELL STOP @ 150"]


# ===================== entries across slots =========================================


def _held(n: int) -> tuple[list[DesiredPosition], list[dict[str, Any]]]:
    """n matched positions with no stop/target, so only entry actions show up."""
    d = [_pos(Side.LONG, stop=None, entry=180.0 + i, hours=i) for i in range(n)]
    lv = [_live(i + 1, "BUY", price=f"{180.0 + i}", hours=i) for i in range(n)]
    return d, lv


def test_multi_slot_places_several_entries() -> None:
    d, lv = _held(2)
    working = [(_sig(Side.LONG), 170.0, 999), (_sig(Side.LONG), 171.0, 999),
               (_sig(Side.LONG), 172.0, 999)]
    c = _FakeClient(positions=lv, orders=[])
    reconcile("XRP_JPY", _state(d, working=working, max_slots=6, last_price=190.0),
              c, execute=True)
    assert c.calls == ["send_order BUY LIMIT @ 170", "send_order BUY LIMIT @ 171",
                       "send_order BUY LIMIT @ 172"]


def test_cycle_is_idempotent_when_entries_already_rest_at_the_right_level() -> None:
    d, lv = _held(2)
    working = [(_sig(Side.LONG), 170.0, 999), (_sig(Side.LONG), 171.0, 999)]
    orders = [{"orderId": 61, "settleType": "OPEN", "side": "BUY", "price": "170.0"},
              {"orderId": 62, "settleType": "OPEN", "side": "BUY", "price": "171.0"}]
    c = _FakeClient(positions=lv, orders=orders)
    reconcile("XRP_JPY", _state(d, working=working, max_slots=6, last_price=190.0),
              c, execute=True)
    assert c.calls == []


def test_resting_entries_count_against_the_live_slot_budget() -> None:
    # 3 slots: 2 live positions + 1 resting entry = 3 of exposure. The second desired
    # entry must NOT be placed even though the sim would take it.
    d, lv = _held(2)
    working = [(_sig(Side.LONG), 170.0, 999), (_sig(Side.LONG), 171.0, 999)]
    orders = [{"orderId": 61, "settleType": "OPEN", "side": "BUY", "price": "170.0"}]
    c = _FakeClient(positions=lv, orders=orders)
    reconcile("XRP_JPY", _state(d, working=working, max_slots=3, last_price=190.0),
              c, execute=True)
    assert c.calls == []


def test_resting_entry_at_a_stale_level_is_cancelled_and_replaced() -> None:
    working = [(_sig(Side.LONG), 180.0, 999)]
    orders = [{"orderId": 55, "settleType": "OPEN", "side": "BUY", "price": "200.0"}]
    c = _FakeClient(positions=[], orders=orders)
    reconcile("XRP_JPY", _state([], working=working, max_slots=1, last_price=190.0),
              c, execute=True)
    assert c.calls == ["cancel_orders [55]", "send_order BUY LIMIT @ 180"]


def test_entry_price_drift_inside_tolerance_does_not_churn() -> None:
    working = [(_sig(Side.LONG), 180.0, 999)]
    orders = [{"orderId": 55, "settleType": "OPEN", "side": "BUY", "price": "180.05"}]
    c = _FakeClient(positions=[], orders=orders)
    reconcile("XRP_JPY", _state([], working=working, max_slots=1, last_price=190.0),
              c, execute=True)
    assert c.calls == []


# ===================== anomaly, drain, ceiling, margin ==============================


def test_full_book_is_not_an_anomaly() -> None:
    desired, live = _three_longs()
    c = _FakeClient(positions=live, orders=[])
    acts = reconcile("XRP_JPY", _state(desired, max_slots=3, last_price=190.0), c, execute=True)
    assert not any(a.startswith("HALT") for a in acts)
    assert len(c.calls) == 3


def test_more_positions_than_slots_halts() -> None:
    _desired, live = _three_longs()
    c = _FakeClient(positions=live, orders=[])
    acts = reconcile("XRP_JPY", _state([], max_slots=2), c, execute=True)
    assert c.calls == [] and acts[0].startswith("HALT:")


def test_drain_mode_winds_down_instead_of_freezing(monkeypatch: Any) -> None:
    monkeypatch.setenv("LIVE_DRAIN_OK", "1")
    desired, live = _three_longs()
    state = _state(desired[:2], working=[(_sig(Side.LONG), 171.0, 999)], max_slots=2,
                   last_price=190.0)
    c = _FakeClient(positions=live, orders=[])
    acts = reconcile("XRP_JPY", state, c, execute=True)
    assert not any(a.startswith("HALT") for a in acts)
    # exits still maintained, the unmatched position closed, and NO new entry
    assert c.calls == ["close 1 SELL STOP @ 100", "close 2 SELL STOP @ 101",
                       "close 3 SELL MARKET"]


def test_undersized_position_stub_halts() -> None:
    c = _FakeClient(positions=[_live(1, "BUY", size="4")], orders=[])
    acts = reconcile("XRP_JPY", _state([], max_slots=2), c, execute=True)
    assert c.calls == [] and acts[0].startswith("HALT:")


def test_unknown_symbol_halts() -> None:
    c = _FakeClient(positions=[_live(1, "BUY")], orders=[])
    acts = reconcile("DOGE_JPY", _state([], max_slots=2), c, execute=True)
    assert c.calls == [] and acts[0].startswith("HALT:")


def test_slot_ceiling_clamps_a_misconfigured_book() -> None:
    # max_slots=99 from a mis-typed AUTO_BOOKS must not authorise 99 live positions.
    live = [_live(i, "BUY") for i in range(1, 10)]  # 9 > the hard ceiling of 8
    c = _FakeClient(positions=live, orders=[])
    acts = reconcile("XRP_JPY", _state([], max_slots=99), c, execute=True)
    assert c.calls == [] and acts[0].startswith("HALT:")


def test_thin_margin_clamps_entries_but_never_exits() -> None:
    # required per slot = 10 * 180 / 2 * 1.5 = 1350 JPY; only 1000 available -> 0 entries.
    desired = [_pos(Side.LONG, stop=100.0)]
    live = [_live(1, "BUY")]
    working = [(_sig(Side.LONG), 170.0, 999)]
    c = _MarginClient(positions=live, orders=[],
                      margin={"availableAmount": "1000", "marginRatio": "900"})
    reconcile("XRP_JPY", _state(desired, working=working, max_slots=3, last_price=180.0),
              c, execute=True)
    assert c.calls == ["close 1 SELL STOP @ 100"]  # exit placed, entry withheld


def test_margin_read_failure_blocks_entries_but_never_exits() -> None:
    desired = [_pos(Side.LONG, stop=100.0)]
    live = [_live(1, "BUY")]
    working = [(_sig(Side.LONG), 170.0, 999)]
    c = _MarginClient(positions=live, orders=[], margin=None)  # get_margin() raises
    reconcile("XRP_JPY", _state(desired, working=working, max_slots=3, last_price=180.0),
              c, execute=True)
    assert c.calls == ["close 1 SELL STOP @ 100"]


def test_healthy_margin_allows_the_entry() -> None:
    desired = [_pos(Side.LONG, stop=100.0)]
    live = [_live(1, "BUY")]
    working = [(_sig(Side.LONG), 170.0, 999)]
    c = _MarginClient(positions=live, orders=[],
                      margin={"availableAmount": "500000", "marginRatio": "900"})
    reconcile("XRP_JPY", _state(desired, working=working, max_slots=3, last_price=180.0),
              c, execute=True)
    assert c.calls == ["close 1 SELL STOP @ 100", "send_order BUY LIMIT @ 170"]


def test_failed_action_is_recorded_not_swallowed(tmp_path: Path, monkeypatch: Any) -> None:
    # The 2026-08 TP defect: record() ran only after fn() returned, and auto_trader
    # swallows per-book exceptions, so a rejected order left no trace anywhere.
    import json

    log = tmp_path / "orders.jsonl"
    monkeypatch.setenv("ORDER_LOG", str(log))

    class _Rejecting(_FakeClient):
        def close_position(self, symbol: str, pid: int, side: str, size: float,
                           **kw: Any) -> str:
            raise RuntimeError("ERR-5201 rejected")

    c = _Rejecting(positions=[_live(1, "BUY")], orders=[])
    acts = reconcile("XRP_JPY", _state([_pos(Side.LONG, stop=100.0)], max_slots=1,
                                       last_price=190.0), c, execute=True)
    assert any(a.startswith("FAILED:") for a in acts)
    rows = [json.loads(x) for x in log.read_text().splitlines()]
    assert any("FAILED" in r["action"] and "ERR-5201" in str(r["result"]) for r in rows)


# ===================== adversarial: hostile / malformed exchange rows ===============
#
# These do not test the happy path. Each one asks: "if the exchange hands us a row we
# did not anticipate, does the executor fail SAFE (halt / skip loudly) or fail OPEN
# (crash the book, or silently leave real exposure unmanaged)?" A crash inside the
# per-position loop is the dangerous one: auto_trader swallows per-book exceptions, so
# it would silently stop maintaining EVERY other slot's protective stop.


def test_position_without_position_id_does_not_strand_the_other_slots() -> None:
    # A row we cannot address must not take the whole book down with it.
    desired = [_pos(Side.LONG, stop=100.0, entry=180.0, hours=0),
               _pos(Side.LONG, stop=101.0, entry=181.0, hours=1)]
    live = [{"side": "BUY", "size": "10", "price": "180.0"},          # no positionId
            _live(2, "BUY", price="181.0", hours=1)]
    c = _FakeClient(positions=live, orders=[])
    acts = reconcile("XRP_JPY", _state(desired, max_slots=2, last_price=190.0), c, execute=True)
    # Either halt cleanly, or protect what it can — but never raise, and never claim
    # everything is fine while an unaddressable position sits there unmanaged.
    assert acts, "reconcile returned no actions at all for an unaddressable position"
    assert acts[0].startswith("HALT:") or any("close 2" in call for call in c.calls)


def test_position_with_unrecognised_side_is_not_silently_ignored() -> None:
    # _match_positions buckets by BUY/SELL. A row that is neither lands in no bucket:
    # it would be neither maintained nor closed — real exposure, invisible to the bot.
    live = [{"positionId": 1, "side": "", "size": "10", "price": "180.0"}]
    c = _FakeClient(positions=live, orders=[])
    acts = reconcile("XRP_JPY", _state([], max_slots=2, last_price=190.0), c, execute=True)
    assert acts, "an unrecognised-side position was silently ignored"
    assert acts[0].startswith("HALT:") or any("close 1" in call for call in c.calls)


def test_kill_switch_still_flattens_when_one_row_is_malformed(monkeypatch: Any) -> None:
    # The emergency stop must be the most robust path in the system: one bad row must
    # not stop it from flattening everything else.
    monkeypatch.setenv("KILL_SWITCH", "1")
    live = [{"side": "BUY", "size": "10"},        # unaddressable
            _live(2, "BUY"), _live(3, "SELL")]
    c = _FakeClient(positions=live, orders=[])
    reconcile("XRP_JPY", _state([], max_slots=3), c, execute=True)
    assert "close 2 SELL MARKET" in c.calls and "close 3 BUY MARKET" in c.calls


def test_duplicate_position_ids_do_not_cross_wire_exits() -> None:
    # Two rows claiming the same 建玉 id: whatever happens, we must not send two
    # different stops for the same id, nor silently protect only one of them.
    desired = [_pos(Side.LONG, stop=100.0, entry=180.0, hours=0),
               _pos(Side.LONG, stop=101.0, entry=181.0, hours=1)]
    live = [_live(7, "BUY", price="180.0", hours=0), _live(7, "BUY", price="181.0", hours=1)]
    c = _FakeClient(positions=live, orders=[])
    acts = reconcile("XRP_JPY", _state(desired, max_slots=2, last_price=190.0), c, execute=True)
    stops = [x for x in c.calls if "STOP" in x]
    assert acts[0].startswith("HALT:") or len(set(stops)) == len(stops), stops


# ===================== adversarial: arithmetic edges ================================


def test_zero_priced_working_order_does_not_crash_the_book() -> None:
    # A 0.0 limit price would be an upstream bug, but a ZeroDivisionError here loses
    # management of every position in the book for that cycle.
    orders = [{"orderId": 55, "settleType": "OPEN", "side": "BUY", "price": "180.0"}]
    c = _FakeClient(positions=[], orders=orders)
    reconcile("XRP_JPY", _state([], working=[(_sig(Side.LONG), 0.0, 999)], max_slots=1),
              c, execute=True)  # must not raise


def test_zero_desired_stop_does_not_crash_the_ratchet() -> None:
    desired = [_pos(Side.LONG, stop=0.0)]
    live = [_live(1, "BUY")]
    orders = [_close_order(11, "STOP", "100.0", "SELL")]
    c = _FakeClient(positions=live, orders=orders)
    reconcile("XRP_JPY", _state(desired, max_slots=1, last_price=190.0), c, execute=True)


def test_unparseable_resting_stop_price_is_replaced_not_trusted() -> None:
    # If we cannot read the resting stop's price we cannot know it is at the right
    # level. Leaving it is silently holding a possibly-stale stop.
    desired = [_pos(Side.LONG, stop=150.0)]
    live = [_live(1, "BUY")]
    orders = [{"orderId": 11, "settleType": "CLOSE", "executionType": "STOP",
               "price": "n/a", "side": "SELL"}]
    c = _FakeClient(positions=live, orders=orders)
    reconcile("XRP_JPY", _state(desired, max_slots=1, last_price=190.0), c, execute=True)
    assert c.calls == ["cancel_order 11", "close 1 SELL STOP @ 150"]


def test_resting_stop_without_an_order_id_is_reported_not_silently_kept() -> None:
    # No id means we cannot surgically cancel it, so the ratchet cannot happen. That
    # must be loud — otherwise the position quietly wears a stale stop forever.
    desired = [_pos(Side.LONG, stop=150.0)]
    live = [_live(1, "BUY")]
    orders = [{"settleType": "CLOSE", "executionType": "STOP", "price": "90.0", "side": "SELL"}]
    c = _FakeClient(positions=live, orders=orders)
    lines: list[str] = []
    sink = logger.add(lines.append, level="WARNING")
    try:
        reconcile("XRP_JPY", _state(desired, max_slots=1, last_price=190.0), c, execute=True)
    finally:
        logger.remove(sink)
    assert lines, "a stop that cannot be ratcheted was kept without any warning"


# ===================== adversarial: semantics =======================================


def test_side_flip_closes_the_old_side_and_adopts_nothing() -> None:
    # Strategy flipped LONG -> SHORT. The live long must be closed; the new short must
    # NOT be adopted mid-flight (entering now is a different trade than the backtest's).
    c = _FakeClient(positions=[_live(1, "BUY")], orders=[])
    acts = reconcile("XRP_JPY", _state([_pos(Side.SHORT, stop=190.0)], max_slots=1,
                                       last_price=180.0), c, execute=True)
    assert c.calls == ["close 1 SELL MARKET"]
    assert not any("entry" in a for a in acts)


def test_close_order_on_the_wrong_side_is_orphaned() -> None:
    # A BUY close order cannot close a BUY position. It is not this position's exit.
    desired = [_pos(Side.LONG, stop=100.0)]
    live = [_live(1, "BUY")]
    orders = [_close_order(11, "STOP", "100.0", "BUY")]  # wrong side
    c = _FakeClient(positions=live, orders=orders)
    reconcile("XRP_JPY", _state(desired, max_slots=1, last_price=190.0), c, execute=True)
    assert "cancel_orders [11]" in c.calls
    assert any("close 1 SELL STOP" in x for x in c.calls)  # the real stop still placed


def test_target_without_stop_places_only_the_tp() -> None:
    desired = [_pos(Side.LONG, stop=None, target=250.0)]
    live = [_live(1, "BUY")]
    c = _FakeClient(positions=live, orders=[])
    reconcile("XRP_JPY", _state(desired, max_slots=1, last_price=190.0), c, execute=True)
    assert c.calls == ["close 1 SELL LIMIT @ 250"]


def test_entry_order_on_the_wrong_side_is_cancelled_and_the_right_one_placed() -> None:
    working = [(_sig(Side.SHORT), 180.0, 999)]
    orders = [{"orderId": 55, "settleType": "OPEN", "side": "BUY", "price": "180.0"}]
    c = _FakeClient(positions=[], orders=orders)
    reconcile("XRP_JPY", _state([], working=working, max_slots=1, last_price=190.0),
              c, execute=True)
    assert c.calls == ["cancel_orders [55]", "send_order SELL LIMIT @ 180"]


# ===================== adversarial: convergence across cycles =======================


def test_second_cycle_is_a_no_op_after_the_first_placed_everything() -> None:
    # Non-convergence is the multi-slot failure that costs money quietly: churn means
    # cancel/replace every hour, paying spread and racing fills. Replay cycle 1's
    # effects into cycle 2's exchange state and demand silence.
    desired = [_pos(Side.LONG, stop=100.0, entry=180.0, hours=0, target=250.0),
               _pos(Side.LONG, stop=101.0, entry=181.0, hours=1, target=251.0)]
    live = [_live(1, "BUY", price="180.0", hours=0), _live(2, "BUY", price="181.0", hours=1)]
    working = [(_sig(Side.LONG), 170.0, 999)]
    state = _state(desired, working=working, max_slots=3, last_price=190.0)

    c1 = _FakeClient(positions=live, orders=[])
    reconcile("XRP_JPY", state, c1, execute=True)
    assert c1.calls, "first cycle placed nothing"

    # Cycle 2: the exchange now shows exactly what cycle 1 created.
    after = [_close_order(101, "STOP", "100.0", "SELL"),
             _close_order(102, "LIMIT", "250.0", "SELL"),
             _close_order(201, "STOP", "101.0", "SELL"),
             _close_order(202, "LIMIT", "251.0", "SELL"),
             {"orderId": 301, "settleType": "OPEN", "side": "BUY", "price": "170.0"}]
    c2 = _FakeClient(positions=live, orders=after)
    reconcile("XRP_JPY", state, c2, execute=True)
    assert c2.calls == [], f"executor churns on an unchanged book: {c2.calls}"


def test_no_churn_when_two_slots_share_an_identical_stop_level() -> None:
    # Same-bar same-side positions SHARE a ratchet stop, so both resting stops sit at
    # the same price. Attribution must stay stable rather than swapping them each cycle.
    desired = [_pos(Side.LONG, stop=100.0), _pos(Side.LONG, stop=100.0)]
    live = [_live(1, "BUY"), _live(2, "BUY")]
    orders = [_close_order(11, "STOP", "100.0", "SELL"), _close_order(22, "STOP", "100.0", "SELL")]
    c = _FakeClient(positions=live, orders=orders)
    reconcile("XRP_JPY", _state(desired, max_slots=2, last_price=190.0), c, execute=True)
    assert c.calls == [], f"churn on identical shared stops: {c.calls}"


# ===================== adversarial round 2: containment and invariants =============
#
# Round 1 asked "does a malformed row break it?". Round 2 asks the harder questions:
# when one action FAILS, does the damage stay contained? And do the structural
# invariants hold across states no hand-written test would think to write?


class _PartlyRejecting(_FakeClient):
    """Rejects any close for `bad_pid`; everything else succeeds."""

    bad_pid = 1

    def close_position(self, symbol: str, pid: int, side: str, size: float, **kw: Any) -> str:
        if pid == self.bad_pid:
            raise RuntimeError("ERR-5106 rejected")
        return super().close_position(symbol, pid, side, size, **kw)


def test_one_positions_rejected_stop_does_not_strand_the_others() -> None:
    # The whole point of containing failures in do(): slot 1 being rejected must not
    # leave slots 2 and 3 unprotected for the rest of the hour.
    desired, live = _three_longs()
    c = _PartlyRejecting(positions=live, orders=[])
    acts = reconcile("XRP_JPY", _state(desired, max_slots=3, last_price=190.0), c, execute=True)
    assert any(a.startswith("FAILED:") for a in acts)
    assert "close 2 SELL STOP @ 101" in c.calls and "close 3 SELL STOP @ 102" in c.calls


def test_kill_switch_flattens_even_when_the_bulk_cancel_fails(monkeypatch: Any) -> None:
    # If cancelling fails we must STILL flatten — an un-cancelled order is survivable,
    # an un-flattened position during an emergency stop is not.
    class _CancelFails(_FakeClient):
        def cancel_bulk(self, symbol: str) -> None:
            raise RuntimeError("cancel API down")

    monkeypatch.setenv("KILL_SWITCH", "1")
    c = _CancelFails(positions=[_live(1, "BUY"), _live(2, "SELL")],
                     orders=[{"orderId": 1, "settleType": "OPEN"}])
    acts = reconcile("XRP_JPY", _state([], max_slots=2), c, execute=True)
    assert any(a.startswith("FAILED:") for a in acts)
    assert "close 1 SELL MARKET" in c.calls and "close 2 BUY MARKET" in c.calls


def test_failed_entry_does_not_block_the_remaining_entries() -> None:
    class _FirstSendFails(_FakeClient):
        n = 0

        def send_order(self, symbol: str, side: str, **kw: Any) -> str:
            self.n += 1
            if self.n == 1:
                raise RuntimeError("ERR-5115 price not tick-snapped")
            return super().send_order(symbol, side, **kw)

    working = [(_sig(Side.LONG), 170.0, 999), (_sig(Side.LONG), 171.0, 999)]
    c = _FirstSendFails(positions=[], orders=[])
    reconcile("XRP_JPY", _state([], working=working, max_slots=3, last_price=190.0),
              c, execute=True)
    assert c.calls == ["send_order BUY LIMIT @ 171"]  # the second one still went


def test_order_with_unknown_settle_type_is_not_left_unmanaged() -> None:
    # settleType is filtered on an exact OPEN/CLOSE match. Anything else falls through
    # both buckets: never cancelled, never counted against a slot — a resting order the
    # bot has forgotten about, which can still FILL.
    orders = [{"orderId": 44, "settleType": "", "side": "BUY", "price": "180.0"}]
    c = _FakeClient(positions=[], orders=orders)
    lines: list[str] = []
    sink = logger.add(lines.append, level="WARNING")
    try:
        reconcile("XRP_JPY", _state([], max_slots=2, last_price=190.0), c, execute=True)
    finally:
        logger.remove(sink)
    assert c.calls or lines, "an unclassifiable resting order was silently ignored"


def test_full_book_places_no_entry_even_with_a_live_signal() -> None:
    desired, live = _three_longs()
    state = _state(desired, working=[(_sig(Side.LONG), 171.0, 999)], max_slots=3,
                   last_price=190.0)
    c = _FakeClient(positions=live, orders=[])
    reconcile("XRP_JPY", state, c, execute=True)
    assert not any("send_order" in x for x in c.calls)


def test_duplicate_working_orders_at_one_price_do_not_double_claim() -> None:
    # Two identical desired entries, one resting order: exactly one must be placed.
    working = [(_sig(Side.LONG), 170.0, 999), (_sig(Side.LONG), 170.0, 999)]
    orders = [{"orderId": 61, "settleType": "OPEN", "side": "BUY", "price": "170.0"}]
    c = _FakeClient(positions=[], orders=orders)
    reconcile("XRP_JPY", _state([], working=working, max_slots=3, last_price=190.0),
              c, execute=True)
    assert c.calls == ["send_order BUY LIMIT @ 170"]


def test_match_positions_never_loses_or_duplicates_a_position() -> None:
    # The structural invariant behind the round-1 "unrecognised side" bug: a live
    # position dropped by the bucketing is real exposure nobody is managing.
    import random

    from src.execution.live_executor import _match_positions

    rng = random.Random(20260808)
    for _ in range(400):
        desired = [_pos(rng.choice([Side.LONG, Side.SHORT]), stop=rng.uniform(50, 250),
                        entry=rng.uniform(100, 200), hours=rng.randint(0, 5))
                   for _ in range(rng.randint(0, 6))]
        live = [_live(i + 1, rng.choice(["BUY", "SELL"]), price=f"{rng.uniform(100, 200):.3f}",
                      hours=rng.randint(0, 5))
                for i in range(rng.randint(0, 6))]
        p = _match_positions(desired, live)
        seen_live = [id(x) for _d, x in p.matched] + [id(x) for x in p.live_only]
        seen_desired = [id(d) for d, _x in p.matched] + [id(d) for d in p.desired_only]
        assert sorted(seen_live) == sorted(id(x) for x in live)
        assert sorted(seen_desired) == sorted(id(d) for d in desired)
        for d, lv in p.matched:  # a pair must never straddle sides
            assert (d.side is Side.LONG) == (str(lv["side"]).upper() == "BUY")


def test_close_order_assignment_never_loses_or_reuses_an_order() -> None:
    import random

    from src.execution.live_executor import _assign_close_orders, _match_positions

    rng = random.Random(4242)
    for _ in range(400):
        desired = [_pos(Side.LONG, stop=rng.uniform(50, 250), entry=100.0 + i, hours=i,
                        target=rng.choice([None, rng.uniform(250, 400)]))
                   for i in range(rng.randint(0, 4))]
        live = [_live(i + 1, "BUY", price=f"{100.0 + i}", hours=i)
                for i in range(rng.randint(0, 4))]
        orders = [_close_order(100 + i, rng.choice(["STOP", "LIMIT"]),
                               f"{rng.uniform(50, 400):.2f}", "SELL")
                  for i in range(rng.randint(0, 6))]
        p = _match_positions(desired, live)
        assigned, orphans = _assign_close_orders(p.matched, p.live_only, orders)
        placed = [id(o) for by_type in assigned.values() for o in by_type.values()]
        assert sorted(placed + [id(o) for o in orphans]) == sorted(id(o) for o in orders)
        assert len(placed) == len(set(placed)), "an order was assigned to two slots"


def test_fuzz_reconcile_holds_its_safety_invariants() -> None:
    # Random books. We do not assert WHAT it does — only that the properties that keep
    # this thing safe never break: it never raises, never bulk-cancels, never exceeds
    # the slot budget on entries, and never sends two exits for the same position+type.
    import random
    import re

    rng = random.Random(31337)
    for _ in range(400):
        slots = rng.randint(1, 6)
        desired = [_pos(rng.choice([Side.LONG, Side.SHORT]),
                        stop=rng.choice([None, rng.uniform(50, 250)]),
                        entry=100.0 + i, hours=i,
                        target=rng.choice([None, rng.uniform(250, 400)]))
                   for i in range(rng.randint(0, slots))]
        live = [_live(i + 1, rng.choice(["BUY", "SELL"]), price=f"{100.0 + i}", hours=i,
                      reserved=rng.choice([None, "0", "10"]))
                for i in range(rng.randint(0, slots))]
        orders = [_close_order(100 + i, rng.choice(["STOP", "LIMIT"]),
                               f"{rng.uniform(50, 400):.2f}", rng.choice(["BUY", "SELL"]))
                  for i in range(rng.randint(0, 4))]
        orders += [{"orderId": 200 + i, "settleType": "OPEN",
                    "side": rng.choice(["BUY", "SELL"]), "price": f"{rng.uniform(50, 250):.2f}"}
                   for i in range(rng.randint(0, 3))]
        working = [(_sig(rng.choice([Side.LONG, Side.SHORT])), rng.uniform(50, 250), 999)
                   for _ in range(rng.randint(0, 3))]
        state = _state(desired, working=working, max_slots=slots,
                       last_price=rng.choice([None, rng.uniform(50, 250)]))
        c = _FakeClient(positions=live, orders=orders)
        acts = reconcile("XRP_JPY", state, c, execute=True)  # must never raise

        assert "cancel_bulk" not in c.calls
        if acts and acts[0].startswith("HALT:"):
            assert c.calls == []
            continue
        assert sum(1 for x in c.calls if x.startswith("send_order")) <= slots
        exits = [m.groups() for m in
                 (re.match(r"close (\d+) \w+ (STOP|LIMIT)", x) for x in c.calls) if m]
        assert len(exits) == len(set(exits)), f"duplicate exit order: {c.calls}"


# ===================== adversarial round 3: multi-cycle convergence =================


class _StatefulExchange:
    """A toy GMO that actually APPLIES the executor's orders.

    Single-cycle tests can only check one step. Churn — cancel/replace every hour,
    paying spread and racing fills — only shows up when the exchange state fed to
    cycle N+1 is what cycle N created. Assumes a position may carry both a resting
    STOP and LIMIT (question P1); the ``orderd`` variant below assumes it may not.
    """

    def __init__(self, positions: list[dict[str, Any]], *, reserve: bool = False) -> None:
        self.positions = list(positions)
        self.orders: list[dict[str, Any]] = []
        self.reserve = reserve  # emulate GMO reserving quantity on the first settle order
        self._next = 9000
        self.calls: list[str] = []

    def _oid(self) -> int:
        self._next += 1
        return self._next

    def get_open_positions(self, symbol: str) -> list[dict[str, Any]]:
        return list(self.positions)

    def get_active_orders(self, symbol: str) -> list[dict[str, Any]]:
        return list(self.orders)

    def send_order(self, symbol: str, side: str, **kw: Any) -> str:
        oid = self._oid()
        self.calls.append(f"send_order {side}")
        self.orders.append({"orderId": oid, "settleType": "OPEN", "side": side,
                            "executionType": kw.get("execution_type"),
                            "price": str(kw.get("price"))})
        return str(oid)

    def close_position(self, symbol: str, pid: int, side: str, size: float, **kw: Any) -> str:
        et = str(kw.get("execution_type", "MARKET")).upper()
        self.calls.append(f"close {pid} {et}")
        if et == "MARKET":
            self.positions = [p for p in self.positions if int(p["positionId"]) != pid]
            return str(self._oid())
        oid = self._oid()
        self.orders.append({"orderId": oid, "settleType": "CLOSE", "side": side,
                            "executionType": et, "price": str(kw.get("price"))})
        if self.reserve:
            for p in self.positions:
                if int(p["positionId"]) == pid:
                    p["orderdSize"] = p["size"]
        return str(oid)

    def cancel_order(self, order_id: int) -> None:
        self.calls.append(f"cancel_order {order_id}")
        self.orders = [o for o in self.orders if int(o["orderId"]) != int(order_id)]

    def cancel_orders(self, order_ids: list[int]) -> None:
        self.calls.append(f"cancel_orders {sorted(int(o) for o in order_ids)}")
        drop = {int(o) for o in order_ids}
        self.orders = [o for o in self.orders if int(o["orderId"]) not in drop]

    def cancel_bulk(self, symbol: str) -> None:
        self.calls.append("cancel_bulk")
        self.orders = []


def test_repeated_cycles_on_an_unchanging_book_go_quiet() -> None:
    # The strategy's desired book is fixed (as it is between bars). However many times
    # the hourly loop fires, it must reach a fixed point and then do NOTHING.
    import random

    rng = random.Random(90210)
    for reserve in (False, True):  # both answers to the open P1 question
        for _ in range(200):
            slots = rng.randint(1, 5)
            n = rng.randint(1, slots)
            desired = [_pos(Side.LONG, stop=rng.uniform(50, 150), entry=100.0 + i, hours=i,
                            target=rng.choice([None, rng.uniform(250, 400)]))
                       for i in range(n)]
            live = [_live(i + 1, "BUY", price=f"{100.0 + i}", hours=i) for i in range(n)]
            # limit entries only: a MARKET entry leaves no resting artifact by design.
            working = [(_sig(Side.LONG), rng.uniform(50, 90), 999)
                       for _ in range(rng.randint(0, 2))]
            state = _state(desired, working=working, max_slots=slots, last_price=200.0)

            ex = _StatefulExchange(live, reserve=reserve)
            reconcile("XRP_JPY", state, ex, execute=True)   # cycle 1: set everything up
            ex.calls.clear()
            reconcile("XRP_JPY", state, ex, execute=True)   # cycle 2: mop up orphans
            ex.calls.clear()
            reconcile("XRP_JPY", state, ex, execute=True)   # cycle 3: must be silent
            assert ex.calls == [], f"churn (reserve={reserve}): {ex.calls}"


def test_ratchet_converges_instead_of_flip_flopping() -> None:
    # Tighten the stop each cycle, as the ratchet does, and confirm each move costs
    # exactly one cancel+replace — never a repeated replace at the same level.
    live = [_live(1, "BUY", price="100.0")]
    ex = _StatefulExchange(live)
    for stop in (80.0, 85.0, 90.0):
        for _ in range(3):  # same desired stop three times: only the FIRST may act
            reconcile("XRP_JPY", _state([_pos(Side.LONG, stop=stop, entry=100.0)],
                                        max_slots=1, last_price=200.0), ex, execute=True)
        placements = [c for c in ex.calls if c.startswith("close 1 STOP")]
        assert len(placements) == 1, f"stop {stop} placed {len(placements)}x: {ex.calls}"
        ex.calls.clear()


def test_known_hazard_market_entry_repeats_if_rerun_inside_the_same_bar() -> None:
    # NOT a pass/fail of correctness — a pinned, documented hazard. A pending MARKET
    # entry leaves no resting artifact, so a second run before the sim advances a bar
    # re-sends it. Mitigation is operational: one run per bar (the HH:05 timer). Never
    # hand-run the trader inside a bar while a market entry is pending.
    state = _state([], pending=[_sig(Side.LONG)], max_slots=2, last_price=200.0)
    ex = _StatefulExchange([])
    reconcile("XRP_JPY", state, ex, execute=True)
    assert ex.calls == ["send_order BUY"]
    ex.positions.append(_live(1, "BUY", price="179.0"))  # it filled
    ex.calls.clear()
    reconcile("XRP_JPY", state, ex, execute=True)
    # The desired book still shows 0 open + 1 pending, so the freshly-filled position
    # looks unwanted (closed) and the entry is re-sent. Same behaviour as the 1-slot
    # executor; it is why the trader must fire once per bar.
    assert ex.calls, "hazard disappeared — update docs/deploy.md if this was fixed"


def test_exposure_cap_blocks_entries_but_never_exits() -> None:
    # A book over MAX_BOOK_NOTIONAL_JPY must stop adding risk WITHOUT stranding the risk
    # already on: an exposure cap that leaves live positions unratcheted is worse than
    # the exposure it prevents. Same principle as the fail-soft AUTO_BOOKS parsing.
    desired = [_pos(Side.LONG, stop=100.0)]
    live = [_live(1, "BUY")]
    working = [(_sig(Side.LONG), 170.0, 999)]
    c = _FakeClient(positions=live, orders=[])
    reconcile("XRP_JPY", _state(desired, working=working, max_slots=3, last_price=190.0),
              c, execute=True, allow_entries=False)
    assert c.calls == ["close 1 SELL STOP @ 100"]  # stop maintained, entry withheld


def test_exposure_cap_still_cleans_up_stale_and_orphaned_orders() -> None:
    # Cleanup is never rationed — a blocked book must not accumulate stray orders.
    orders = [{"orderId": 55, "settleType": "OPEN", "side": "BUY", "price": "200.0"},
              _close_order(66, "LIMIT", "250.0", "SELL")]
    c = _FakeClient(positions=[], orders=orders)
    reconcile("XRP_JPY", _state([], max_slots=3, last_price=190.0), c, execute=True,
              allow_entries=False)
    assert "cancel_orders [66]" in c.calls and "cancel_orders [55]" in c.calls


def test_partly_adopted_book_never_reports_itself_in_sync() -> None:
    # Reproduces the live 2026-08-08 05:56 cycle: raising :slots 1->2 mid-flight made the
    # simulator's replay take a trade live never took, so one desired position is matched
    # and one is unadopted. The summary line must not contradict the OUT OF SYNC warning.
    desired = [_pos(Side.LONG, stop=100.0, entry=180.0, hours=0),
               _pos(Side.LONG, stop=101.0, entry=181.0, hours=1)]
    live = [_live(1, "BUY", price="180.0", hours=0)]
    orders = [_close_order(11, "STOP", "100.0", "SELL")]  # already correct -> no actions
    c = _FakeClient(positions=live, orders=orders)
    lines: list[str] = []
    sink = logger.add(lines.append, level="INFO")
    try:
        acts = reconcile("XRP_JPY", _state(desired, max_slots=2, last_price=190.0),
                         c, execute=True)
    finally:
        logger.remove(sink)
    assert c.calls == [] and acts == []
    assert not any("in sync (desired == live)" in x for x in lines), lines
    assert any("NOT adopted" in x for x in lines), lines


def test_fully_matched_book_still_reports_in_sync() -> None:
    desired = [_pos(Side.LONG, stop=100.0)]
    live = [_live(1, "BUY")]
    orders = [_close_order(11, "STOP", "100.0", "SELL")]
    c = _FakeClient(positions=live, orders=orders)
    lines: list[str] = []
    sink = logger.add(lines.append, level="INFO")
    try:
        reconcile("XRP_JPY", _state(desired, max_slots=2, last_price=190.0), c, execute=True)
    finally:
        logger.remove(sink)
    assert any("in sync (desired == live)" in x for x in lines), lines
