"""Exit-rule abstraction for per-trade, context-derived TP/SL.

The default exit path in this project is static: a strategy returns one
:class:`~src.core.types.ExitConfig` from ``get_exit_rules()`` and the simulator
applies it bar-by-bar via :func:`src.exit.rules.evaluate_exit`.

Some exits need to size TP/SL from information known only at entry (e.g. recent
zigzag leg sizes). An :class:`ExitRule` turns an :class:`ExitContext` (entry
state) into a concrete per-trade :class:`ExitConfig`. A strategy computes this at
signal time and attaches it to the :class:`~src.core.types.Signal` via
``exit_config``; the simulator then prefers that per-trade config over the
strategy's static default.

Ported/adapted from cld_trade_advisor ``src/exit/base.py`` (which was
stock/ADX specific and long-only); this version is product-agnostic and
supports both long and short.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from src.core.types import ExitConfig, Side


@dataclass(frozen=True, slots=True)
class ExitContext:
    """Entry-time state an :class:`ExitRule` uses to size TP/SL.

    Attributes:
        side: Trade direction.
        entry_price: Reference entry price (signal-bar close; the simulator fills
            at the next bar's open, but band *distances* are price-relative).
        zs_history: Recent zigzag leg sizes in price units, oldest-first — the
            adaptive-volatility input for ZS-based rules. May be empty.
        entry_atr: ATR at entry, for ATR-based rules. ``0.0`` if unused.
    """

    side: Side
    entry_price: float
    zs_history: tuple[float, ...] = field(default_factory=tuple)
    entry_atr: float = 0.0


class ExitRule(ABC):
    """Turns an :class:`ExitContext` into a per-trade :class:`ExitConfig`."""

    name: str = "exit_rule"

    @abstractmethod
    def exit_config(self, ctx: ExitContext) -> ExitConfig:
        """Return the concrete TP/SL/time-stop config for one trade.

        Args:
            ctx: Entry-time context.

        Returns:
            An :class:`ExitConfig` (typically using absolute ``tp_abs`` /
            ``sl_abs`` distances) that the simulator applies bar-by-bar.
        """
        raise NotImplementedError
