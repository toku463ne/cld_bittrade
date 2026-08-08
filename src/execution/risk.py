"""Exposure and margin limits for the live book.

The 1-slot executor needed none of this: peak exposure was, by construction, one
minimum lot. A multi-slot book's peak exposure is ``max_slots x min lot x price``, so
the ceiling becomes a number someone has to choose — and this module is where it lives.

Two layers, deliberately separate:

- **Startup** — :func:`book_within_notional_cap` against ``MAX_BOOK_NOTIONAL_JPY``. A
  book whose *full* occupancy would breach the cap must refuse to execute at all rather
  than discover it mid-cycle with positions already on.
- **Per cycle** — :func:`entry_budget` against live margin. How many NEW entries the
  account can currently afford.

**The cardinal rule: these gate ENTRIES ONLY.** Exits, cancels, ratchets, orphan cleanup
and the kill switch are never blocked by margin state — a margin problem must never be
the reason a position is left unprotected. The executor enforces this by consulting the
budget only in the entry phase.
"""

from __future__ import annotations

import os
from typing import Any

from loguru import logger

from src.execution.gmo_client import LEVERAGE_MIN_SIZE

GMO_LEVERAGE = 2.0  # 個人 crypto leverage on GMO — required margin = notional / this
_HEADROOM = 1.5  # demand 50% more free margin than the notional strictly needs
_MIN_MARGIN_RATIO = 200.0  # percent; GMO's losscut territory is far below this


def peak_exposure_jpy(symbol: str, slots: int, price: float) -> float:
    """Notional at FULL occupancy — the number the slot cap actually guarantees.

    Args:
        symbol: GMO leverage symbol.
        slots: The book's concurrency cap.
        price: Reference price (the last closed-bar close is fine).

    Returns:
        ``slots x min lot x price`` in JPY, or ``0.0`` for an unknown symbol.
    """
    return slots * LEVERAGE_MIN_SIZE.get(symbol, 0.0) * price


def required_margin_jpy(notional: float) -> float:
    """Margin the venue reserves for ``notional`` of leverage exposure."""
    return notional / GMO_LEVERAGE


def book_within_notional_cap(symbol: str, slots: int, price: float) -> tuple[bool, str]:
    """Startup check: would this book at full occupancy breach ``MAX_BOOK_NOTIONAL_JPY``?

    Args:
        symbol: GMO leverage symbol.
        slots: The book's concurrency cap.
        price: Reference price for the notional estimate.

    Returns:
        ``(ok, message)``. ``ok`` is True when no cap is configured (the env var is the
        opt-in) or the peak fits under it.
    """
    raw = os.environ.get("MAX_BOOK_NOTIONAL_JPY", "").strip()
    peak = peak_exposure_jpy(symbol, slots, price)
    if not raw:
        return True, f"{symbol}: peak notional ~{peak:,.0f} JPY ({slots} slots), no cap set"
    try:
        cap = float(raw)
    except ValueError:
        return False, f"MAX_BOOK_NOTIONAL_JPY={raw!r} is not a number"
    if peak > cap:
        return False, (f"{symbol}: peak notional {peak:,.0f} JPY ({slots} slots) exceeds "
                       f"MAX_BOOK_NOTIONAL_JPY={cap:,.0f}")
    return True, f"{symbol}: peak notional ~{peak:,.0f} JPY ({slots} slots) <= cap {cap:,.0f}"


def entry_budget(
    symbol: str, slots_free: int, price: float | None, client: Any
) -> tuple[int, str]:
    """How many NEW entries the live margin permits this cycle.

    Never blocks exits — the executor calls this only when sizing entries.

    Fail directions are deliberate and opposite:

    - ``get_margin()`` **raises** -> budget 0 (a real API failure; do not add risk blind).
    - the client has **no** ``get_margin`` -> skip the check (read-only/legacy clients and
      test doubles keep working; the slot cap is still in force).
    - ``price`` is None -> skip; without a market reference no notional can be computed,
      and the startup notional cap already bounds the book.

    Args:
        symbol: GMO leverage symbol.
        slots_free: Entries the slot arithmetic already permits — the ceiling.
        price: Reference price, or None when unavailable.
        client: A GMO client (anything exposing ``get_margin()``).

    Returns:
        ``(n_allowed, reason)`` where ``0 <= n_allowed <= slots_free``.
    """
    if slots_free <= 0:
        return 0, "no free slot"
    get_margin = getattr(client, "get_margin", None)
    if get_margin is None:
        return slots_free, "no margin source (check skipped)"
    if price is None:
        return slots_free, "no price reference (check skipped)"

    try:
        margin = get_margin()
    except Exception as e:  # noqa: BLE001 - any failure here must fail CLOSED
        logger.warning("{}: get_margin() failed ({}) — allowing 0 new entries", symbol, e)
        return 0, f"margin read failed: {e}"

    try:
        available = float(margin.get("availableAmount", 0.0))
    except (TypeError, ValueError):
        logger.warning("{}: unparseable availableAmount {!r} — allowing 0 new entries",
                       symbol, margin.get("availableAmount"))
        return 0, "unparseable availableAmount"

    # marginRatio is absent while flat on some responses — only enforce it when present.
    raw_ratio = margin.get("marginRatio")
    if raw_ratio is not None:
        try:
            ratio = float(raw_ratio)
        except (TypeError, ValueError):
            ratio = float("inf")
        if ratio < _MIN_MARGIN_RATIO:
            logger.warning("{}: margin ratio {:.1f}% < {:.0f}% — no new entries",
                           symbol, ratio, _MIN_MARGIN_RATIO)
            return 0, f"margin ratio {ratio:.1f}% below {_MIN_MARGIN_RATIO:.0f}%"

    per_slot = required_margin_jpy(LEVERAGE_MIN_SIZE.get(symbol, 0.0) * price) * _HEADROOM
    if per_slot <= 0:
        return slots_free, "per-slot margin is zero (unknown symbol)"
    affordable = int(available // per_slot)
    allowed = max(0, min(slots_free, affordable))
    if allowed < slots_free:
        logger.warning("{}: margin allows {} of {} free slot(s) (available {:,.0f} JPY, "
                       "{:,.0f}/slot incl. {:.0%} headroom)",
                       symbol, allowed, slots_free, available, per_slot, _HEADROOM - 1)
    return allowed, f"margin allows {allowed}/{slots_free} (available {available:,.0f} JPY)"
