"""AUTO_BOOKS / EXEC_MAX_SLOTS parsing — must fail SOFT, never abort the run.

``_books()`` is called outside the per-book ``try`` in ``main()``, so anything it raises
kills the whole hourly run: no book gets reconciled, no ratchet, no orphan cleanup. The
trader's safety-critical job is maintaining exits on positions that are already open, so
a config typo must degrade one book, never all of them.
"""

from __future__ import annotations

from typing import Any

from src.execution.auto_trader import DEFAULT_BOOKS, _books, exec_max_slots


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
