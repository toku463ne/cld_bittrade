"""Strategy registry (see CLAUDE.md § Strategy registry).

Maintains a dict of all available strategies by name. Used for:

- CLI selection (``--strategy ema_atr_breakout`` / ``--strategy all``)
- Populating the viz app's strategy dropdown
- The backtest runner iterating over all strategies
"""

from __future__ import annotations

from collections.abc import Callable

from src.strategy.base import Strategy
from src.strategy.density_band import DensityBandStrategy
from src.strategy.density_breakout import DensityBreakoutStrategy
from src.strategy.density_breakout_acc import DensityBreakoutAccStrategy
from src.strategy.density_breakout_clearair import DensityBreakoutClearairStrategy
from src.strategy.density_breakout_vol import DensityBreakoutVolStrategy
from src.strategy.density_multi_breakout import DensityMultiBreakoutStrategy
from src.strategy.density_multi_relative import DensityMultiRelativeStrategy
from src.strategy.density_volwall_breakout import DensityVolwallBreakoutStrategy
from src.strategy.ema_atr_breakout import EmaAtrBreakoutStrategy
from src.strategy.zigzag_bounce import ZigzagBounceStrategy

# Factories (zero-arg) so each consumer gets a fresh, default-configured strategy.
# zigzag_bounce defaults to ambiguous-wall matching (was the zigzag_bounce_wall
# variant, now folded into the default).
STRATEGY_REGISTRY: dict[str, Callable[[], Strategy]] = {
    EmaAtrBreakoutStrategy.name: EmaAtrBreakoutStrategy,
    ZigzagBounceStrategy.name: ZigzagBounceStrategy,
    DensityBandStrategy.name: DensityBandStrategy,
    DensityBreakoutStrategy.name: DensityBreakoutStrategy,
    DensityBreakoutAccStrategy.name: DensityBreakoutAccStrategy,
    DensityBreakoutClearairStrategy.name: DensityBreakoutClearairStrategy,
    DensityBreakoutVolStrategy.name: DensityBreakoutVolStrategy,
    DensityMultiBreakoutStrategy.name: DensityMultiBreakoutStrategy,
    DensityMultiRelativeStrategy.name: DensityMultiRelativeStrategy,
    DensityVolwallBreakoutStrategy.name: DensityVolwallBreakoutStrategy,
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
