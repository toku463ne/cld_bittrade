"""Core domain types shared by strategies, signs, the simulator and exits.

These are deliberately framework-agnostic dataclasses (no DB / no pandas) so
that strategy and exit logic can be unit-tested in isolation through the mock
layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Side(str, Enum):
    """Trade direction."""

    LONG = "long"
    SHORT = "short"

    @property
    def sign(self) -> int:
        """Return +1 for long, -1 for short."""
        return 1 if self is Side.LONG else -1


class Timeframe(str, Enum):
    """Supported OHLCV timeframes and their per-period reporting unit.

    The reporting unit is the natural per-period breakdown unit defined in
    CLAUDE.md (1m -> 1 hour, 5m -> 1 day, 15m -> 1 day, 1h -> 1 week).
    """

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"

    @property
    def seconds(self) -> int:
        """Number of seconds in one bar of this timeframe."""
        return {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}[self.value]

    @property
    def period_unit(self) -> str:
        """The per-period breakdown unit for reporting (see CLAUDE.md)."""
        return {"1m": "hour", "5m": "day", "15m": "day", "1h": "week"}[self.value]


@dataclass(frozen=True, slots=True)
class Bar:
    """A single OHLCV bar for ``FX_BTC_JPY``.

    Attributes:
        timestamp: Bar open time (UTC).
        open: Open price.
        high: High price.
        low: Low price.
        close: Close price.
        volume: Traded volume in the bar.
    """

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class Signal:
    """A directional entry signal produced by a strategy on bar T.

    Per the two-bar fill rule, a signal fires at the *close* of bar T and is
    filled at the *open* of bar T+1.

    Attributes:
        side: Long or short.
        timestamp: Timestamp of the signal bar (bar T).
        price: Reference price (close of bar T).
        score: Detector confidence in ``[0, 1]``.
        reason: Human-readable explanation (which gates fired).
        meta: Optional extra fields (e.g. atr at fire) for diagnostics.
    """

    side: Side
    timestamp: datetime
    price: float
    score: float = 1.0
    reason: str = ""
    meta: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExitConfig:
    """Exit-rule parameters returned by ``Strategy.get_exit_rules()``.

    Any subset may be active. ``*_atr_mult`` values are multiples of the ATR at
    entry; ``*_pct`` values are fractional moves from entry price. ``time_stop``
    is measured in bars.

    Attributes:
        tp_atr_mult: Take-profit distance as a multiple of entry ATR.
        sl_atr_mult: Stop-loss distance as a multiple of entry ATR.
        tp_pct: Take-profit distance as a fraction of entry price.
        sl_pct: Stop-loss distance as a fraction of entry price.
        trail_atr_mult: ATR-trailing-stop distance as a multiple of entry ATR.
        time_stop_bars: Force-exit after this many bars held.
    """

    tp_atr_mult: float | None = None
    sl_atr_mult: float | None = None
    tp_pct: float | None = None
    sl_pct: float | None = None
    trail_atr_mult: float | None = None
    time_stop_bars: int | None = None


class ExitReason(str, Enum):
    """Why a position was closed."""

    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    TRAIL_STOP = "trail_stop"
    TIME_STOP = "time_stop"
    END_OF_DATA = "end_of_data"


@dataclass(frozen=True, slots=True)
class Trade:
    """A completed round-trip trade produced by the simulator.

    Attributes:
        side: Long or short.
        entry_time: Fill time of the entry (open of bar T+1).
        entry_price: Fill price.
        exit_time: Fill time of the exit.
        exit_price: Exit fill price.
        exit_reason: Why the position closed.
        size: Position size in BTC.
        bars_held: Number of bars the position was open.
        signal_score: Score of the originating signal.
    """

    side: Side
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    exit_reason: ExitReason
    size: float
    bars_held: int
    signal_score: float

    @property
    def pnl(self) -> float:
        """Absolute PnL in JPY (price terms × size)."""
        return self.side.sign * (self.exit_price - self.entry_price) * self.size

    @property
    def return_pct(self) -> float:
        """Signed fractional return of the trade (long-equivalent)."""
        return self.side.sign * (self.exit_price - self.entry_price) / self.entry_price
