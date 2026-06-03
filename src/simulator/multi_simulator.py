"""Multi-position bar simulator (overlapping slots, two-bar fill rule).

A generalisation of :class:`~src.simulator.simulator.Simulator` for strategies
that hold several positions at once (``strategy.max_slots > 1``). On each bar:

1. Evaluate exits for every open position — the static :class:`ExitConfig`
   (stop / target / time, via :func:`~src.exit.rules.evaluate_exit`) first, then
   the strategy's :meth:`~src.strategy.base.Strategy.dynamic_exit` hook.
2. Fill a pending signal at this bar's open if a slot is free (two-bar rule).
3. Read the strategy's precomputed signal for this bar -> pending for next bar.

It records a **mark-to-market** equity curve (realised + unrealised across the
open book), which is the basis for the time-based equity Sharpe — the correct
metric for overlapping positions (per-trade Sharpe understates the
diversification benefit). Entries come from :meth:`Strategy.precompute` (required
here), so the book's entries match the per-fire benchmark.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from loguru import logger

from src.core.types import Bar, ExitConfig, ExitReason, Trade
from src.exit.rules import OpenPosition, evaluate_exit, tp_sl_levels
from src.simulator.simulator import DEFAULT_FEE_RATE, SimResult
from src.strategy.base import Strategy


@dataclass(slots=True)
class _Slot:
    """One open position plus the bookkeeping the simulator owns."""

    pos: OpenPosition
    entry_idx: int
    entry_time: datetime
    cfg: ExitConfig


class MultiSimulator:
    """Bar simulator holding up to ``strategy.max_slots`` concurrent positions.

    Args:
        strategy: The strategy to drive (must implement ``precompute``).
        size: Per-slot position size in BTC (minimum lot by default).
        atr_period: ATR period for entry sizing (parity with the single sim).
        fee_rate: Per-side taker cost; round-trip = ``entry × size × rate × 2``.
    """

    def __init__(
        self,
        strategy: Strategy,
        *,
        size: float = 0.001,
        atr_period: int = 14,
        fee_rate: float = DEFAULT_FEE_RATE,
    ) -> None:
        self.strategy = strategy
        self.size = size
        self.atr_period = atr_period
        self.fee_rate = fee_rate

    def run(self, bars: list[Bar]) -> SimResult:
        """Run the multi-position simulation over ``bars``."""
        self.strategy.reset()
        fallback_cfg = self.strategy.get_exit_rules()
        max_slots = max(1, self.strategy.max_slots)
        atr_vals = self._atr_series(bars)

        precomputed = self.strategy.precompute(bars)
        if precomputed is None:
            raise ValueError(
                f"MultiSimulator requires a precompute() strategy; '{self.strategy.name}' "
                "returned None."
            )

        trades: list[Trade] = []
        equity_curve: list[float] = []
        realised = 0.0
        book: list[_Slot] = []
        pending = None
        pending_atr = 0.0

        for i, bar in enumerate(bars):
            # 1. Exits on the current bar (static config, then the dynamic hook).
            survivors: list[_Slot] = []
            for slot in book:
                result = evaluate_exit(slot.pos, bar, slot.cfg)
                if result is None:
                    result = self.strategy.dynamic_exit(slot.pos, bar, i, slot.entry_idx)
                if result is None:
                    slot.pos.bars_held += 1
                    survivors.append(slot)
                else:
                    reason, exit_price = result
                    trade = self._close(slot, bar, exit_price, reason, i - slot.entry_idx)
                    trades.append(trade)
                    realised += trade.pnl
            book = survivors

            # 2. Fill a pending signal at this bar's open if a slot is free.
            if pending is not None and len(book) < max_slots:
                pos = OpenPosition(
                    side=pending.side, entry_price=bar.open, entry_atr=pending_atr
                )
                cfg = pending.exit_config or fallback_cfg
                pos.tp_price, pos.sl_price = tp_sl_levels(pos, cfg)
                pos.ref_time, pos.ref_price = pending.ref_time, pending.ref_price
                pos.ref2_time, pos.ref2_price = pending.ref2_time, pending.ref2_price
                book.append(_Slot(pos, i, bar.timestamp, cfg))
            pending = None

            # 3. Read the precomputed signal for this just-closed bar.
            signal = precomputed.get(bar.timestamp)
            if signal is not None:
                pending = signal
                pending_atr = atr_vals[i]

            # Mark-to-market: realised + unrealised across the open book.
            unreal = sum(
                s.pos.side.sign * (bar.close - s.pos.entry_price) * self.size for s in book
            )
            equity_curve.append(realised + unreal)

        # Close anything still open at end of data.
        if book and bars:
            last = bars[-1]
            for slot in book:
                trade = self._close(
                    slot, last, last.close, ExitReason.END_OF_DATA, len(bars) - 1 - slot.entry_idx
                )
                trades.append(trade)
                realised += trade.pnl
            if equity_curve:
                equity_curve[-1] = realised

        logger.info(
            "MultiSimulated {} bars for '{}': {} trades ({} slots), net PnL {:.1f}",
            len(bars),
            self.strategy.name,
            len(trades),
            max_slots,
            realised,
        )
        return SimResult(
            trades=trades,
            strategy_name=self.strategy.name,
            n_bars=len(bars),
            equity_curve=equity_curve,
        )

    def _atr_series(self, bars: list[Bar]) -> list[float]:
        if not bars:
            return []
        import pandas as pd

        from src.indicators import atr

        df = pd.DataFrame(
            {"high": [b.high for b in bars], "low": [b.low for b in bars], "close": [b.close for b in bars]}
        )
        return [float(v) for v in atr(df, self.atr_period).to_numpy()]

    def _close(
        self, slot: _Slot, bar: Bar, exit_price: float, reason: ExitReason, bars_held: int
    ) -> Trade:
        pos = slot.pos
        cost = pos.entry_price * self.size * self.fee_rate * 2.0
        return Trade(
            side=pos.side,
            entry_time=slot.entry_time,
            entry_price=pos.entry_price,
            exit_time=bar.timestamp,
            exit_price=exit_price,
            exit_reason=reason,
            size=self.size,
            bars_held=max(1, bars_held),
            signal_score=1.0,
            cost=cost,
            tp_price=pos.tp_price,
            sl_price=pos.sl_price,
            ref_time=pos.ref_time,
            ref_price=pos.ref_price,
            ref2_time=pos.ref2_time,
            ref2_price=pos.ref2_price,
        )
