"""Tests for the 1-slot live executor (mocked client; no network)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.core.types import Side, Signal
from src.execution.live_executor import reconcile
from src.simulator.multi_simulator import DesiredPosition, LiveBookState

_T = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _FakeClient:
    """Records order calls; returns the configured positions/orders."""

    def __init__(self, positions: list[dict[str, Any]], orders: list[dict[str, Any]]) -> None:
        self._positions = positions
        self._orders = orders
        self.calls: list[str] = []

    def get_open_positions(self, symbol: str) -> list[dict[str, Any]]:
        return self._positions

    def get_active_orders(self, symbol: str) -> list[dict[str, Any]]:
        return self._orders

    def send_order(self, symbol: str, side: str, **kw: Any) -> str:
        self.calls.append(f"send_order {side} {kw.get('execution_type')}")
        return "OID"

    def close_position(self, symbol: str, pid: int, side: str, size: float, **kw: Any) -> str:
        self.calls.append(f"close {pid} {side} {kw.get('execution_type')}")
        return "OID"

    def cancel_bulk(self, symbol: str) -> None:
        self.calls.append("cancel_bulk")


def _state(positions: list[DesiredPosition], working: list[Any] = [], pending: list[Signal] = []) -> LiveBookState:
    return LiveBookState(positions=positions, pending_entries=pending, working_orders=working, last_bar_time=_T)


def _pos(side: Side, stop: float | None = 170.0) -> DesiredPosition:
    return DesiredPosition(side=side, entry_time=_T, entry_price=180.0, current_stop=stop,
                           target=None, bars_held=3, time_stop_bars=120)


def _sig(side: Side) -> Signal:
    return Signal(side=side, timestamp=_T, price=179.0)


def test_flat_with_resting_limit_places_entry() -> None:
    state = _state([], working=[(_sig(Side.SHORT), 179.5, 999)])
    c = _FakeClient(positions=[], orders=[])
    reconcile("XRP_JPY", state, c, execute=True)
    assert c.calls == ["send_order SELL LIMIT"]


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
    assert c.calls == ["close 7 BUY STOP"]  # SELL position -> BUY stop to close


def test_holding_with_current_stop_no_dup() -> None:
    state = _state([_pos(Side.SHORT, stop=185.0)])
    live = [{"positionId": 7, "side": "SELL", "size": "10"}]
    orders = [{"orderId": 1, "settleType": "CLOSE", "executionType": "STOP", "price": "185.0", "side": "BUY"}]
    c = _FakeClient(positions=live, orders=orders)
    reconcile("XRP_JPY", state, c, execute=True)
    assert c.calls == []  # stop already at the right level


def test_strategy_exit_closes_position() -> None:
    state = _state([])  # desired flat
    live = [{"positionId": 7, "side": "SELL", "size": "10"}]
    c = _FakeClient(positions=live, orders=[])
    reconcile("XRP_JPY", state, c, execute=True)
    assert c.calls == ["close 7 BUY MARKET"]


def test_anomaly_two_positions_halts() -> None:
    live = [{"positionId": 1, "side": "BUY", "size": "10"}, {"positionId": 2, "side": "SELL", "size": "10"}]
    c = _FakeClient(positions=live, orders=[])
    acts = reconcile("XRP_JPY", _state([]), c, execute=True)
    assert c.calls == [] and acts == ["HALT: anomalous live state"]


def test_kill_switch_flattens(monkeypatch: Any) -> None:
    monkeypatch.setenv("KILL_SWITCH", "1")
    live = [{"positionId": 9, "side": "BUY", "size": "10"}]
    c = _FakeClient(positions=live, orders=[{"orderId": 1, "settleType": "OPEN"}])
    reconcile("XRP_JPY", _state([_pos(Side.LONG)]), c, execute=True)
    assert "cancel_bulk" in c.calls and any("close 9 SELL MARKET" == x for x in c.calls)
