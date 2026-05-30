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

import pandas as pd

from src.core.types import Bar, ExitConfig, Signal


class Strategy(ABC):
    """Abstract strategy with an internal bar buffer.

    Attributes:
        name: Unique identifier.
        description: Human-readable summary.
        required_indicators: Indicator keys the strategy depends on.
        warmup: Number of bars to accumulate before signals may fire.
    """

    name: str = "base"
    description: str = ""
    required_indicators: list[str] = []
    warmup: int = 30

    def __init__(self) -> None:
        self._bars: list[Bar] = []

    def reset(self) -> None:
        """Clear the internal bar buffer (call between independent runs)."""
        self._bars = []

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
