"""AUTO_BOOKS / EXEC_MAX_SLOTS parsing — must fail SOFT, never abort the run.

``_books()`` is called outside the per-book ``try`` in ``main()``, so anything it raises
kills the whole hourly run: no book gets reconciled, no ratchet, no orphan cleanup. The
trader's safety-critical job is maintaining exits on positions that are already open, so
a config typo must degrade one book, never all of them.
"""

from __future__ import annotations

from typing import Any

from datetime import datetime, timedelta, timezone

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


# --- stale-bars guard (2026-09 DNS outage: two weeks of replays on bars ending 09-06) ---


def test_bar_age_is_measured_from_the_bar_close_not_its_open() -> None:
    from src.execution.auto_trader import _bar_age

    bar = datetime(2026, 9, 26, 1, 0, tzinfo=timezone.utc)  # 01:00 bar closes 02:00
    age, stale = _bar_age(bar, datetime(2026, 9, 26, 2, 1, tzinfo=timezone.utc), 90)
    assert age == 1.0 and stale is False  # the normal HH:01 run


def test_one_late_bar_is_tolerated_but_two_missing_bars_halt() -> None:
    from src.execution.auto_trader import _bar_age

    bar = datetime(2026, 9, 26, 0, 0, tzinfo=timezone.utc)  # closes 01:00
    _, late = _bar_age(bar, datetime(2026, 9, 26, 2, 1, tzinfo=timezone.utc), 90)
    assert late is False, "GMO publishing the newest bar late must not halt the book"
    _, gone = _bar_age(bar, datetime(2026, 9, 26, 3, 1, tzinfo=timezone.utc), 90)
    assert gone is True


def test_the_september_outage_replay_is_stale() -> None:
    """The real incident: bars frozen at 09-06 20:00 while the run fired on 09-13."""
    from src.execution.auto_trader import _bar_age

    age, stale = _bar_age(datetime(2026, 9, 6, 20, 0, tzinfo=timezone.utc),
                          datetime(2026, 9, 13, 0, 27, tzinfo=timezone.utc), 90)
    assert stale is True and age is not None and age > 6 * 24 * 60


def test_missing_bar_time_counts_as_stale() -> None:
    from src.execution.auto_trader import _bar_age

    assert _bar_age(None, datetime(2026, 9, 26, tzinfo=timezone.utc), 90) == (None, True)


def test_max_bar_age_defaults_and_cannot_be_disabled_by_junk(monkeypatch: Any) -> None:
    from src.execution.auto_trader import MAX_BAR_AGE_MIN_DEFAULT, max_bar_age_min

    monkeypatch.delenv("MAX_BAR_AGE_MIN", raising=False)
    assert max_bar_age_min() == MAX_BAR_AGE_MIN_DEFAULT
    monkeypatch.setenv("MAX_BAR_AGE_MIN", "junk")
    assert max_bar_age_min() == MAX_BAR_AGE_MIN_DEFAULT
    monkeypatch.setenv("MAX_BAR_AGE_MIN", "0")
    assert max_bar_age_min() == 1


def _run_main_with_bars_ending(monkeypatch: Any, last_bar: datetime) -> tuple[list[Any], list[dict[str, Any]]]:
    """Run ``main()`` for one live-execute book with the replay stubbed to end at ``last_bar``."""
    import sys
    from types import SimpleNamespace

    from src.execution import auto_trader as at

    state = LiveBookState(positions=[], pending_entries=[], working_orders=[],
                          last_bar_time=last_bar, last_price=13_000_000.0, max_slots=1)
    reconciled: list[Any] = []
    rows: list[dict[str, Any]] = []
    monkeypatch.setattr(at, "get_settings", lambda: SimpleNamespace(
        allow_orders=True, use_live_api=True, log_level="INFO"))
    monkeypatch.setattr(at, "configure_logging", lambda _lvl: None)
    monkeypatch.setattr(at, "_books", lambda: [("density_pullback", "BTC_JPY", 1)])
    monkeypatch.setattr(at, "_desired", lambda *_a: (state, True))
    monkeypatch.setattr(at, "gmo_trading_client_from_settings", lambda: object())
    monkeypatch.setattr(at, "gmo_account_client_from_settings", lambda: object())
    monkeypatch.setattr(at, "reconcile", lambda *a, **k: reconciled.append(a))
    monkeypatch.setattr(at, "snapshot", rows.append)
    monkeypatch.setattr(sys, "argv", ["auto_trader", "--execute"])
    monkeypatch.delenv("MAX_BAR_AGE_MIN", raising=False)
    at.main()
    return reconciled, rows


def test_main_skips_reconcile_on_stale_bars_but_still_writes_the_heartbeat(monkeypatch: Any) -> None:
    reconciled, rows = _run_main_with_bars_ending(
        monkeypatch, datetime(2026, 9, 6, 20, 0, tzinfo=timezone.utc))
    assert reconciled == [], "a stale replay must never reach the exchange"
    assert len(rows) == 1 and rows[0]["stale"] is True and rows[0]["bar_age_min"] > 60


def test_main_reconciles_on_fresh_bars(monkeypatch: Any) -> None:
    fresh = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    reconciled, rows = _run_main_with_bars_ending(monkeypatch, fresh)
    assert len(reconciled) == 1
    assert rows[0]["stale"] is False
