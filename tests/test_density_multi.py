"""Tests for the multi-position simulator and density_multi_breakout strategy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

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
