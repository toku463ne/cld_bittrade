"""ZS-based Take-Profit / Stop-Loss exit rule.

Uses an exponentially weighted average (EWA) of recent zigzag leg sizes ("ZS")
as an adaptive volatility estimate. Older legs are down-weighted by ``(1-alpha)``
per step, so recent volatility dominates::

    ewa = alpha·leg_N + (1-alpha)·alpha·leg_(N-1) + …

TP / SL are multiples of this band (price-distance terms, so they apply to either
side via :func:`src.exit.rules.evaluate_exit`)::

    TP distance = tp_mult · band      SL distance = sl_mult · band

If fewer than ``min_legs`` legs are available, falls back to a percentage band
(``fallback_pct`` of entry price).

Ported/adapted from cld_trade_advisor ``src/exit/zs_tp_sl.py``: here it produces
a per-trade :class:`~src.core.types.ExitConfig` instead of being polled per bar,
so it plugs into this project's existing exit evaluator unchanged.
"""

from __future__ import annotations

from src.core.types import ExitConfig
from src.exit.base import ExitContext, ExitRule


def ewa(legs: tuple[float, ...], alpha: float) -> float:
    """Exponentially weighted average of zigzag leg sizes (oldest-first).

    The newest leg carries weight ``alpha``, the one before ``alpha·(1-alpha)``,
    and so on.

    Args:
        legs: Leg sizes in price units, oldest-first. Must be non-empty.
        alpha: Smoothing factor in ``(0, 1]``; higher weights recent legs more.

    Returns:
        The EWA band in price units.
    """
    out = legs[0]
    for leg in legs[1:]:
        out = alpha * leg + (1.0 - alpha) * out
    return out


class ZsTpSl(ExitRule):
    """ZS-adaptive TP/SL with an EWA volatility band.

    Args:
        tp_mult: TP distance = ``tp_mult × band``.
        sl_mult: SL distance = ``sl_mult × band``.
        alpha: EWA smoothing factor (0 < alpha ≤ 1). ``0.3`` ≈ 2-leg half-life.
        min_legs: Minimum legs before the EWA is trusted; otherwise fall back.
        fallback_pct: Fallback band as a fraction of entry price.
        max_bars: Hard time-stop (bars).
    """

    def __init__(
        self,
        tp_mult: float = 1.5,
        sl_mult: float = 1.0,
        alpha: float = 0.3,
        min_legs: int = 3,
        fallback_pct: float = 0.01,
        max_bars: int = 40,
    ) -> None:
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha must be in (0, 1]")
        self.tp_mult = tp_mult
        self.sl_mult = sl_mult
        self.alpha = alpha
        self.min_legs = min_legs
        self.fallback_pct = fallback_pct
        self.max_bars = max_bars
        self.name = f"zs_tp{tp_mult}_sl{sl_mult}_a{alpha}"

    def band(self, ctx: ExitContext) -> float:
        """Return the volatility band (price units) for this entry."""
        legs = ctx.zs_history
        if len(legs) >= self.min_legs:
            return ewa(legs, self.alpha)
        return ctx.entry_price * self.fallback_pct

    def exit_config(self, ctx: ExitContext) -> ExitConfig:  # noqa: D102 (inherited)
        band = self.band(ctx)
        return ExitConfig(
            tp_abs=self.tp_mult * band,
            sl_abs=self.sl_mult * band,
            time_stop_bars=self.max_bars,
        )
