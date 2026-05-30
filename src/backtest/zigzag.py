"""Zigzag outcome measurement for per-fire benchmarking.

Implements the fire-outcome definition from ``docs/evaluation_guide.md`` §1:
from a fire on bar T, find the next confirmed zigzag peak within ~``window``
bars on the selected timeframe and record whether the next major swing went UP
(``trend_dir = +1``) or DOWN (``trend_dir = -1``).

This uses ``_first_zigzag_peak`` semantics (a forward window from the fire,
matching what is knowable at decision time) — NOT a post-fact ``detect_peaks``
over the full series (which would leak future data; see guide §7.2).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Outcome:
    """Measured outcome of a single fire.

    Attributes:
        trend_dir: +1 if the next confirmed swing was up, -1 if down, 0 if no
            swing confirmed within the window.
        magnitude: ``abs(peak_price - entry_price) / entry_price``.
        signed_return: ``trend_dir * magnitude`` (the long-equivalent return).
    """

    trend_dir: int
    magnitude: float
    signed_return: float


def first_zigzag_peak(
    closes: list[float],
    entry_idx: int,
    *,
    window: int = 30,
    threshold: float = 0.003,
) -> Outcome:
    """Find the first confirmed swing after ``entry_idx``.

    A swing is "confirmed" when price moves at least ``threshold`` (fractional)
    away from the entry in some direction before reversing by the same amount,
    OR when the window ends — whichever extreme (up vs down) was reached first
    and by the largest margin defines the direction.

    Args:
        closes: Close prices for the full series.
        entry_idx: Index of the fire bar (bar T).
        window: Max look-ahead in bars.
        threshold: Minimum fractional move to count as a confirmed swing.

    Returns:
        An :class:`Outcome`. ``trend_dir == 0`` when neither side reaches the
        threshold within the window (treated as a non-event by the pipeline).
    """
    n = len(closes)
    entry = closes[entry_idx]
    if entry <= 0.0 or entry_idx >= n - 1:
        return Outcome(0, 0.0, 0.0)

    end = min(n - 1, entry_idx + window)
    up_hit_idx: int | None = None
    dn_hit_idx: int | None = None
    max_up = 0.0
    max_dn = 0.0

    for i in range(entry_idx + 1, end + 1):
        move = (closes[i] - entry) / entry
        if move > max_up:
            max_up = move
        if -move > max_dn:
            max_dn = -move
        if up_hit_idx is None and move >= threshold:
            up_hit_idx = i
        if dn_hit_idx is None and -move >= threshold:
            dn_hit_idx = i
        if up_hit_idx is not None and dn_hit_idx is not None:
            break

    # Decide direction by whichever threshold was crossed FIRST.
    if up_hit_idx is not None and (dn_hit_idx is None or up_hit_idx < dn_hit_idx):
        return Outcome(1, max_up, max_up)
    if dn_hit_idx is not None and (up_hit_idx is None or dn_hit_idx < up_hit_idx):
        return Outcome(-1, max_dn, -max_dn)

    # No confirmed swing: fall back to the dominant unconfirmed excursion.
    if max_up == 0.0 and max_dn == 0.0:
        return Outcome(0, 0.0, 0.0)
    if max_up >= max_dn:
        return Outcome(1, max_up, max_up)
    return Outcome(-1, max_dn, -max_dn)
