"""AUTO_BOOKS / EXEC_MAX_SLOTS parsing — must fail SOFT, never abort the run.

``_books()`` is called outside the per-book ``try`` in ``main()``, so anything it raises
kills the whole hourly run: no book gets reconciled, no ratchet, no orphan cleanup. The
trader's safety-critical job is maintaining exits on positions that are already open, so
a config typo must degrade one book, never all of them.
"""

from __future__ import annotations

from typing import Any

from datetime import datetime, timezone

from src.core.types import Side
from src.execution.auto_trader import (
    DEFAULT_BOOKS,
    _books,
    _heartbeat_fields,
    exec_max_slots,
)
from src.simulator.multi_simulator import DesiredPosition, LiveBookState


def test_heartbeat_separates_the_desired_book_from_the_unread_live_one() -> None:
    """``n_open`` is INTENT; the live counts stay None until the exchange is read.

    Reading ``n_open`` as the live position count is exactly what hid the 2026-08-08
    mis-pairing for a day — the strategy held 1 position the account did not.
    ``None`` (never read) must stay distinguishable from ``0`` (read, found nothing).
    """
    t = datetime(2026, 8, 8, 15, 0, tzinfo=timezone.utc)
    pos = DesiredPosition(side=Side.LONG, entry_time=t, entry_price=10_271_097.86,
                          current_stop=10_142_003.21, target=None, bars_held=5,
                          time_stop_bars=None)
    state = LiveBookState(positions=[pos], pending_entries=[], working_orders=[],
                          last_bar_time=t, last_price=10_268_114.0, max_slots=2)

    f = _heartbeat_fields("density_pullback", "BTC_JPY", 2, state, True)

    assert f["n_open"] == 1  # desired
    for key in ("n_live_open", "n_matched", "n_unadopted", "n_live_only", "anomaly"):
        assert f[key] is None, f"{key} must be None until the exchange is actually read"
    assert f["halted"] is False


def test_phantom_warning_tells_the_truth_in_each_of_the_three_states() -> None:
    """A log line that misreports the book's state is what hid the 2026-08-08 incident."""
    from src.execution.auto_trader import _phantom_warning

    def row(**kw: Any) -> dict[str, Any]:
        return {"max_slots": 2, "n_unadopted": 0, "phantoms_ignored": False, **kw}

    assert _phantom_warning(row()) is None  # healthy: say nothing

    partial = _phantom_warning(row(n_unadopted=1))
    assert partial is not None and "1 of 2 slot(s)" in partial
    assert "NOTHING" not in partial, "one free slot left — the book still trades"

    frozen = _phantom_warning(row(n_unadopted=2))
    assert frozen is not None and "can open NOTHING" in frozen, (
        "every slot phantom is a freeze, not merely a smaller book"
    )

    released = _phantom_warning(row(n_unadopted=2, phantoms_ignored=True))
    assert released is not None and "RELEASED" in released
    assert "NOTHING" not in released, "the slots were released — do not still call it blocked"
    assert "capped at 2 slot(s)" in released, "must reassure that exposure is still bounded"


def test_every_live_side_key_reconcile_writes_is_declared_in_the_heartbeat() -> None:
    """``main()`` merges reconcile's ``sync`` over the heartbeat fields.

    The merge is a blind ``dict.update``, so a key written on only one side would
    either add an undeclared column or leave a declared one stuck at None forever —
    silently, in the one file used for offline analysis. Pin them together.
    """
    from src.execution.live_executor import reconcile

    class _Client:
        def __init__(self, positions: list[dict[str, Any]]) -> None:
            self._positions = positions

        def get_open_positions(self, symbol: str) -> list[dict[str, Any]]:
            return self._positions

        def get_active_orders(self, symbol: str) -> list[dict[str, Any]]:
            return []

    t = datetime(2026, 8, 8, 15, 0, tzinfo=timezone.utc)
    state = LiveBookState(positions=[], pending_entries=[], working_orders=[],
                          last_bar_time=t, last_price=170.0, max_slots=1)
    declared = set(_heartbeat_fields("s", "XRP_JPY", 1, state, True))

    written: set[str] = set()
    for positions in ([],                                        # healthy, flat
                      [{"positionId": i, "side": "BUY", "size": "10", "price": "170",
                        "timestamp": t.isoformat()} for i in (1, 2)]):  # anomaly halt
        sync: dict[str, Any] = {}
        reconcile("XRP_JPY", state, _Client(positions), execute=False, sync=sync)
        written |= set(sync)

    assert written, "reconcile reported nothing — the probe itself is broken"
    assert written <= declared, f"undeclared heartbeat key(s): {sorted(written - declared)}"


