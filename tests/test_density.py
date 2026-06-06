"""Tests for the density profile/value-area indicator and density_band sign."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from src.core.types import Side
from src.indicators.density import (
    find_walls,
    relative_dense_band,
    time_acceptance_profile,
    time_at_price_profile,
    value_area,
    volume_acceptance_profile,
)
from src.signs.density_band import DensityBandSign
from src.signs.density_breakout import DensityBreakoutSign
from src.signs.density_breakout_acc import DensityBreakoutAccSign
from src.signs.density_breakout_vol import DensityBreakoutVolSign


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


# --- volume_acceptance_profile -------------------------------------------------


def test_volume_profile_per_bar_weight_is_conserved_regardless_of_shape() -> None:
    # THE invariant the naive `/ (high - low)` formula violates: with equal
    # volume, every bar contributes exactly 1.0 of weight no matter its body/wick
    # shape (marubozu, doji, top-heavy, bottom-heavy). Total == bar count.
    opens =  [100.0, 100.0, 105.0, 101.0, 109.0]  # noqa: E222
    closes = [110.0, 100.1, 95.0, 101.2, 91.0]    # marubozu, ~doji, mixed...
    highs =  [110.0, 106.0, 105.5, 108.0, 110.0]  # noqa: E222
    lows =   [100.0, 94.0, 94.5, 92.0, 90.0]      # noqa: E222
    vols =   [1.0, 1.0, 1.0, 1.0, 1.0]            # noqa: E222
    for br in (0.1, 0.5, 0.7, 0.9):
        _, w = volume_acceptance_profile(
            opens, highs, lows, closes, vols, n_bins=64, body_ratio=br
        )
        assert w.sum() == pytest.approx(len(opens)), f"body_ratio={br}"


def test_volume_profile_total_tracks_normalised_volume() -> None:
    # With non-flat volume the total equals sum(norm_vol) = sum(v)/mean(v).
    opens = [100.0, 200.0, 300.0]
    closes = [101.0, 201.0, 301.0]
    highs = [102.0, 202.0, 302.0]
    lows = [99.0, 199.0, 299.0]
    vols = [1.0, 4.0, 7.0]
    _, w = volume_acceptance_profile(opens, highs, lows, closes, vols, n_bins=80)
    expected = sum(vols) / (sum(vols) / len(vols))  # == n bars
    assert w.sum() == pytest.approx(expected)


def test_volume_profile_volume_dominates_the_poc() -> None:
    # Two equal-shape bars in different price regions; the high-volume one wins
    # the Point-of-Control, which a pure time profile (equal weight) would not.
    opens = [100.0, 200.0]
    closes = [101.0, 201.0]
    highs = [101.0, 201.0]
    lows = [100.0, 200.0]
    vols = [1.0, 20.0]  # second region traded 20x
    centers, w = volume_acceptance_profile(opens, highs, lows, closes, vols, n_bins=60)
    poc = float(centers[int(np.argmax(w))])
    assert 200.0 <= poc <= 201.0


def test_volume_profile_body_weighting_makes_the_body_the_poc() -> None:
    # A bar with a small body up high and a long lower rejection wick. A
    # body-heavy ratio raises the *per-bin density* in the body, so the busiest
    # bin (POC) lands in the body even though the wick spans far more price.
    opens, closes = [109.0], [110.0]   # body in [109, 110]
    highs, lows = [110.0], [90.0]      # long lower wick down to 90
    vols = [1.0]
    centers, w = volume_acceptance_profile(
        opens, highs, lows, closes, vols, n_bins=40, body_ratio=0.9
    )
    poc = float(centers[int(np.argmax(w))])
    assert poc >= 108.0  # POC sits in the body, not the long wick
    # Per-bin density in the body strictly exceeds the wick (9:1 at ratio 0.9).
    body_bins = w[centers >= 109.0]
    wick_bins = w[(centers < 109.0) & (w > 0)]
    assert body_bins.mean() > wick_bins.mean()


def test_volume_profile_body_ratio_half_matches_uniform_volume_profile() -> None:
    # body_ratio == 0.5 weights body and wick equally => mass spreads uniformly
    # across the bar's range, i.e. a plain volume profile with no acceptance tilt.
    opens, closes = [109.0], [110.0]
    highs, lows = [110.0], [90.0]
    vols = [3.0]
    centers, w = volume_acceptance_profile(
        opens, highs, lows, closes, vols, n_bins=40, body_ratio=0.5
    )
    covered = w[w > 0]
    # All covered bins carry equal weight (uniform spread over [90, 110]).
    assert covered.std() == pytest.approx(0.0, abs=1e-9)
    assert w.sum() == pytest.approx(1.0)  # single bar => norm_vol == 1


def test_volume_profile_flat_bar_deposits_full_weight() -> None:
    centers, w = volume_acceptance_profile(
        [100.0], [100.0], [100.0], [100.0], [5.0], n_bins=11
    )
    assert w.sum() == pytest.approx(1.0)  # single bar => norm_vol == 1


def test_volume_profile_zero_volume_falls_back_to_equal_weight() -> None:
    opens = [100.0, 200.0]
    closes = [101.0, 201.0]
    highs = [102.0, 202.0]
    lows = [99.0, 199.0]
    _, w = volume_acceptance_profile(opens, highs, lows, closes, [0.0, 0.0], n_bins=60)
    assert w.sum() == pytest.approx(2.0)  # degrades to 1.0 per bar


def test_volume_profile_rejects_bad_body_ratio() -> None:
    with pytest.raises(ValueError):
        volume_acceptance_profile([1.0], [2.0], [0.0], [1.0], [1.0], n_bins=4, body_ratio=1.5)


def test_volume_profile_rejects_unknown_transform() -> None:
    with pytest.raises(ValueError):
        volume_acceptance_profile(
            [1.0], [2.0], [0.0], [1.0], [1.0], n_bins=4, vol_transform="cube"  # type: ignore[arg-type]
        )


def test_volume_profile_transforms_preserve_conservation() -> None:
    # Each transform must keep the window total at the bar count (per-bar weight
    # averages 1 after the post-transform normalisation), and stay scale-free.
    rng = np.random.default_rng(21)
    n = 50
    closes = list(100.0 + np.cumsum(rng.normal(0, 0.5, n)))
    opens = [closes[0]] + closes[:-1]
    highs = [max(o, c) + 0.4 for o, c in zip(opens, closes)]
    lows = [min(o, c) - 0.4 for o, c in zip(opens, closes)]
    vols = list(np.exp(rng.normal(2.0, 1.5, n)))  # heavy-tailed (log-normal)
    for tr in ("linear", "sqrt", "log"):
        _, w = volume_acceptance_profile(
            opens, highs, lows, closes, vols, n_bins=64, vol_transform=tr, vol_clip=None
        )
        assert w.sum() == pytest.approx(float(n)), f"{tr} broke conservation"


def test_volume_profile_transform_compression_ordering() -> None:
    # On a heavy-tailed volume window, log compresses more than sqrt compresses
    # more than linear: the share captured by the highest-volume bins shrinks.
    rng = np.random.default_rng(22)
    n = 200
    base = 100.0
    closes = list(base + rng.normal(0, 0.2, n))  # all bars in a tight band
    opens = list(closes)
    highs = [c + 0.1 for c in closes]
    lows = [c - 0.1 for c in closes]
    vols = list(np.exp(rng.normal(2.0, 1.8, n)))  # strong right tail
    shares = {}
    for tr in ("linear", "sqrt", "log"):
        _, w = volume_acceptance_profile(
            opens, highs, lows, closes, vols, n_bins=80, vol_transform=tr, vol_clip=None
        )
        top = np.sort(w)[-8:].sum()  # weight in the 8 busiest bins
        shares[tr] = top / w.sum()
    assert shares["linear"] > shares["sqrt"] > shares["log"]


def test_time_acceptance_half_ratio_matches_uniform_time_profile() -> None:
    # The clean-A/B property: body_ratio == 0.5 reproduces the plain uniform
    # time profile EXACTLY, so density_breakout_acc(0.5) == density_breakout.
    rng = np.random.default_rng(7)
    n = 120
    closes = list(100.0 + rng.normal(0, 1.0, n))
    opens = list(100.0 + rng.normal(0, 1.0, n))
    highs = [max(o, c) + abs(rng.normal(0, 0.5)) for o, c in zip(opens, closes)]
    lows = [min(o, c) - abs(rng.normal(0, 0.5)) for o, c in zip(opens, closes)]
    _, w_uniform = time_at_price_profile(highs, lows, n_bins=64)
    _, w_acc = time_acceptance_profile(opens, highs, lows, closes, n_bins=64, body_ratio=0.5)
    np.testing.assert_allclose(w_acc, w_uniform, rtol=1e-9, atol=1e-9)


def test_time_acceptance_each_bar_deposits_unit_weight() -> None:
    # No volume: every bar contributes total weight 1.0 regardless of body_ratio
    # or candle shape (conservation), so weights sum to the bar count.
    opens = [100.0, 101.0, 99.5]
    closes = [100.5, 100.0, 100.5]
    highs = [103.0, 101.2, 100.6]  # bar 0 has a long upper wick
    lows = [99.9, 97.0, 99.4]  # bar 1 has a long lower wick
    for br in (0.3, 0.5, 0.7, 0.9):
        _, w = time_acceptance_profile(opens, highs, lows, closes, n_bins=50, body_ratio=br)
        assert w.sum() == pytest.approx(3.0)


def test_time_acceptance_downweights_the_wick() -> None:
    # A single candle with a long upper hige: raising body_ratio moves density
    # OUT of the wick (rejected high) and INTO the body, vs the uniform profile.
    opens, closes = [100.0], [100.2]
    highs, lows = [105.0], [99.9]  # body ~[100,100.2], long upper wick to 105
    _, w_uniform = time_acceptance_profile(opens, highs, lows, closes, n_bins=50, body_ratio=0.5)
    _, w_body = time_acceptance_profile(opens, highs, lows, closes, n_bins=50, body_ratio=0.85)
    # Top 40% of bins (the wick region) must hold less weight under body weighting.
    hi_region = slice(30, 50)
    assert w_body[hi_region].sum() < w_uniform[hi_region].sum()


def test_find_walls_detects_two_separate_peaks() -> None:
    # A bimodal profile (two dense zones with a gap) must yield two walls, each
    # bracketing its own peak — this is what lets volume add walls time misses.
    centers = np.linspace(100.0, 110.0, 21)
    weights = np.ones(21) * 0.2
    weights[3] = 5.0  # peak near 101.5
    weights[15] = 6.0  # peak near 107.5
    walls = find_walls(centers, weights, prominence_k=1.0)
    assert len(walls) == 2
    assert walls[0][0] <= 101.5 <= walls[0][1]
    assert walls[1][0] <= 107.5 <= walls[1][1]
    assert walls[0][2] < walls[1][2]  # ascending by price


def test_find_walls_flat_profile_has_no_walls() -> None:
    centers = np.linspace(100.0, 110.0, 21)
    weights = np.ones(21)
    assert find_walls(centers, weights, prominence_k=1.0) == []


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


# --- density_breakout_vol sign (A/B sibling) -----------------------------------


def _vol_frame(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
) -> pd.DataFrame:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    idx = pd.DatetimeIndex(
        [start + timedelta(hours=i) for i in range(len(highs))], name="timestamp"
    )
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=idx,
    )


def test_breakout_vol_fires_long_on_close_above_top() -> None:
    # Same setup as the time-based sibling: consolidate in a band around 100,
    # then close out above the top edge. The volume profile must still fire.
    win = 30
    rng = np.random.default_rng(3)
    base_close = list(100.0 + rng.normal(0, 0.3, win))
    opens = list(base_close)
    highs = [c + 0.5 for c in base_close]
    lows = [c - 0.5 for c in base_close]
    vols = [1.0] * win
    opens += [100.2, 100.2]
    closes = base_close + [100.2, 103.0]
    highs = highs + [100.7, 103.5]
    lows = lows + [99.7, 100.4]
    vols += [1.0, 1.0]
    sign = DensityBreakoutVolSign(window=win, n_bins=40, coverage=0.70)
    fire = sign.last_fire(_vol_frame(opens, highs, lows, closes, vols))
    assert fire is not None
    assert fire.side is Side.LONG
    assert fire.ref_price is not None and fire.ref2_price is not None
    assert fire.ref2_price < fire.ref_price  # ref=top edge, ref2=bottom edge


def test_breakout_vol_detect_matches_last_fire_no_lookahead() -> None:
    # detect() over the full frame must agree with last_fire() on each prefix:
    # a fire at index t may only use bars <= t (the profile excludes bar t).
    win = 20
    rng = np.random.default_rng(7)
    n = 90
    closes = list(100.0 + np.cumsum(rng.normal(0, 0.4, n)))
    opens = [closes[0]] + closes[:-1]
    highs = [max(o, c) + 0.6 for o, c in zip(opens, closes)]
    lows = [min(o, c) - 0.6 for o, c in zip(opens, closes)]
    vols = list(1.0 + rng.uniform(0, 5, n))
    df = _vol_frame(opens, highs, lows, closes, vols)
    sign = DensityBreakoutVolSign(window=win, n_bins=30, max_band_pct=None)
    fires = {f.fired_at for f in sign.detect(df)}
    for t in range(len(df)):
        lf = sign.last_fire(df.iloc[: t + 1])
        if lf is not None:
            assert lf.fired_at in fires, f"prefix fire at {lf.fired_at} missing in detect"
