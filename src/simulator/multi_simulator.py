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

from src.core.types import Bar, ExitConfig, ExitReason, Side, Signal, Trade
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
    swap: float = 0.0  # accrued daily-swap/funding cost (JPY) while held


@dataclass(slots=True)
class _Working:
    """A resting limit order awaiting a touch (or expiry)."""

    sig: Signal
    limit_price: float
    atr: float
    expiry_idx: int


class MultiSimulator:
    """Bar simulator holding up to ``strategy.max_slots`` concurrent positions.

    Args:
        strategy: The strategy to drive (must implement ``precompute``).
        size: Per-slot position size in BTC (minimum lot by default).
        atr_period: ATR period for entry sizing (parity with the single sim).
        fee_rate: Per-side taker cost; round-trip = ``entry × size × rate × 2``.
        daily_swap_rate: Daily funding/swap as a fraction of position notional,
            charged once per calendar day on every position **held across the
            day boundary** (e.g. bitFlyer Lightning FX_BTC_JPY = ``0.0004`` =
            0.04%/day at the 00:00 JST cutoff). ``0.0`` (default) = no swap, so
            commission-free spot/GMO backtests are unchanged. The accrued swap is
            folded into each trade's ``cost`` (so it flows into per-trade PnL and
            returns) and debited from the mark-to-market equity path as it accrues.
        burst_cost_mult: Spread multiplier applied to the **exit leg** of a
            ``STOP_LOSS`` exit only — the burst-aftermath fill, the widest-spread
            moment on bitFlyer FX. The stop's exit half-spread becomes
            ``fee_rate × burst_cost_mult`` (entry leg and all non-stop exits stay at
            ``fee_rate``). ``1.0`` (default) = exact no-op, preserving the
            deterministic benchmark snapshot. e.g. base ``fee_rate=0.0002`` (2 bp)
            with ``burst_cost_mult=5.0`` charges 10 bp on stop exits — the realistic
            burst-fill cost identified as vol_expansion_ride's binding, otherwise-
            unmeasurable risk (~79% of its exits are stops). GMO OHLC cannot observe
            this spread, so it is modelled as a parameter rather than read from bars.
    """

    def __init__(
        self,
        strategy: Strategy,
        *,
        size: float = 0.001,
        atr_period: int = 14,
        fee_rate: float = DEFAULT_FEE_RATE,
        daily_swap_rate: float = 0.0,
        burst_cost_mult: float = 1.0,
    ) -> None:
        if daily_swap_rate < 0.0:
            raise ValueError("daily_swap_rate must be >= 0")
        if burst_cost_mult < 1.0:
            raise ValueError("burst_cost_mult must be >= 1")
        self.strategy = strategy
        self.size = size
        self.atr_period = atr_period
        self.fee_rate = fee_rate
        self.daily_swap_rate = daily_swap_rate
        self.burst_cost_mult = burst_cost_mult

    def run(self, bars: list[Bar]) -> SimResult:
        """Run the multi-position simulation over ``bars``."""
        self.strategy.reset()
        fallback_cfg = self.strategy.get_exit_rules()
        max_slots = max(1, self.strategy.max_slots)
        atr_vals = self._atr_series(bars)

        # Prefer the multi-signal hook (several entries per bar, e.g. a hedged
        # pair); otherwise wrap the single-signal precompute as one-element lists.
        signals_by_ts: dict[object, list[Signal]]
        multi = self.strategy.precompute_multi(bars)
        if multi is not None:
            signals_by_ts = {ts: list(sigs) for ts, sigs in multi.items()}
        else:
            precomputed = self.strategy.precompute(bars)
            if precomputed is None:
                raise ValueError(
                    f"MultiSimulator requires a precompute()/precompute_multi() strategy; "
                    f"'{self.strategy.name}' returned None."
                )
            signals_by_ts = {ts: [sig] for ts, sig in precomputed.items()}

        trades: list[Trade] = []
        equity_curve: list[float] = []
        realised = 0.0
        book: list[_Slot] = []
        pending: list[Signal] = []
        pending_atr = 0.0
        working: list[_Working] = []
        swap_open = 0.0  # accrued swap on still-open positions (debited from equity)
        prev_date = None  # JST calendar date of the previous bar

        for i, bar in enumerate(bars):
            # 0. Daily swap/funding: on each new calendar day, charge every position
            #    carried across the boundary (per-slot, folded into its eventual cost
            #    and debited from equity now). New entries below are not yet held
            #    across a cutoff, so they are charged from the next boundary on.
            if self.daily_swap_rate > 0.0:
                d = bar.timestamp.date()
                if prev_date is not None and d != prev_date:
                    for slot in book:
                        inc = self.daily_swap_rate * self.size * bar.close
                        slot.swap += inc
                        swap_open += inc
                prev_date = d

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
                    swap_open -= slot.swap  # now realised via trade.cost
            book = survivors

            # 2. Fill market pending signals at this bar's open while slots are
            #    free (a hedged pair fills both legs; the two-bar rule is preserved).
            for sig in pending:
                if len(book) >= max_slots:
                    break
                book.append(self._open(sig, bar.open, pending_atr, i, bar.timestamp, fallback_cfg))
            pending = []

            # 3. Resting limit orders: fill at the limit on a touch (better price),
            #    drop on expiry. An order placed reading bar t is eligible from t+1
            #    (added in step 4, below), so this is causal.
            kept: list[_Working] = []
            for wo in working:
                if i > wo.expiry_idx:
                    continue  # cancelled, never touched
                hit = (
                    (wo.sig.side is Side.LONG and bar.low <= wo.limit_price)
                    or (wo.sig.side is Side.SHORT and bar.high >= wo.limit_price)
                )
                if hit and len(book) < max_slots:
                    book.append(
                        self._open(wo.sig, wo.limit_price, wo.atr, i, bar.timestamp, fallback_cfg)
                    )
                else:
                    kept.append(wo)  # not touched, or no free slot — keep until expiry
            working = kept

            # 4. Read the precomputed signal(s) for this just-closed bar: market
            #    orders -> pending (next-open fill); limit orders -> working.
            sigs = signals_by_ts.get(bar.timestamp)
            if sigs:
                market = [s for s in sigs if s.limit_price is None]
                if market:
                    pending = market
                    pending_atr = atr_vals[i]
                for s in sigs:
                    if s.limit_price is not None:
                        working.append(
                            _Working(s, s.limit_price, atr_vals[i], i + max(1, s.limit_expiry_bars))
                        )

            # Mark-to-market: realised + unrealised across the open book, less the
            # swap accrued so far on still-open positions.
            unreal = sum(
                s.pos.side.sign * (bar.close - s.pos.entry_price) * self.size for s in book
            )
            equity_curve.append(realised + unreal - swap_open)

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

    def _open(
        self,
        sig: Signal,
        fill_price: float,
        atr: float,
        i: int,
        ts: datetime,
        fallback_cfg: ExitConfig,
    ) -> _Slot:
        """Open a position from ``sig`` filled at ``fill_price`` (market or limit)."""
        pos = OpenPosition(side=sig.side, entry_price=fill_price, entry_atr=atr)
        cfg = sig.exit_config or fallback_cfg
        pos.tp_price, pos.sl_price = tp_sl_levels(pos, cfg)
        pos.ref_time, pos.ref_price = sig.ref_time, sig.ref_price
        pos.ref2_time, pos.ref2_price = sig.ref2_time, sig.ref2_price
        return _Slot(pos, i, ts, cfg)

    def _close(
        self, slot: _Slot, bar: Bar, exit_price: float, reason: ExitReason, bars_held: int
    ) -> Trade:
        pos = slot.pos
        cost = pos.entry_price * self.size * self.fee_rate * 2.0 + slot.swap
        # Burst-aftermath surcharge: a stop-out fills at the widest-spread moment, so
        # its exit leg pays (mult-1)x extra half-spread. No-op when burst_cost_mult==1.
        if reason is ExitReason.STOP_LOSS and self.burst_cost_mult != 1.0:
            cost += exit_price * self.size * self.fee_rate * (self.burst_cost_mult - 1.0)
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
