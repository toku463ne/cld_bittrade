"""Strategy base class.

Defines the interface every strategy implements (see CLAUDE.md § Strategy
Architecture):

- ``name`` / ``description`` — identity
- ``required_indicators`` — declared upfront for dependency injection
- ``on_bar(bar) -> Signal | None`` — core logic, called on every new bar
- ``get_exit_rules() -> ExitConfig`` — TP/SL/time-stop parameters

The base maintains a rolling bar buffer so concrete strategies can compute
indicators incrementally while keeping the simple ``on_bar(bar)`` signature.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING

import pandas as pd

from src.core.types import Bar, ExitConfig, ExitReason, Signal

if TYPE_CHECKING:
    from src.exit.rules import OpenPosition


class Strategy(ABC):
    """Abstract strategy with an internal bar buffer.

    Attributes:
        name: Unique identifier.
        description: Human-readable summary.
        required_indicators: Indicator keys the strategy depends on.
        warmup: Number of bars to accumulate before signals may fire.
        max_buffer: Cap on the rolling bar buffer. Keeps per-bar evaluation O(1)
            instead of O(N) (avoiding an O(N^2) backtest). Must be comfortably
            larger than the longest indicator lookback so values are fully
            converged; recursive indicators (EMA/Wilder ATR) forget their seed
            exponentially, so a few hundred bars is exact in practice.
    """

    name: str = "base"
    description: str = ""
    required_indicators: list[str] = []
    warmup: int = 30
    max_buffer: int = 400
    # Concurrent positions allowed. ``1`` (default) = the single-position
    # Simulator; ``>1`` routes the backtest to the MultiSimulator (overlapping
    # slots, mark-to-market equity Sharpe). Such strategies must implement
    # :meth:`precompute`.
    max_slots: int = 1

    def __init__(self) -> None:
        self._bars: list[Bar] = []

    def reset(self) -> None:
        """Clear the internal bar buffer (call between independent runs)."""
        self._bars = []

    @property
    def components(self) -> list["Strategy"]:
        """Sub-strategies whose signals this book is composed of.

        A plain strategy is its own only component. Composite books (e.g.
        :class:`~src.strategy.combo_dp_ver.ComboDpVerStrategy`) override this to
        expose their parts, so a viewer can attribute/colour signals per source.
        """
        return [self]

    def push(self, bar: Bar) -> Signal | None:
        """Append a bar to the buffer and evaluate the strategy.

        This is the entry point the simulator calls each bar. It delegates to
        :meth:`on_bar` once warmup is satisfied.

        Args:
            bar: The newly closed bar (bar T).

        Returns:
            A :class:`Signal` to enter at the next bar's open, or ``None``.
        """
        self._bars.append(bar)
        # Trim to a bounded rolling window so each evaluation is O(max_buffer),
        # not O(len(history)). The window is far larger than any indicator
        # lookback, so EMA/ATR values match the full-series computation.
        if len(self._bars) > self.max_buffer:
            self._bars = self._bars[-self.max_buffer :]
        if len(self._bars) < self.warmup:
            return None
        return self.on_bar(bar)

    def buffer_frame(self) -> pd.DataFrame:
        """Return the current bar buffer as a time-indexed OHLCV DataFrame."""
        return pd.DataFrame(
            {
                "open": [b.open for b in self._bars],
                "high": [b.high for b in self._bars],
                "low": [b.low for b in self._bars],
                "close": [b.close for b in self._bars],
                "volume": [b.volume for b in self._bars],
            },
            index=pd.DatetimeIndex([b.timestamp for b in self._bars], name="timestamp"),
        )

    def precompute(self, bars: list[Bar]) -> dict[datetime, Signal] | None:
        """Optionally precompute entry signals for the whole series (fast path).

        Vectorisable strategies should detect over the full bar series once and
        return a ``{bar_timestamp: Signal}`` map; the simulator then looks up
        signals per bar in O(1) instead of re-evaluating a growing buffer
        (avoiding an O(N^2) backtest). Computing over the full series here also
        keeps the simulator's entries identical to the per-fire benchmark.

        Returns:
            A signal-by-timestamp map, or ``None`` to use the per-bar
            :meth:`on_bar` path.
        """
        return None

    def precompute_multi(self, bars: list[Bar]) -> dict[datetime, list[Signal]] | None:
        """Optionally precompute *several* entry signals per bar (MultiSimulator).

        Like :meth:`precompute`, but each timestamp maps to a *list* of signals so
        a strategy can open more than one position from a single bar (e.g. a hedged
        long+short pair). The MultiSimulator fills them in order while slots remain
        free. ``None`` (default) falls back to :meth:`precompute` (one per bar).

        Returns:
            A ``{bar_timestamp: [Signal, ...]}`` map, or ``None``.
        """
        return None

    @abstractmethod
    def on_bar(self, bar: Bar) -> Signal | None:
        """Core strategy logic for the just-closed bar.

        Args:
            bar: The newly closed bar (bar T). The full buffer is available via
                :meth:`buffer_frame`.

        Returns:
            A :class:`Signal` or ``None``.
        """
        raise NotImplementedError

    @abstractmethod
    def get_exit_rules(self) -> ExitConfig:
        """Return the strategy's TP/SL/time-stop configuration."""
        raise NotImplementedError

    def dynamic_exit(
        self, pos: OpenPosition, bar: Bar, i: int, entry_idx: int
    ) -> tuple[ExitReason, float] | None:
        """Optional per-bar exit beyond the static :class:`ExitConfig`.

        Called by the MultiSimulator for each open position on each bar *after*
        the static exits (stop / target / time) have been checked. Multi-position
        strategies override this for state-dependent exits (e.g. the dense
        "stall" exit). Single-position strategies never reach it.

        Args:
            pos: The open position (carries entry price, side, ``ref``/``ref2``).
            bar: The current bar.
            i: Index of ``bar`` in the run's bar list.
            entry_idx: Index at which the position was filled.

        Returns:
            ``(reason, exit_price)`` to close the position, or ``None`` to hold.
        """
        return None
