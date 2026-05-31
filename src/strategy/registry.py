"""Strategy registry (see CLAUDE.md § Strategy registry).

Maintains a dict of all available strategies by name. Used for:

- CLI selection (``--strategy ema_atr_breakout`` / ``--strategy all``)
- Populating the viz app's strategy dropdown
- The backtest runner iterating over all strategies
"""

from __future__ import annotations

from collections.abc import Callable

from src.strategy.base import Strategy
from src.strategy.ema_atr_breakout import EmaAtrBreakoutStrategy
from src.strategy.zigzag_bounce import ZigzagBounceStrategy, ZigzagBounceWallStrategy

# Factories (zero-arg) so each consumer gets a fresh, default-configured strategy.
STRATEGY_REGISTRY: dict[str, Callable[[], Strategy]] = {
    EmaAtrBreakoutStrategy.name: EmaAtrBreakoutStrategy,
    ZigzagBounceStrategy.name: ZigzagBounceStrategy,
    ZigzagBounceWallStrategy.name: ZigzagBounceWallStrategy,
}


def get_strategy(name: str) -> Strategy:
    """Instantiate a registered strategy by name.

    Args:
        name: Registered strategy name.

    Returns:
        A fresh strategy instance.

    Raises:
        KeyError: If ``name`` is not registered.
    """
    if name not in STRATEGY_REGISTRY:
        raise KeyError(
            f"Unknown strategy '{name}'. Known: {sorted(STRATEGY_REGISTRY)}"
        )
    return STRATEGY_REGISTRY[name]()


def all_strategies() -> list[str]:
    """Return the names of all registered strategies."""
    return sorted(STRATEGY_REGISTRY)
