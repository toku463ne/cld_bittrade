"""Tests for the zigzag indicator, ZS exit rule, and zigzag_bounce detection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from src.core.types import ExitConfig, Side
from src.exit.base import ExitContext
from src.exit.zs_tp_sl import ZsTpSl, ewa
from src.indicators.zigzag import confirmed_leg_sizes, detect_peaks
from src.signs.zigzag_bounce import ZigzagBounceSign


def _triangle(peaks_at: list[int], n: int, base: float = 100.0, amp: float = 10.0) -> list[float]:
    """Build a series with highs spiking at given indices (for peak tests)."""
    vals = [base] * n
    for p in peaks_at:
        vals[p] = base + amp
    return vals


def test_detect_peaks_finds_confirmed_high() -> None:
    n = 41
    highs = [100.0] * n
    highs[20] = 130.0  # a clear isolated high, 20 bars each side
    lows = [90.0] * n
    peaks = detect_peaks(highs, lows, size=10, middle_size=3)
    highs_found = [p for p in peaks if p.is_high and p.is_confirmed]
    assert any(p.bar_index == 20 for p in highs_found)


def test_detect_peaks_middle_size_smaller_than_size_required() -> None:
    import pytest

    with pytest.raises(ValueError):
        detect_peaks([1.0, 2.0], [0.0, 1.0], size=3, middle_size=5)


def test_confirmed_leg_sizes_are_absolute_gaps() -> None:
    n = 61
    highs = [100.0] * n
    lows = [90.0] * n
    highs[20] = 140.0
    lows[40] = 60.0
    peaks = detect_peaks(highs, lows, size=10, middle_size=3)
    legs = confirmed_leg_sizes(peaks)
    assert all(leg >= 0.0 for leg in legs)


def test_ewa_weights_recent_more() -> None:
    # Newest leg (last) is large; EWA should sit above the small older legs.
    val = ewa((1.0, 1.0, 1.0, 10.0), alpha=0.5)
    assert val > 1.0


def test_zs_exit_config_uses_band_when_enough_legs() -> None:
    rule = ZsTpSl(tp_mult=1.5, sl_mult=1.0, alpha=0.3, min_legs=3, fallback_pct=0.01)
    ctx = ExitContext(side=Side.LONG, entry_price=1_000_000.0, zs_history=(20_000.0, 20_000.0, 20_000.0))
    cfg = rule.exit_config(ctx)
    assert isinstance(cfg, ExitConfig)
    assert cfg.tp_abs is not None and cfg.sl_abs is not None
    assert abs(cfg.tp_abs - 1.5 * 20_000.0) < 1e-6
    assert abs(cfg.sl_abs - 1.0 * 20_000.0) < 1e-6


def test_zs_exit_config_falls_back_without_enough_legs() -> None:
    rule = ZsTpSl(tp_mult=1.5, sl_mult=1.0, min_legs=3, fallback_pct=0.01)
    ctx = ExitContext(side=Side.SHORT, entry_price=1_000_000.0, zs_history=(20_000.0,))
    cfg = rule.exit_config(ctx)
    band = 1_000_000.0 * 0.01
    assert cfg.tp_abs is not None and abs(cfg.tp_abs - 1.5 * band) < 1e-6


def test_bounce_sign_shorts_early_high_near_recent_high() -> None:
    # Construct hourly bars: an old confirmed high near price P, then price comes
    # back up to ~P forming a right-edge early high -> expect a SHORT fire.
    size, mid = 10, 3
    sign = ZigzagBounceSign(size=size, mid_size=mid, lookback=72, tol_pct=0.01)
    ts0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    n = 120
    highs = [12_000_000.0] * n
    # old confirmed resistance at index 70 (within the 72-bar lookback of ep)
    highs[70] = 12_120_000.0
    # right-edge early high mid bars before the end, near the old resistance
    ep = n - 1 - mid
    highs[ep] = 12_118_000.0
    # Lows track highs (realistic; avoids a flat-low region reading as an
    # 'early low' everywhere, which the ambiguity guard would reject).
    lows = [h - 50_000.0 for h in highs]
    close = [(h + low) / 2 for h, low in zip(highs, lows)]
    df = pd.DataFrame(
        {"open": close, "high": highs, "low": lows, "close": close, "volume": [1.0] * n},
        index=pd.DatetimeIndex([ts0 + timedelta(hours=i) for i in range(n)]),
    )
    fire = sign.last_fire(df)
    assert fire is not None
    assert fire.side is Side.SHORT
