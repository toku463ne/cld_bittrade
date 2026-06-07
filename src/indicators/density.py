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

from typing import Literal

import numpy as np
from numpy.typing import NDArray

VolTransform = Literal["linear", "sqrt", "log"]
"""Concave compression applied to volume before the per-window mean-normalisation.

``linear`` = raw volume (heavy-tailed; pair with ``vol_clip``). ``sqrt`` = a mild
compression that tames the tail while keeping volume informative (recommended).
``log`` = ``log1p``; compresses so hard it nearly erases volume differences,
collapsing toward the time-at-price profile — kept only for A/B completeness.
"""


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


def _body_wick_profile(
    norm: NDArray[np.float64],
    o: NDArray[np.float64],
    h: NDArray[np.float64],
    low_arr: NDArray[np.float64],
    c: NDArray[np.float64],
    n_bins: int,
    body_ratio: float,
    lo: float | None,
    hi: float | None,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Distribute each bar's weight ``norm[i]`` across price bins, body/wick tilted.

    Shared core of :func:`volume_acceptance_profile` (``norm`` = mean-normalised
    volume) and :func:`time_acceptance_profile` (``norm`` = ones). The candle body
    span (open->close) is weighted ``body_ratio`` and the wick span
    ``1 - body_ratio``; the per-bar normaliser is that same body/wick-weighted
    height, so each bar deposits exactly ``norm[i]`` regardless of candle shape —
    magnitude and shape are never confounded. ``body_ratio == 0.5`` recovers
    uniform-within-bar weighting (the plain :func:`time_at_price_profile` shape).

    Args:
        norm: Per-bar total weight to deposit (length = n_bars).
        o, h, low_arr, c: Per-bar open/high/low/close (numpy, same length).
        n_bins: Number of equal-width bins.
        body_ratio: Body-vs-wick weight in ``[0, 1]``.
        lo: Lower price bound (``None`` -> ``min(low)``).
        hi: Upper price bound (``None`` -> ``max(high)``).

    Returns:
        ``(centers, weights)`` — bin centres and the deposited weight per bin.
    """
    lo_b = float(low_arr.min()) if lo is None else float(lo)
    hi_b = float(h.max()) if hi is None else float(hi)
    if hi_b <= lo_b:
        # Degenerate (flat) window: a single price holds all the weight.
        centers = np.full(n_bins, lo_b, dtype=np.float64)
        weights = np.zeros(n_bins, dtype=np.float64)
        weights[n_bins // 2] = float(norm.sum())
        return centers, weights

    edges = np.linspace(lo_b, hi_b, n_bins + 1)
    left = edges[:-1]
    right = edges[1:]
    centers = 0.5 * (left + right)

    # Clip every span to the global bounds so weight is conserved exactly.
    bar_lo = np.clip(low_arr, lo_b, hi_b)
    bar_hi = np.clip(h, lo_b, hi_b)
    body_bot = np.clip(np.minimum(o, c), lo_b, hi_b)
    body_top = np.clip(np.maximum(o, c), lo_b, hi_b)

    full_overlap = np.clip(
        np.minimum(bar_hi[:, None], right[None, :])
        - np.maximum(bar_lo[:, None], left[None, :]),
        0.0,
        None,
    )
    body_overlap = np.clip(
        np.minimum(body_top[:, None], right[None, :])
        - np.maximum(body_bot[:, None], left[None, :]),
        0.0,
        None,
    )
    wick_overlap = np.clip(full_overlap - body_overlap, 0.0, None)

    # Per-bar normaliser = the same body/wick-weighted height the numerator sums
    # to, so each bar deposits exactly norm[i] (sum_j numer_j / denom == 1).
    body_h = body_top - body_bot
    wick_h = np.clip((bar_hi - bar_lo) - body_h, 0.0, None)
    denom = body_h * body_ratio + wick_h * (1.0 - body_ratio)
    numer = body_overlap * body_ratio + wick_overlap * (1.0 - body_ratio)

    weights = np.zeros(n_bins, dtype=np.float64)
    good = denom > 0.0
    if good.any():
        contrib = (norm[good][:, None] * numer[good]) / denom[good][:, None]
        weights += contrib.sum(axis=0)

    # Degenerate bars (denom == 0: flat high == low, or body_ratio at an extreme
    # zeroing the only non-empty span) deposit their full weight at the close.
    if (~good).any():
        flat_c = np.clip(c[~good], lo_b, hi_b)
        idx = np.clip(np.searchsorted(edges, flat_c, side="right") - 1, 0, n_bins - 1)
        np.add.at(weights, idx, norm[~good])

    return centers, weights


def time_acceptance_profile(
    opens: NDArray[np.float64] | list[float],
    highs: NDArray[np.float64] | list[float],
    lows: NDArray[np.float64] | list[float],
    closes: NDArray[np.float64] | list[float],
    n_bins: int,
    body_ratio: float = 0.7,
    lo: float | None = None,
    hi: float | None = None,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Build a *time-at-price* profile with body/wick acceptance weighting.

    Identical to :func:`time_at_price_profile` (each bar deposits total weight
    ``1.0``, **no** volume) except the unit weight is tilted *within* the bar
    toward the candle **body** (acceptance) and away from the **wicks**
    (rejection) by ``body_ratio``. This isolates the body/wick (hige/marubozu)
    effect as a single knob vs the uniform time profile:

    - ``body_ratio == 0.5`` reproduces :func:`time_at_price_profile` exactly
      (uniform across ``[low, high]``).
    - ``body_ratio > 0.5`` down-weights the wicks — a long upper/lower hige
      deposits less density at the rejected extreme; a marubozu (no wick) keeps
      all of its weight in the body.

    Args:
        opens: Per-bar open prices.
        highs: Per-bar high prices.
        lows: Per-bar low prices.
        closes: Per-bar close prices.
        n_bins: Number of equal-width price bins.
        body_ratio: Weight on the body span vs the wicks, in ``[0, 1]``.
        lo: Lower price bound. Defaults to ``min(lows)``.
        hi: Upper price bound. Defaults to ``max(highs)``.

    Returns:
        ``(centers, weights)`` — bin centres and the time-acceptance weight per
        bin. ``weights`` sums to the bar count when the bounds enclose every bar.

    Raises:
        ValueError: On bad ``n_bins`` / ``body_ratio``, empty or mismatched inputs.
    """
    if n_bins < 1:
        raise ValueError("n_bins must be >= 1")
    if not 0.0 <= body_ratio <= 1.0:
        raise ValueError("body_ratio must be in [0, 1]")
    o = np.asarray(opens, dtype=np.float64)
    h = np.asarray(highs, dtype=np.float64)
    low_arr = np.asarray(lows, dtype=np.float64)
    c = np.asarray(closes, dtype=np.float64)
    if not (o.shape == h.shape == low_arr.shape == c.shape):
        raise ValueError("opens/highs/lows/closes must share a length")
    if h.size == 0:
        raise ValueError("inputs must be non-empty")
    norm = np.ones(h.size, dtype=np.float64)
    return _body_wick_profile(norm, o, h, low_arr, c, n_bins, body_ratio, lo, hi)


def volume_acceptance_profile(
    opens: NDArray[np.float64] | list[float],
    highs: NDArray[np.float64] | list[float],
    lows: NDArray[np.float64] | list[float],
    closes: NDArray[np.float64] | list[float],
    volumes: NDArray[np.float64] | list[float],
    n_bins: int,
    body_ratio: float = 0.7,
    lo: float | None = None,
    hi: float | None = None,
    vol_clip: float | None = None,
    vol_transform: VolTransform = "linear",
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Build a *volume-at-price* profile with body/wick acceptance weighting.

    Unlike :func:`time_at_price_profile` (each bar = 1.0 of "time", spread
    uniformly over its range), this is a volume profile that also treats the
    candle **body** (open->close) as *acceptance* and the **wicks** as
    *rejection*:

    - Each bar deposits a total weight of ``norm_vol`` = the (optionally
      transformed) volume divided by the window mean of the same — so the window
      sums to the bar count when volume is flat, keeping the :func:`value_area`
      coverage logic unchanged. ``vol_transform`` applies a concave compression
      first (volume is heavy-tailed), and ``vol_clip`` caps the result so a single
      outsized print cannot define the whole band. Both compose; normalisation is
      always applied *after* the transform so per-bar conservation still holds.
    - That weight is distributed *within* the bar toward the body: the body span
      is weighted ``body_ratio`` and the wick span ``1 - body_ratio``. Crucially
      the per-bar total stays ``norm_vol`` regardless of candle shape — the
      normaliser is the body/wick-weighted height, not the raw ``high - low`` —
      so magnitude (volume) and shape (body/wick) are never confounded.

    Args:
        opens: Per-bar open prices.
        highs: Per-bar high prices.
        lows: Per-bar low prices.
        closes: Per-bar close prices.
        volumes: Per-bar traded volume (non-negative).
        n_bins: Number of equal-width price bins.
        body_ratio: Weight on the body span vs the wicks, in ``[0, 1]``. ``0.5``
            recovers uniform-within-bar weighting (volume profile, no acceptance
            tilt); ``> 0.5`` favours the body (market-profile "acceptance").
        lo: Lower price bound. Defaults to ``min(lows)``.
        hi: Upper price bound. Defaults to ``max(highs)``.
        vol_clip: If set, clip ``norm_vol`` to at most this multiple of the mean
            (e.g. ``8.0``). ``None`` disables clipping.
        vol_transform: Concave compression applied to volume before
            normalisation — see :data:`VolTransform`. ``"sqrt"`` is the
            recommended tail-tamer; ``"log"`` over-compresses.

    Returns:
        ``(centers, weights)`` — bin centre prices and the volume-acceptance
        weight per bin. ``weights`` sums to ``sum(norm_vol)`` (= bar count when
        volume is flat) whenever the bounds enclose every bar.

    Raises:
        ValueError: On bad ``n_bins`` / ``body_ratio`` / ``vol_clip``, empty or
            mismatched inputs.
    """
    if n_bins < 1:
        raise ValueError("n_bins must be >= 1")
    if not 0.0 <= body_ratio <= 1.0:
        raise ValueError("body_ratio must be in [0, 1]")
    if vol_clip is not None and vol_clip <= 0.0:
        raise ValueError("vol_clip must be > 0 when set")

    o = np.asarray(opens, dtype=np.float64)
    h = np.asarray(highs, dtype=np.float64)
    low_arr = np.asarray(lows, dtype=np.float64)
    c = np.asarray(closes, dtype=np.float64)
    v = np.asarray(volumes, dtype=np.float64)
    if not (o.shape == h.shape == low_arr.shape == c.shape == v.shape):
        raise ValueError("opens/highs/lows/closes/volumes must share a length")
    if h.size == 0:
        raise ValueError("inputs must be non-empty")

    # Concave compression first (volume is heavy-tailed), then mean-normalise so
    # each bar's total contribution is norm_vol. Normalising *after* the transform
    # keeps the per-bar conservation property and makes sqrt/log scale-invariant.
    vt = np.clip(v, 0.0, None)
    if vol_transform == "sqrt":
        vt = np.sqrt(vt)
    elif vol_transform == "log":
        vt = np.log1p(vt)
    elif vol_transform != "linear":
        raise ValueError(f"unknown vol_transform {vol_transform!r}")
    # If volume is absent/degenerate (mean <= 0), fall back to equal weight so the
    # profile degrades gracefully to a body/wick-shaped time profile, not NaNs.
    mean_vt = float(vt.mean())
    norm = np.ones_like(vt) if mean_vt <= 0.0 else vt / mean_vt
    if vol_clip is not None:
        norm = np.minimum(norm, vol_clip)

    return _body_wick_profile(norm, o, h, low_arr, c, n_bins, body_ratio, lo, hi)


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


def find_walls(
    centers: NDArray[np.float64],
    weights: NDArray[np.float64],
    *,
    prominence_k: float = 1.0,
) -> list[tuple[float, float, float]]:
    """Find the discrete high-density walls (peaks) in a price profile.

    Unlike :func:`value_area` (one contiguous band around the single POC), this
    returns *every* dense zone: each maximal run of contiguous bins whose weight
    exceeds ``mean + prominence_k * std`` of the profile is one wall. This is what
    lets a *volume* profile contribute walls a *time* profile misses — a level a
    lot of size traded at, even briefly, shows up as its own peak.

    Args:
        centers: Bin centre prices (length ``n``), ascending and equally spaced.
        weights: Weight per bin (length ``n``).
        prominence_k: Threshold in standard deviations above the mean a bin must
            clear to belong to a wall. Higher = fewer, stronger walls.

    Returns:
        One ``(lo, hi, peak_price)`` per wall — the price bounds of the run
        (extended half a bin past the outer centres) and the price of its
        heaviest bin — ascending by price. Empty when the profile is flat or
        nothing clears the threshold.
    """
    w = np.asarray(weights, dtype=np.float64)
    c = np.asarray(centers, dtype=np.float64)
    if w.size == 0 or w.size != c.size:
        return []
    half = 0.5 * float(c[1] - c[0]) if c.size >= 2 else 0.0
    thr = float(w.mean() + prominence_k * w.std())
    above = w > thr
    walls: list[tuple[float, float, float]] = []
    i = 0
    n = w.size
    while i < n:
        if not above[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and above[j + 1]:
            j += 1
        peak_local = int(np.argmax(w[i : j + 1]))
        peak_price = float(c[i + peak_local])
        walls.append((float(c[i] - half), float(c[j] + half), peak_price))
        i = j + 1
    return walls
