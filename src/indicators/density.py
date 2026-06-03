"""Time-at-price density profile and market-profile value area.

Builds a *time-at-price* histogram over a window of OHLC bars: each bar
contributes a total weight of ``1.0``, spread across the price bins its
``[low, high]`` range overlaps, proportional to the overlap. Equal per-bar
weight means a wide-range bar does not dominate the profile merely by being
wide — it is "time spent at each price", not "range covered".

The :func:`value_area` routine reduces a profile to a single dense band using
the standard market-profile construction: start at the Point-of-Control (the
busiest bin) and expand outward, always toward the heavier adjacent side, until
a target fraction (default 70%) of the total time is enclosed. The enclosed
price interval is the "dense band" the ``density_band`` sign trades around.

These are pure functions (numpy only, no pandas / no DB) so the math is
unit-testable in isolation.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def time_at_price_profile(
    highs: NDArray[np.float64] | list[float],
    lows: NDArray[np.float64] | list[float],
    n_bins: int,
    lo: float | None = None,
    hi: float | None = None,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Build a time-at-price histogram over a set of bars.

    Each bar contributes total weight ``1.0``, distributed across the bins its
    ``[low, high]`` span overlaps in proportion to the overlap length. A
    zero-range bar (``high == low``) deposits its full weight in the single bin
    containing that price.

    Args:
        highs: Per-bar high prices.
        lows: Per-bar low prices.
        n_bins: Number of equal-width price bins.
        lo: Lower price bound of the histogram. Defaults to ``min(lows)``.
        hi: Upper price bound of the histogram. Defaults to ``max(highs)``.

    Returns:
        ``(centers, weights)`` — bin centre prices and the time weight in each
        bin (both length ``n_bins``). ``weights`` sums to the bar count when the
        bounds enclose every bar.

    Raises:
        ValueError: If ``n_bins < 1`` or the inputs are empty / mismatched.
    """
    if n_bins < 1:
        raise ValueError("n_bins must be >= 1")
    h = np.asarray(highs, dtype=np.float64)
    low_arr = np.asarray(lows, dtype=np.float64)
    if h.shape != low_arr.shape:
        raise ValueError("highs and lows must have the same length")
    if h.size == 0:
        raise ValueError("highs/lows must be non-empty")

    lo_b = float(low_arr.min()) if lo is None else float(lo)
    hi_b = float(h.max()) if hi is None else float(hi)
    if hi_b <= lo_b:
        # Degenerate (flat) window: a single price. One bin, all the weight.
        centers = np.full(n_bins, lo_b, dtype=np.float64)
        weights = np.zeros(n_bins, dtype=np.float64)
        weights[n_bins // 2] = float(h.size)
        return centers, weights

    edges = np.linspace(lo_b, hi_b, n_bins + 1)
    left = edges[:-1]
    right = edges[1:]
    centers = 0.5 * (left + right)

    # Clip each bar's range to the global bounds so weight is conserved.
    bar_lo = np.clip(low_arr, lo_b, hi_b)
    bar_hi = np.clip(h, lo_b, hi_b)
    span = bar_hi - bar_lo  # (n_bars,)

    # overlap[i, j] = overlap of bar i's range with bin j.
    overlap = np.clip(
        np.minimum(bar_hi[:, None], right[None, :])
        - np.maximum(bar_lo[:, None], left[None, :]),
        0.0,
        None,
    )

    weights = np.zeros(n_bins, dtype=np.float64)

    ranged = span > 0.0
    if ranged.any():
        contrib = overlap[ranged] / span[ranged][:, None]
        weights += contrib.sum(axis=0)

    # Zero-range bars: deposit full unit weight in the containing bin.
    if (~ranged).any():
        flat_prices = bar_lo[~ranged]
        idx = np.clip(
            np.searchsorted(edges, flat_prices, side="right") - 1, 0, n_bins - 1
        )
        np.add.at(weights, idx, 1.0)

    return centers, weights


def relative_dense_band(
    centers: NDArray[np.float64],
    weights: NDArray[np.float64],
    sigma_r: float = 1.0,
    min_poc_ratio: float = 2.0,
) -> tuple[float, float] | None:
    """Dense band defined *relative* to the period's own density distribution.

    Instead of an absolute width filter, a price level is "dense" when its
    time-weight stands out from the window's distribution: ``weight >= mean +
    sigma_r * std``. The band is the contiguous run of such bins around the
    Point-of-Control (busiest bin), so it adapts to the regime — it appears in any
    period with a real concentration, regardless of the absolute price range, and
    a higher ``sigma_r`` demands a sharper peak (narrower band, fewer fires).

    A scale-free backstop rejects structureless periods: the POC must hold at
    least ``min_poc_ratio`` times the uniform-expectation weight
    (``total / n_bins``); a roughly uniform histogram (no real dense) fails it.

    Args:
        centers: Bin centre prices (length ``n``), ascending.
        weights: Time weight per bin (length ``n``).
        sigma_r: Threshold in standard deviations above the mean bin weight.
        min_poc_ratio: Minimum POC weight as a multiple of the uniform weight.

    Returns:
        ``(band_lo, band_hi)`` bin-centre bounds of the dense band, or ``None`` if
        the period has no real concentration (backstop) or a degenerate band.

    Raises:
        ValueError: On length mismatch, empty input, or non-positive ``sigma_r``.
    """
    if centers.shape != weights.shape:
        raise ValueError("centers and weights must have the same length")
    n = centers.size
    if n == 0:
        raise ValueError("profile must be non-empty")
    if sigma_r <= 0.0:
        raise ValueError("sigma_r must be > 0")

    total = float(weights.sum())
    if total <= 0.0:
        return None
    poc_i = int(np.argmax(weights))
    if float(weights[poc_i]) < min_poc_ratio * (total / n):
        return None  # too flat / no real dense zone

    thr = float(weights.mean()) + sigma_r * float(weights.std())
    lo_i = hi_i = poc_i
    while lo_i - 1 >= 0 and float(weights[lo_i - 1]) >= thr:
        lo_i -= 1
    while hi_i + 1 < n and float(weights[hi_i + 1]) >= thr:
        hi_i += 1
    if hi_i <= lo_i:
        return None  # single-bin spike: too tight to trade as a box
    return float(centers[lo_i]), float(centers[hi_i])


def value_area(
    centers: NDArray[np.float64],
    weights: NDArray[np.float64],
    coverage: float = 0.70,
) -> tuple[float, float, float]:
    """Reduce a profile to its dense band (market-profile value area).

    Starts at the Point-of-Control (busiest bin) and expands outward, each step
    toward the heavier adjacent side, until ``coverage`` of the total weight is
    enclosed.

    Args:
        centers: Bin centre prices (length ``n``), ascending.
        weights: Time weight per bin (length ``n``).
        coverage: Target fraction of total weight to enclose, in ``(0, 1]``.

    Returns:
        ``(poc_price, band_lo, band_hi)`` — the Point-of-Control price and the
        inclusive price bounds of the dense band (bin-centre based).

    Raises:
        ValueError: On length mismatch, empty input, or out-of-range coverage.
    """
    if centers.shape != weights.shape:
        raise ValueError("centers and weights must have the same length")
    n = centers.size
    if n == 0:
        raise ValueError("profile must be non-empty")
    if not 0.0 < coverage <= 1.0:
        raise ValueError("coverage must be in (0, 1]")

    total = float(weights.sum())
    poc_i = int(np.argmax(weights))
    if total <= 0.0:
        c = float(centers[poc_i])
        return c, c, c

    target = coverage * total
    lo_i = hi_i = poc_i
    acc = float(weights[poc_i])
    while acc < target and (lo_i > 0 or hi_i < n - 1):
        below = float(weights[lo_i - 1]) if lo_i > 0 else -np.inf
        above = float(weights[hi_i + 1]) if hi_i < n - 1 else -np.inf
        if above >= below:
            hi_i += 1
            acc += float(weights[hi_i])
        else:
            lo_i -= 1
            acc += float(weights[lo_i])

    return float(centers[poc_i]), float(centers[lo_i]), float(centers[hi_i])