def test_unset_falls_back_to_the_default_books(monkeypatch: Any) -> None:
    monkeypatch.delenv("AUTO_BOOKS", raising=False)
    assert _books() == DEFAULT_BOOKS


def test_explicit_slots_are_parsed(monkeypatch: Any) -> None:
    monkeypatch.setenv("AUTO_BOOKS", "density_pullback:BTC_JPY:6,density_pullback_xrp:XRP_JPY:2")
    assert _books() == [("density_pullback", "BTC_JPY", 6),
                        ("density_pullback_xrp", "XRP_JPY", 2)]


def test_omitted_slots_stay_none_at_single_slot(monkeypatch: Any) -> None:
    # EXEC_MAX_SLOTS=1 is the historical config; None means "use the strategy default",
    # which the executor then gates anyway. Unchanged behaviour.
    monkeypatch.setenv("EXEC_MAX_SLOTS", "1")
    monkeypatch.setenv("AUTO_BOOKS", "density_pullback:BTC_JPY")
    assert _books() == [("density_pullback", "BTC_JPY", None)]


def test_omitted_slots_clamp_to_one_instead_of_killing_the_run(monkeypatch: Any) -> None:
    # The live misconfiguration of 2026-08-08: EXEC_MAX_SLOTS=12 with no :slots. This
    # used to raise, and because _books() runs outside the per-book try it took the whole
    # run down — every hour, silently, while a BTC position was open.
    monkeypatch.setenv("EXEC_MAX_SLOTS", "12")
    monkeypatch.setenv("AUTO_BOOKS", "density_pullback:BTC_JPY,density_pullback_xrp:XRP_JPY")
    assert _books() == [("density_pullback", "BTC_JPY", 1),
                        ("density_pullback_xrp", "XRP_JPY", 1)]


def test_one_malformed_entry_does_not_drop_the_healthy_ones(monkeypatch: Any) -> None:
    monkeypatch.setenv("EXEC_MAX_SLOTS", "1")
    monkeypatch.setenv("AUTO_BOOKS", "garbage,density_pullback:BTC_JPY:2,:XRP_JPY:1")
    assert _books() == [("density_pullback", "BTC_JPY", 2)]


def test_non_numeric_and_zero_slot_counts_are_skipped(monkeypatch: Any) -> None:
    monkeypatch.setenv("EXEC_MAX_SLOTS", "6")
    monkeypatch.setenv("AUTO_BOOKS", "a:BTC_JPY:six,b:ETH_JPY:0,c:XRP_JPY:3")
    assert _books() == [("c", "XRP_JPY", 3)]


def test_all_entries_unusable_returns_empty_without_raising(monkeypatch: Any) -> None:
    # Nothing is managed, which is bad — but it is logged CRITICAL per entry and the
    # process still exits cleanly, so the other books (and the next run) are unaffected.
    monkeypatch.setenv("AUTO_BOOKS", "garbage,alsogarbage")
    assert _books() == []


def test_exec_max_slots_defaults_to_one_and_survives_junk(monkeypatch: Any) -> None:
    monkeypatch.delenv("EXEC_MAX_SLOTS", raising=False)
    assert exec_max_slots() == 1
    monkeypatch.setenv("EXEC_MAX_SLOTS", "not-a-number")
    assert exec_max_slots() == 1
    monkeypatch.setenv("EXEC_MAX_SLOTS", "0")
    assert exec_max_slots() == 1  # never below one
