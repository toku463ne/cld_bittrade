"""Sign registry — maps sign names to detector factories.

The benchmark pipeline iterates over this registry to run per-fire diagnostics.
"""

from __future__ import annotations

from collections.abc import Callable

from src.signs.base import Sign
from src.signs.ema_atr_breakout import EmaAtrBreakoutSign
from src.signs.ema_cross import EmaCrossSign
from src.signs.zigzag_bounce import ZigzagBounceSign

# Factories (zero-arg) so each consumer gets a fresh, default-configured detector.
# zigzag_bounce defaults to ambiguous-wall matching (the wall variant is now the
# default config, not a separate registered sign).
SIGN_REGISTRY: dict[str, Callable[[], Sign]] = {
    EmaCrossSign.name: EmaCrossSign,
    EmaAtrBreakoutSign.name: EmaAtrBreakoutSign,
    ZigzagBounceSign.name: ZigzagBounceSign,
}


def get_sign(name: str) -> Sign:
    """Instantiate a registered sign by name.

    Args:
        name: Registered sign name.

    Returns:
        A fresh detector instance.

    Raises:
        KeyError: If ``name`` is not registered.
    """
    if name not in SIGN_REGISTRY:
        raise KeyError(f"Unknown sign '{name}'. Known: {sorted(SIGN_REGISTRY)}")
    return SIGN_REGISTRY[name]()


def all_signs() -> list[str]:
    """Return the names of all registered signs."""
    return sorted(SIGN_REGISTRY)
