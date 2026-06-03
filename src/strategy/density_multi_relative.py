"""Strategy: density_multi_relative (EXPERIMENTAL / rejected variant).

A variant of :class:`~src.strategy.density_multi_breakout.DensityMultiBreakoutStrategy`
that swaps the absolute tight-box filter for a **regime-relative** dense band:
the contiguous run of bins whose time-weight exceeds ``mean + sigma_r × std``
around the Point-of-Control, with a scale-free backstop (POC ≥ ``min_poc_ratio ×``
the uniform weight) — see :func:`src.indicators.density.relative_dense_band`. The
absolute ``max_band_pct`` is kept only as a *loose* safety cap (default 10%).

**This variant is REJECTED — registered only for UI inspection.** It produces ~3×
the entries but is a regime artifact: net IS equity Sharpe goes *negative* while
OOS is large-positive (all from the single recent-decline fold); per-fold it is
positive in only 1 of 6 folds. It demonstrates that the absolute tight-box filter
is a quality gate, not arbitrary (the relative band floods in wide-range zones that
chop). See `src/backtest/analysis/density_relative_probe.py` and
`src/backtest/benchmark.md`. Do not trade.
"""

from __future__ import annotations

import numpy as np

from src.indicators.density import relative_dense_band, time_at_price_profile
from src.strategy.density_multi_breakout import DensityMultiBreakoutStrategy


class DensityMultiRelativeStrategy(DensityMultiBreakoutStrategy):
    """Relative-density band variant of density_multi_breakout (experimental)."""

    name = "density_multi_relative"
    description = (
        "EXPERIMENTAL/rejected: density_multi_breakout with a regime-RELATIVE dense "
        "band (bins > mean+R·σ around the POC) instead of the absolute tight-box "
        "filter. ~3× entries but a regime artifact (IS-negative/OOS-positive); kept "
        "for UI inspection only — do not trade."
    )

    def __init__(
        self,
        sigma_r: float = 1.5,
        min_poc_ratio: float = 3.0,
        max_band_pct: float = 0.10,
        **kwargs: float,
    ) -> None:
        """Initialise the relative variant.

        Args:
            sigma_r: Dense threshold in std-devs above the mean bin weight.
            min_poc_ratio: POC weight floor as a multiple of the uniform weight.
            max_band_pct: *Loose* absolute width cap (a safety net, not the gate).
            **kwargs: Forwarded to ``DensityMultiBreakoutStrategy`` (window, slots,
                target_min_dist_frac, etc.).
        """
        super().__init__(max_band_pct=max_band_pct, **kwargs)  # type: ignore[arg-type]
        if sigma_r <= 0.0:
            raise ValueError("sigma_r must be > 0")
        self.sigma_r = sigma_r
        self.min_poc_ratio = min_poc_ratio

    def _compute_bands(
        self, highs: list[float], lows: list[float]
    ) -> tuple[np.ndarray, np.ndarray]:  # noqa: D102 (override)
        n = len(highs)
        bl = np.full(n, np.nan)
        bh = np.full(n, np.nan)
        for t in range(self.window, n):
            centers, weights = time_at_price_profile(
                highs[t - self.window : t], lows[t - self.window : t], self.n_bins
            )
            band = relative_dense_band(centers, weights, self.sigma_r, self.min_poc_ratio)
            if band is not None:
                bl[t], bh[t] = band
        return bl, bh
