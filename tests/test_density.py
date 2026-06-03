"""Tests for the density profile/value-area indicator and density_band sign."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from src.core.types import Side
from src.indicators.density import relative_dense_band, time_at_price_profile, value_area
from src.signs.density_band import DensityBandSign
from src.signs.density_breakout import DensityBreakoutSign


def test_profile_weight_is_one_per_ranged_bar() -> None:
    # Two bars, each spanning a different region; total weight == bar count.
    highs = [110.0, 130.0]
    lows = [100.0, 120.0]
    centers, weights = time_at_price_profile(highs, lows, n_bins=30)
    assert weights.sum() == pytest.approx(2.0)
    assert centers.shape == weights.shape == (30,)


def test_profile_concentrates_where_price_dwells() -> None:
    # Many bars dwell in [100, 102]; a couple wander up to 130. The busiest bin
    # must sit in the dwell zone, not the excursion zone.
    highs = [102.0] * 20 + [130.0, 131.0]
    lows = [100.0] * 20 + [128.0, 129.0]
    centers, weights = time_at_price_profile(highs, lows, n_bins=60)
    poc, lo, hi = value_area(centers, weights, coverage=0.70)
    assert 100.0 <= poc <= 102.0
    assert lo >= 99.0 and hi <= 104.0  # value area hugs the dwell zone


def test_relative_dense_band_finds_peak_in_wide_range() -> None:
    # Strong concentration around 100 plus wide excursions: the absolute value
    # area would be wide, but the relative band hugs the peak.
    highs = [100.5] * 30 + [120.0, 80.0, 121.0, 79.0]
    lows = [99.5] * 30 + [118.0, 78.0, 119.0, 77.0]
    centers, weights = time_at_price_profile(highs, lows, n_bins=80)
    band = relative_dense_band(centers, weights, sigma_r=1.0, min_poc_ratio=2.0)
    assert band is not None
    lo, hi = band
    assert lo <= 100.0 <= hi
    assert (hi - lo) < 10.0  # hugs the peak, not the full 80->120 range


def test_relative_dense_band_rejects_flat_period() -> None:
    # Near-uniform coverage (no real dense): the POC backstop returns None.
    rng = np.random.default_rng(11)
    base = list(100.0 + rng.uniform(-10, 10, 60))
    highs = [c + 0.5 for c in base]
    lows = [c - 0.5 for c in base]
    centers, weights = time_at_price_profile(highs, lows, n_bins=40)
    assert relative_dense_band(centers, weights, sigma_r=1.0, min_poc_ratio=3.0) is None


def test_flat_bar_deposits_full_weight() -> None:
    centers, weights = time_at_price_profile([100.0], [100.0], n_bins=11)
    assert weights.sum() == pytest.approx(1.0)


def test_value_area_widens_with_coverage() -> None:
    highs = [102.0] * 10 + [108.0] * 3 + [96.0] * 3
    lows = [100.0] * 10 + [106.0] * 3 + [94.0] * 3
    centers, weights = time_at_price_profile(highs, lows, n_bins=80)
    _, lo70, hi70 = value_area(centers, weights, coverage=0.70)
    _, lo95, hi95 = value_area(centers, weights, coverage=0.95)
    assert (hi95 - lo95) >= (hi70 - lo70)


def test_value_area_rejects_bad_coverage() -> None:
    centers, weights = time_at_price_profile([1.0, 2.0], [0.0, 1.0], n_bins=4)
    with pytest.raises(ValueError):
        value_area(centers, weights, coverage=0.0)


def _frame(highs: list[float], lows: list[float], closes: list[float]) -> pd.DataFrame:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    idx = pd.DatetimeIndex(
        [start + timedelta(hours=i) for i in range(len(highs))], name="timestamp"
    )
    return pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes}, index=idx
    )


def test_sign_fires_long_on_touch_from_above() -> None:
    # Build a dense band around 100 over the window, then push price up and bring
    # it back down to touch the top edge.
    win = 30
    rng = np.random.default_rng(0)
    base_close = list(100.0 + rng.normal(0, 0.3, win))
    base_hi = [c + 0.5 for c in base_close]
    base_lo = [c - 0.5 for c in base_close]
    # Excursion above the band, then a touch back down to the top edge (~101).
    closes = base_close + [105.0, 101.2]
    highs = base_hi + [105.5, 101.5]
    lows = base_lo + [104.5, 101.0]  # last bar low dips to ~101 (top edge)

    sign = DensityBandSign(window=win, n_bins=40, coverage=0.70, tol_pct=0.02)
    fire = sign.last_fire(_frame(highs, lows, closes))
    assert fire is not None
    assert fire.side is Side.LONG
    assert fire.ref_price is not None and fire.ref2_price is not None


def test_sign_no_fire_when_price_inside_band() -> None:
    win = 30
    rng = np.random.default_rng(1)
    base_close = list(100.0 + rng.normal(0, 0.3, win))
    highs = [c + 0.5 for c in base_close] + [100.2]
    lows = [c - 0.5 for c in base_close] + [99.8]
    closes = base_close + [100.0]  # prev close is inside the band -> no stage
    sign = DensityBandSign(window=win, n_bins=40)
    assert sign.last_fire(_frame(highs, lows, closes)) is None


def test_detect_matches_last_fire_no_lookahead() -> None:
    # detect() over the full frame must agree with last_fire() on each prefix:
    # a fire at index t may only use bars <= t.
    win = 20
    rng = np.random.default_rng(2)
    n = 80
    closes = list(100.0 + np.cumsum(rng.normal(0, 0.4, n)))
    highs = [c + 0.6 for c in closes]
    lows = [c - 0.6 for c in closes]
    df = _frame(highs, lows, closes)
    sign = DensityBandSign(window=win, n_bins=30, tol_pct=0.01)
    fires = {f.fired_at for f in sign.detect(df)}
    for t in range(len(df)):
        prefix = df.iloc[: t + 1]
        lf = sign.last_fire(prefix)
        if lf is not None:
            assert lf.fired_at in fires, f"prefix fire at {lf.fired_at} missing in detect"


def test_breakout_fires_long_on_close_above_top() -> None:
    # Consolidate inside a band around 100, then close out above the top edge.
    win = 30
    rng = np.random.default_rng(3)
    base_close = list(100.0 + rng.normal(0, 0.3, win))
    highs = [c + 0.5 for c in base_close]
    lows = [c - 0.5 for c in base_close]
    # prev bar closes inside the band (~100.2), breakout bar closes well above.
    closes = base_close + [100.2, 103.0]
    highs = highs + [100.7, 103.5]
    lows = lows + [99.7, 100.4]
    sign = DensityBreakoutSign(window=win, n_bins=40, coverage=0.70)
    fire = sign.last_fire(_frame(highs, lows, closes))
    assert fire is not None
    assert fire.side is Side.LONG
    # ref = broken (top) edge, ref2 = opposite (bottom) edge / stop level.
    assert fire.ref_price is not None and fire.ref2_price is not None
    assert fire.ref2_price < fire.ref_price


def test_breakout_no_fire_when_prev_close_outside_band() -> None:
    # If the prior bar already closed ABOVE the band, this is not a breakout from
    # inside (it is the bounce setup) -> no breakout fire.
    win = 30
    rng = np.random.default_rng(4)
    base_close = list(100.0 + rng.normal(0, 0.3, win))
    highs = [c + 0.5 for c in base_close] + [104.0, 105.0]
    lows = [c - 0.5 for c in base_close] + [103.0, 104.0]
    closes = base_close + [103.5, 104.5]  # prev close already outside (above)
    sign = DensityBreakoutSign(window=win, n_bins=40)
    assert sign.last_fire(_frame(highs, lows, closes)) is None


def test_breakout_max_band_pct_filters_wide_box() -> None:
    # A very wide band should be filtered out by a tight max_band_pct.
    win = 30
    rng = np.random.default_rng(5)
    base_close = list(100.0 + rng.normal(0, 5.0, win))  # wide dispersion
    highs = [c + 1.0 for c in base_close] + [100.0, 130.0]
    lows = [c - 1.0 for c in base_close] + [99.0, 110.0]
    closes = base_close + [100.0, 130.0]
    tight = DensityBreakoutSign(window=win, n_bins=40, max_band_pct=0.02)
    assert tight.last_fire(_frame(highs, lows, closes)) is None
