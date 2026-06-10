"""Unit tests for the density_pullback failed-breakout invalidation exit."""

from __future__ import annotations

from datetime import datetime, timezone

from src.core.types import Bar, ExitReason, Side
from src.exit.rules import OpenPosition
from src.strategy.density_pullback import DensityPullbackStrategy

_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _bar(close: float) -> Bar:
    return Bar(timestamp=_TS, open=close, high=close + 0.5, low=close - 0.5, close=close, volume=1.0)


def _pos(side: Side, inval: float | None) -> OpenPosition:
    # sl_price=None keeps the inherited ratchet inert so the test isolates the
    # invalidation branch; ref2_price carries the frozen invalidation level.
    pos = OpenPosition(side=side, entry_price=100.0, entry_atr=1.0, sl_price=None)
    pos.ref2_price = inval
    return pos


def test_invalidation_long_exits_on_close_below_level() -> None:
    strat = DensityPullbackStrategy(invalidation_depth=0.5)
    pos = _pos(Side.LONG, inval=99.0)
    assert strat.dynamic_exit(pos, _bar(98.5), 10, 5) == (ExitReason.STOP_LOSS, 98.5)
    # A close at/above the level holds.
    assert strat.dynamic_exit(pos, _bar(99.0), 11, 5) is None
    assert strat.dynamic_exit(pos, _bar(99.5), 12, 5) is None


def test_invalidation_short_exits_on_close_above_level() -> None:
    strat = DensityPullbackStrategy(invalidation_depth=0.5)
    pos = _pos(Side.SHORT, inval=101.0)
    assert strat.dynamic_exit(pos, _bar(101.5), 10, 5) == (ExitReason.STOP_LOSS, 101.5)
    assert strat.dynamic_exit(pos, _bar(100.5), 11, 5) is None


def test_invalidation_off_is_noop() -> None:
    # Knob off: even a position carrying a ref2 level must not exit on it.
    strat = DensityPullbackStrategy()
    assert strat.invalidation_depth is None
    pos = _pos(Side.LONG, inval=99.0)
    assert strat.dynamic_exit(pos, _bar(90.0), 10, 5) is None


def test_invalidation_signals_carry_ref2_only_when_on() -> None:
    import pytest

    with pytest.raises(ValueError):
        DensityPullbackStrategy(invalidation_depth=0.0)
    with pytest.raises(ValueError):
        DensityPullbackStrategy(invalidation_depth=-1.0)


def test_max_base_bars_validation_and_default() -> None:
    import pytest

    # Adopted default (2026-06-11): the BTC-chosen stale-box gate, ETH-replicated.
    assert DensityPullbackStrategy().max_base_bars == 64
    assert DensityPullbackStrategy(max_base_bars=None).max_base_bars is None
    assert DensityPullbackStrategy(max_base_bars=32).max_base_bars == 32
    with pytest.raises(ValueError):
        DensityPullbackStrategy(max_base_bars=0)


def test_density_pullback_eth_variant_registered() -> None:
    from src.strategy.density_pullback import DensityPullbackEthStrategy
    from src.strategy.registry import get_strategy

    s = get_strategy("density_pullback_eth")
    assert isinstance(s, DensityPullbackEthStrategy)
    assert s.invalidation_depth == 0.25  # the ETH-only adoption (C'')
    assert s.recalc_bars == 72  # ETH-only slower ratchet (C''')
    # The BTC defaults must remain — those verdicts stand.
    assert DensityPullbackStrategy().invalidation_depth is None
    assert DensityPullbackStrategy().recalc_bars == 48
    assert DensityPullbackStrategy().limit_offset == 0.0  # offset rejected (C''')


def test_combo_dp_ver_registered_and_multi() -> None:
    from src.strategy.combo_dp_ver import ComboDpVerStrategy
    from src.strategy.registry import get_strategy

    s = get_strategy("combo_dp_ver")
    assert isinstance(s, ComboDpVerStrategy)
    assert s.max_slots == 12  # dp's existing live peak-capital budget
    # Empty input -> empty signal dict (the merged precompute path is wired).
    assert s.precompute_multi([]) == {}
