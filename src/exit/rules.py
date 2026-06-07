"""Exit-rule evaluation against a single bar.

Exit levels are derived from the entry price and the ATR at entry (for
``*_atr_mult`` rules) or from fractional moves (for ``*_pct`` rules). The
trailing stop tracks the most favourable price seen since entry.

Intra-bar ordering convention: **stop-loss / trailing stop are checked before
take-profit** (pessimistic), since within a single bar we cannot know which
level traded first. This keeps backtest results conservative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.core.types import Bar, ExitConfig, ExitReason, Side


@dataclass(slots=True)
class OpenPosition:
    """Mutable state of a position open in the simulator.

    Attributes:
        side: Long or short.
        entry_price: Fill price (open of bar T+1).
        entry_atr: ATR at the signal bar, used to size ATR-based exits.
        bars_held: Bars elapsed since entry (incremented by the simulator).
        favorable_extreme: Highest high (long) / lowest low (short) since entry,
            used for the trailing stop.
        tp_price: Fixed take-profit price level (set by the simulator at entry).
        sl_price: Fixed stop-loss price level (set by the simulator at entry).
    """

    side: Side
    entry_price: float
    entry_atr: float
    bars_held: int = 0
    favorable_extreme: float = field(default=0.0)
    tp_price: float | None = None
    sl_price: float | None = None
    ref_time: datetime | None = None
    ref_price: float | None = None
    ref2_time: datetime | None = None
    ref2_price: float | None = None

    def __post_init__(self) -> None:
        if self.favorable_extreme == 0.0:
            self.favorable_extreme = self.entry_price


def _tp_sl_distances(pos: OpenPosition, cfg: ExitConfig) -> tuple[float | None, float | None]:
    """Return absolute (tp_distance, sl_distance) in price units, or None each.

    Distance precedence: ``abs`` > ``atr_mult`` (when ATR is known) > ``pct``.
    """
    tp = sl = None
    if cfg.tp_abs is not None:
        tp = cfg.tp_abs
    elif cfg.tp_atr_mult is not None and pos.entry_atr > 0.0:
        tp = cfg.tp_atr_mult * pos.entry_atr
    elif cfg.tp_pct is not None:
        tp = cfg.tp_pct * pos.entry_price
    if cfg.sl_abs is not None:
        sl = cfg.sl_abs
    elif cfg.sl_atr_mult is not None and pos.entry_atr > 0.0:
        sl = cfg.sl_atr_mult * pos.entry_atr
    elif cfg.sl_pct is not None:
        sl = cfg.sl_pct * pos.entry_price
    return tp, sl


def tp_sl_levels(pos: OpenPosition, cfg: ExitConfig) -> tuple[float | None, float | None]:
    """Return the fixed (take_profit_price, stop_loss_price) for a position.

    Side-adjusted absolute price levels derived from the same TP/SL distances
    :func:`evaluate_exit` uses. Either may be ``None`` if not configured. The
    trailing stop is dynamic and not returned here.

    Args:
        pos: The open position (entry price, side, ATR).
        cfg: The trade's exit configuration.

    Returns:
        ``(tp_price, sl_price)``.
    """
    tp_dist, sl_dist = _tp_sl_distances(pos, cfg)
    long = pos.side is Side.LONG
    tp = None if tp_dist is None else (pos.entry_price + tp_dist if long else pos.entry_price - tp_dist)
    sl = None if sl_dist is None else (pos.entry_price - sl_dist if long else pos.entry_price + sl_dist)
    return tp, sl


def evaluate_exit(
    pos: OpenPosition, bar: Bar, cfg: ExitConfig
) -> tuple[ExitReason, float] | None:
    """Evaluate whether ``pos`` exits on ``bar``.

    Updates ``pos.favorable_extreme`` as a side effect. Does NOT increment
    ``bars_held`` (the simulator owns that).

    Args:
        pos: The open position.
        bar: The bar being evaluated (a bar strictly after entry).
        cfg: The strategy's exit configuration.

    Returns:
        ``(reason, exit_price)`` if an exit triggers on this bar, else ``None``.
    """
    long = pos.side is Side.LONG
    tp_dist, sl_dist = _tp_sl_distances(pos, cfg)

    # Update trailing extreme.
    if long:
        pos.favorable_extreme = max(pos.favorable_extreme, bar.high)
    else:
        pos.favorable_extreme = min(pos.favorable_extreme, bar.low)

    # 1. Stop loss (pessimistic: checked first).
    if sl_dist is not None:
        sl_level = pos.entry_price - sl_dist if long else pos.entry_price + sl_dist
        if (long and bar.low <= sl_level) or (not long and bar.high >= sl_level):
            return ExitReason.STOP_LOSS, sl_level

    # 2. Trailing stop.
    if cfg.trail_atr_mult is not None and pos.entry_atr > 0.0:
        trail_dist = cfg.trail_atr_mult * pos.entry_atr
        trail_level = (
            pos.favorable_extreme - trail_dist
            if long
            else pos.favorable_extreme + trail_dist
        )
        if (long and bar.low <= trail_level) or (not long and bar.high >= trail_level):
            return ExitReason.TRAIL_STOP, trail_level

    # 3. Take profit.
    if tp_dist is not None:
        tp_level = pos.entry_price + tp_dist if long else pos.entry_price - tp_dist
        if (long and bar.high >= tp_level) or (not long and bar.low <= tp_level):
            return ExitReason.TAKE_PROFIT, tp_level

    # 4. Time stop (exit at close once held long enough).
    if cfg.time_stop_bars is not None and pos.bars_held >= cfg.time_stop_bars:
        return ExitReason.TIME_STOP, bar.close

    return None
