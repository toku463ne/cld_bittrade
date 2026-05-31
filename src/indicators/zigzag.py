"""Zigzag peak/trough detector.

A bar is a *confirmed* high (``direction = 2``) if its high is the maximum of
``size`` bars on each side. A bar is an *early* high (``direction = 1``) if its
high is the maximum of ``size`` bars to the left and ``middle_size`` bars to the
right. Troughs use lows with ``direction = -2`` / ``-1`` respectively.

An early peak is what is knowable ``middle_size`` bars *after* it forms; a
confirmed peak is only knowable ``size`` bars after. The ``zigzag_bounce``
strategy keys off this distinction (see ``src/signs/zigzag_bounce.py``).

Ported from cld_trade_advisor ``src/indicators/zigzag.py``. This is distinct from
``src/backtest/zigzag.py`` (which measures per-fire outcomes).
"""

from __future__ import annotations

from dataclasses import dataclass

# direction constants
CONFIRMED_HIGH = 2
CONFIRMED_LOW = -2
EARLY_HIGH = 1
EARLY_LOW = -1


@dataclass(frozen=True, slots=True)
class Peak:
    """A detected zigzag peak or trough.

    Attributes:
        bar_index: Position in the input arrays.
        direction: ``2`` confirmed high, ``-2`` confirmed low, ``1`` early high,
            ``-1`` early low.
        price: ``high[bar_index]`` for highs, ``low[bar_index]`` for lows.
    """

    bar_index: int
    direction: int
    price: float

    @property
    def is_high(self) -> bool:
        """Whether this is a high/peak (vs a low/trough)."""
        return self.direction > 0

    @property
    def is_confirmed(self) -> bool:
        """Whether this peak is confirmed (``size`` bars on each side)."""
        return abs(self.direction) == 2


def detect_peaks(
    highs: list[float],
    lows: list[float],
    size: int = 10,
    middle_size: int = 3,
) -> list[Peak]:
    """Return zigzag peaks/troughs in chronological order.

    Args:
        highs: Per-bar high prices.
        lows: Per-bar low prices (same length as ``highs``).
        size: Bars that must be lower/higher on *each side* of the candidate for
            a *confirmed* peak (``±2``).
        middle_size: Bars after the candidate for an *early* peak (``±1``).

    Returns:
        Detected peaks in ascending ``bar_index`` order.

    Raises:
        ValueError: If ``highs`` and ``lows`` differ in length or
            ``middle_size >= size``.
    """
    if len(highs) != len(lows):
        raise ValueError("highs and lows must have equal length")
    if middle_size >= size:
        raise ValueError("middle_size must be < size")

    peak_idxs: list[int] = []
    dirs: list[int] = []

    def _prices_for(d: int) -> list[float]:
        return highs if d > 0 else lows

    def _update(new_dir: int, i: int) -> None:
        prices = _prices_for(new_dir)
        # Early peaks and direction reversals are always appended.
        if abs(new_dir) == 1 or not dirs or new_dir * dirs[-1] <= -4:
            peak_idxs.append(i)
            dirs.append(new_dir)
            return
        # Walk back through the same-sign run, replacing/merging weaker peaks.
        for j in range(1, len(dirs) + 1):
            if new_dir * dirs[-j] <= -4:
                break
            jidx = peak_idxs[-j]
            if abs(dirs[-j]) == 2:
                if new_dir > 0:
                    if prices[i] > prices[jidx]:
                        dirs[-j] = 1  # demote old confirmed high to early
                    else:
                        new_dir = 1
                        break
                else:
                    if prices[i] < prices[jidx]:
                        dirs[-j] = -1
                    else:
                        new_dir = -1
                        break
        peak_idxs.append(i)
        dirs.append(new_dir)

    n = len(highs)
    for i in range(n - size * 2, 0, -1):
        midi = i + size
        win_full = slice(i, i + size * 2)
        win_early = slice(i, i + size + middle_size + 1)
        if highs[midi] == max(highs[win_full]):
            _update(CONFIRMED_HIGH, midi)
        elif lows[midi] == min(lows[win_full]):
            _update(CONFIRMED_LOW, midi)
        elif highs[midi] == max(highs[win_early]):
            _update(EARLY_HIGH, midi)
        elif lows[midi] == min(lows[win_early]):
            _update(EARLY_LOW, midi)

    dirs.reverse()
    peak_idxs.reverse()

    out: list[Peak] = []
    for idx, d in zip(peak_idxs, dirs):
        price = highs[idx] if d > 0 else lows[idx]
        out.append(Peak(bar_index=idx, direction=d, price=price))
    return out


def confirmed_leg_sizes(peaks: list[Peak]) -> tuple[float, ...]:
    """Absolute price moves between consecutive confirmed peaks (oldest-first).

    Used as the adaptive-volatility input ("ZS") for the ZS TP/SL exit rule.

    Args:
        peaks: Output of :func:`detect_peaks`.

    Returns:
        ``|price[k] - price[k-1]|`` over consecutive confirmed peaks.
    """
    confirmed = [p for p in peaks if p.is_confirmed]
    return tuple(
        abs(confirmed[k].price - confirmed[k - 1].price)
        for k in range(1, len(confirmed))
    )
