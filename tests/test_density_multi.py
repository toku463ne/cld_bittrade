"""Tests for the multi-position simulator and density_multi_breakout strategy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from src.core.types import Bar, ExitConfig, ExitReason, Side, Signal
from src.exit.rules import OpenPosition
from src.simulator import MultiSimulator
from src.strategy.base import Strategy
from src.strategy.density_multi_breakout import DensityMultiBreakoutStrategy

_T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _bars(closes: list[float], highs: list[float], lows: list[float]) -> list[Bar]:
    return [
        Bar(timestamp=_T0 + timedelta(hours=i), open=c, high=h, low=lo, close=c, volume=1.0)
        for i, (c, h, lo) in enumerate(zip(closes, highs, lows, strict=True))
    ]


class _EveryBarLong(Strategy):
    """Fires LONG every bar with an exit that never triggers (for slot-cap tests)."""

    name = "_every_bar_long"
    max_slots = 3

    def precompute(self, bars: list[Bar]) -> dict[object, Signal] | None:  # type: ignore[override]
        # Huge stop, no TP/time -> positions only close at end of data.
        cfg = ExitConfig(sl_abs=1e9)
        return {
            b.timestamp: Signal(side=Side.LONG, timestamp=b.timestamp, price=b.close, exit_config=cfg)
            for b in bars
        }

    def on_bar(self, bar: Bar) -> Signal | None:
        return None

    def get_exit_rules(self) -> ExitConfig:
        return ExitConfig()


def test_multi_simulator_caps_concurrent_slots() -> None:
    # Entry every bar, nothing ever exits before the end -> only max_slots fill,
    # all close at end_of_data.
    n = 10
    bars = _bars([100.0] * n, [100.5] * n, [99.5] * n)
    res = MultiSimulator(_EveryBarLong(), size=0.001).run(bars)
    assert len(res.trades) == 3  # capped at max_slots
    assert all(t.exit_reason is ExitReason.END_OF_DATA for t in res.trades)
    assert len(res.equity_curve) == n


def test_multi_simulator_two_bar_fill() -> None:
    # First signal fires on bar 0's close, fills at bar 1's open (two-bar rule).
    bars = _bars([100.0] * 5, [100.5] * 5, [99.5] * 5)
    res = MultiSimulator(_EveryBarLong(), size=0.001).run(bars)
    # The earliest entry is bar index 1 (filled at the open after the bar-0 fire).
    assert min(t.entry_time for t in res.trades) == _T0 + timedelta(hours=1)


def test_multi_simulator_daily_swap() -> None:
    # 30 flat hourly bars from 2024-01-01 00:00 UTC cross exactly one calendar-day
    # boundary (2024-01-02 00:00). With max_slots=3 all three positions are open
    # before the boundary and held to end, so each is charged swap once.
    n = 30
    bars = _bars([100.0] * n, [100.5] * n, [99.5] * n)
    rate, size = 0.01, 1.0  # swap = rate * size * close = 0.01 * 1 * 100 = 1.0 / boundary

    base = MultiSimulator(_EveryBarLong(), size=size, fee_rate=0.0).run(bars)
    swapped = MultiSimulator(
        _EveryBarLong(), size=size, fee_rate=0.0, daily_swap_rate=rate
    ).run(bars)

    assert sum(t.cost for t in base.trades) == 0.0  # fee-free, no swap
    # 3 positions held across 1 boundary -> 3 * 1.0 folded into trade cost.
    assert sum(t.cost for t in swapped.trades) == pytest.approx(3.0)
    # Flat price -> realised PnL is exactly minus the swap; it shows in the equity path.
    assert swapped.equity_curve[-1] == pytest.approx(-3.0)
    # daily_swap_rate=0.0 must be a no-op vs the default constructor.
    assert base.equity_curve[-1] == pytest.approx(0.0)


class _OneLongTightStop(Strategy):
    """Fires LONG once (bar 0); a tight stop is hit on the down-bar -> STOP_LOSS exit."""

    name = "_one_long_tight_stop"
    max_slots = 1

    def precompute(self, bars: list[Bar]) -> dict[object, Signal] | None:  # type: ignore[override]
        cfg = ExitConfig(sl_abs=1.0)  # stop 1.0 below entry
        b0 = bars[0]
        return {
            b0.timestamp: Signal(side=Side.LONG, timestamp=b0.timestamp, price=b0.close, exit_config=cfg)
        }

    def on_bar(self, bar: Bar) -> Signal | None:
        return None

    def get_exit_rules(self) -> ExitConfig:
        return ExitConfig()


def test_multi_simulator_burst_cost_on_stop_only() -> None:
    # Entry fills at bar-1 open (100); bar-2 low (97) breaches the stop at 99 -> STOP_LOSS.
    closes = [100.0, 100.0, 100.0, 100.0]
    highs = [100.5, 100.5, 100.5, 100.5]
    lows = [99.5, 99.5, 97.0, 99.5]
    bars = _bars(closes, highs, lows)
    fee, size, mult = 0.0002, 1.0, 5.0

    base = MultiSimulator(_OneLongTightStop(), size=size, fee_rate=fee).run(bars)
    burst = MultiSimulator(
        _OneLongTightStop(), size=size, fee_rate=fee, burst_cost_mult=mult
    ).run(bars)

    assert len(base.trades) == 1
    t_base, t_burst = base.trades[0], burst.trades[0]
    assert t_base.exit_reason is ExitReason.STOP_LOSS
    # Base round-trip = entry*size*fee*2; burst adds exit_price*size*fee*(mult-1) on the stop.
    assert t_base.cost == pytest.approx(100.0 * size * fee * 2.0)
    surcharge = t_burst.exit_price * size * fee * (mult - 1.0)
    assert t_burst.cost == pytest.approx(t_base.cost + surcharge)
    # burst_cost_mult=1.0 must be an exact no-op.
    noop = MultiSimulator(
        _OneLongTightStop(), size=size, fee_rate=fee, burst_cost_mult=1.0
    ).run(bars)
    assert noop.trades[0].cost == pytest.approx(t_base.cost)


def test_burst_cost_no_surcharge_off_stop_exits() -> None:
    # _EveryBarLong never stops out (huge sl) -> burst_cost_mult must not change cost.
    bars = _bars([100.0] * 8, [100.5] * 8, [99.5] * 8)
    base = MultiSimulator(_EveryBarLong(), size=1.0, fee_rate=0.0002).run(bars)
    burst = MultiSimulator(
        _EveryBarLong(), size=1.0, fee_rate=0.0002, burst_cost_mult=5.0
    ).run(bars)
    assert sum(t.cost for t in base.trades) == pytest.approx(sum(t.cost for t in burst.trades))


def test_multi_strategy_is_registered_and_multi() -> None:
    from src.strategy.registry import get_strategy

    s = get_strategy("density_multi_breakout")
    assert isinstance(s, DensityMultiBreakoutStrategy)
    assert s.max_slots > 1


def test_density_multi_precompute_emits_breakout_with_exit_config() -> None:
    # Tight consolidation around 100, then a close above the top edge -> a LONG
    # entry carrying a structural stop (sl_abs) in its exit_config.
    win = 30
    rng = np.random.default_rng(7)
    base = list(100.0 + rng.normal(0, 0.3, win))
    closes = base + [100.2, 103.0]
    highs = [c + 0.5 for c in base] + [100.7, 103.5]
    lows = [c - 0.5 for c in base] + [99.7, 100.4]
    strat = DensityMultiBreakoutStrategy(window=win, n_bins=40, max_band_pct=0.05)
    sigs = strat.precompute(_bars(closes, highs, lows))
    assert sigs  # at least one entry
    longs = [s for s in sigs.values() if s.side is Side.LONG]
    assert longs
    assert all(s.exit_config is not None and s.exit_config.sl_abs is not None for s in longs)


def test_density_multi_stall_exit_fires_in_new_box() -> None:
    # Construct a position whose band index sits inside a fresh tight box far from
    # the entry price -> the stall (dynamic) exit should trigger.
    strat = DensityMultiBreakoutStrategy(window=4, max_band_pct=0.05, min_hold=2)
    # Rolling bands: a tight box [109, 111] at index i=5 (price 110 inside it).
    strat._band_lo = np.array([np.nan] * 5 + [109.0])
    strat._band_hi = np.array([np.nan] * 5 + [111.0])
    pos = OpenPosition(side=Side.LONG, entry_price=100.0, entry_atr=1.0)
    pos.ref_price, pos.ref2_price = 101.0, 100.0  # entry band height ~1
    bar = Bar(timestamp=_T0, open=110.0, high=110.5, low=109.5, close=110.0, volume=1.0)
    out = strat.dynamic_exit(pos, bar, i=5, entry_idx=0)
    assert out is not None
    assert out[0] is ExitReason.TRAIL_STOP
