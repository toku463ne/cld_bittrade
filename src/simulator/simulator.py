"""Bar-based trade simulator with the two-bar fill rule.

A single position is held at a time (scalping, minimum lot). On each bar:

1. If a position is open, evaluate exits on the *current* bar.
2. If flat and a pending signal exists from the previous bar, fill at this
   bar's open (two-bar fill rule).
3. Feed the bar to the strategy; any new signal becomes pending for next bar.

ATR at entry is taken from the ATR series computed over the full input so
exit sizing matches what the strategy saw.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from src.core.types import Bar, ExitConfig, ExitReason, Signal, Trade
from src.exit.rules import OpenPosition, evaluate_exit, tp_sl_levels
from src.indicators import atr
from src.strategy.base import Strategy

# Per-side TAKER cost as a fraction of price. bitFlyer FX_BTC_JPY (now Crypto CFD,
# formerly Lightning FX) has **0% trading commission** — verified from the official
# API docs (gettradingcommission returns commission: 0). The real taker cost is
# therefore SLIPPAGE: crossing the half-spread on each side. ~1-2 bps in calm
# markets, wider (10-20 bps) in volatile bursts; situational SWAP (~0.04%/day, only
# if held across the daily clearing) and SFD (only if CFD deviates ≥5% from spot)
# are NOT modelled here. A MAKER would instead EARN this spread (negative cost).
# NOTE: the prior value 0.001 (0.1%/side) was the bitFlyer SPOT fee, wrongly applied
# to this commission-free venue — it over-penalised every backtest by ~10x. 0.0002
# (2 bps/side) is a conservative calm-market central estimate; sweep it to check
# sensitivity (see src/backtest/analysis/cost_sensitivity_rerun.py).
DEFAULT_FEE_RATE = 0.0002


@dataclass(slots=True)
class SimResult:
    """Output of a simulation run.

    Attributes:
        trades: Completed round-trip trades in entry order.
        strategy_name: Name of the simulated strategy.
        n_bars: Number of bars processed.
    """

    trades: list[Trade]
    strategy_name: str
    n_bars: int = 0
    equity_curve: list[float] = field(default_factory=list)


class Simulator:
    """Single-position bar simulator honouring the two-bar fill rule.

    Args:
        strategy: The strategy to drive.
        size: Position size in BTC (minimum lot by default).
        atr_period: ATR period used to size ATR-based exits at entry.
        fee_rate: Per-side taker fee rate. The round-trip cost deducted from each
            trade is ``entry_price × size × fee_rate × 2``.
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
        """Run the simulation over ``bars``.

        Args:
            bars: Time-ordered bars.

        Returns:
            A :class:`SimResult` with the realised trades and equity curve.
        """
        self.strategy.reset()
        exit_cfg = self.strategy.get_exit_rules()

        # Precompute ATR over the full series for entry sizing.
        atr_vals = self._atr_series(bars)

        # Fast path: if the strategy can precompute all signals over the full
        # series (vectorised), look them up per bar in O(1) instead of running
        # the O(N) on_bar buffer evaluation every bar (which is O(N^2) total).
        precomputed = self.strategy.precompute(bars)

        trades: list[Trade] = []
        equity = 0.0
        equity_curve: list[float] = []
        pending: Signal | None = None
        pending_atr: float = 0.0
        pos: OpenPosition | None = None
        pos_cfg: ExitConfig = exit_cfg  # exit config for the currently open trade
        entry_time = bars[0].timestamp if bars else None
        entry_idx = 0

        for i, bar in enumerate(bars):
            # 1. Manage an open position on the current bar.
            if pos is not None:
                result = evaluate_exit(pos, bar, pos_cfg)
                if result is not None:
                    reason, exit_price = result
                    trade = self._close(pos, entry_time, bar, exit_price, reason, i - entry_idx)
                    trades.append(trade)
                    equity += trade.pnl
                    pos = None
                else:
                    pos.bars_held += 1

            # 2. Fill a pending signal at this bar's open (two-bar fill).
            if pos is None and pending is not None:
                pos = OpenPosition(
                    side=pending.side,
                    entry_price=bar.open,
                    entry_atr=pending_atr,
                )
                # Per-trade exit config (e.g. ZS TP/SL) overrides the static one.
                pos_cfg = pending.exit_config or exit_cfg
                pos.tp_price, pos.sl_price = tp_sl_levels(pos, pos_cfg)
                pos.ref_time, pos.ref_price = pending.ref_time, pending.ref_price
                pos.ref2_time, pos.ref2_price = pending.ref2_time, pending.ref2_price
                entry_time = bar.timestamp
                entry_idx = i
                pending = None

            # 3. Generate a new signal from the just-closed bar.
            if precomputed is not None:
                signal = precomputed.get(bar.timestamp) if pos is None else None
            elif pos is None:
                signal = self.strategy.push(bar)
            else:
                # Keep the strategy buffer in sync even while in a position.
                self.strategy.push(bar)
                signal = None
            if signal is not None:
                pending = signal
                pending_atr = atr_vals[i]

            equity_curve.append(equity)

        # Close any position still open at end of data.
        if pos is not None and bars:
            last = bars[-1]
            trade = self._close(
                pos, entry_time, last, last.close, ExitReason.END_OF_DATA, len(bars) - 1 - entry_idx
            )
            trades.append(trade)
            equity += trade.pnl
            equity_curve[-1] = equity

        logger.info(
            "Simulated {} bars for '{}': {} trades, net PnL {:.1f}",
            len(bars),
            self.strategy.name,
            len(trades),
            equity,
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

        df = pd.DataFrame(
            {
                "high": [b.high for b in bars],
                "low": [b.low for b in bars],
                "close": [b.close for b in bars],
            }
        )
        return [float(v) for v in atr(df, self.atr_period).to_numpy()]

    def _close(
        self,
        pos: OpenPosition,
        entry_time: object,
        bar: Bar,
        exit_price: float,
        reason: ExitReason,
        bars_held: int,
    ) -> Trade:
        from datetime import datetime

        assert isinstance(entry_time, datetime)
        # Round-trip trading cost: entry and exit are each charged fee_rate.
        cost = pos.entry_price * self.size * self.fee_rate * 2.0
        return Trade(
            side=pos.side,
            entry_time=entry_time,
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
