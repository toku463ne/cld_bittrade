"""Harness-level regime gate — a signal-agnostic entry filter wrapper.

``RegimeGatedStrategy`` wraps *any* inner strategy and suppresses its entries
when the current bar's volatility / expansion regime is outside a productive
percentile band. It adds NO entry logic and re-picks NO direction — it only
decides *when* (in what regime) the inner strategy is allowed to trade. This is
the harness-level lever the ``entry_context_probe`` found: pooled over 7k
heterogeneous entries, the upper-middle ATR / realized-range percentile buckets
carried positive expectancy in BOTH the IS and OOS splits, while the dead-quiet
(and, for range, blown-out) buckets bled. Because the gate is a property of market
context, not of the signal, the same wrapper works for every strategy.

Regime is measured exactly as the probe did, causally: ATR(14) and trailing
``RR_LOOKBACK``-bar realized range, each ranked against a trailing
``RANK_WINDOW``-bar window (via rolling quantiles), and the entry is kept only when
the rank sits inside ``[min, max]`` for each enabled feature. ``min=0, max=1``
disables a feature. The default concrete strategy keeps the ATR upper half
(rank >= 0.5), the single cleanest robust cell.

Whether the per-trade quality lift survives the trade-count it costs is the
benchmark question (run_cycle the gated vs ungated strategy), not an assumption —
the same trap that sank the clear-air filter.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from src.core.types import Bar, ExitConfig, Signal
from src.indicators import atr
from src.strategy.base import Strategy
from src.strategy.density_breakout import DensityBreakoutStrategy
from src.strategy.density_multi_breakout import DensityMultiBreakoutStrategy

RR_LOOKBACK = 24
RANK_WINDOW = 500


class RegimeGatedStrategy(Strategy):
    """Wrap an inner strategy; pass its entries only inside a regime band."""

    def __init__(
        self,
        inner: Strategy,
        *,
        atr_rank_min: float = 0.5,
        atr_rank_max: float = 1.0,
        rr_rank_min: float = 0.0,
        rr_rank_max: float = 1.0,
        rank_window: int = RANK_WINDOW,
    ) -> None:
        """Initialise the gate around ``inner``.

        Args:
            inner: The strategy whose entries are gated. Its exits, sizing,
                ``max_slots`` and signals are used unchanged.
            atr_rank_min: Keep entries only when the ATR(14) trailing percentile
                rank is >= this. ``0.0`` removes the lower bound.
            atr_rank_max: ... and <= this. ``1.0`` removes the upper bound.
            rr_rank_min: Same for the realized-range percentile (lower bound).
            rr_rank_max: Same for the realized-range percentile (upper bound).
            rank_window: Trailing bars used for the percentile ranks.

        Raises:
            ValueError: On a malformed percentile band or window.
        """
        super().__init__()
        for lo, hi in ((atr_rank_min, atr_rank_max), (rr_rank_min, rr_rank_max)):
            if not (0.0 <= lo <= hi <= 1.0):
                raise ValueError("rank bands must satisfy 0 <= min <= max <= 1")
        if rank_window < 2:
            raise ValueError("rank_window must be >= 2")
        self._inner = inner
        self._atr_min, self._atr_max = atr_rank_min, atr_rank_max
        self._rr_min, self._rr_max = rr_rank_min, rr_rank_max
        self._rank_window = rank_window
        self.required_indicators = list(inner.required_indicators)
        self.max_slots = inner.max_slots
        # The gate needs a full ranking window; the inner needs its own warmup.
        self.warmup = max(inner.warmup, rank_window)
        self.max_buffer = max(inner.max_buffer, rank_window + RR_LOOKBACK + 2)

    # --- regime mask ---------------------------------------------------------
    def _band_pass(self, s: pd.Series, lo: float, hi: float) -> pd.Series:
        """Boolean Series: is each value within the ``[lo, hi]`` trailing-rank band?"""
        if lo <= 0.0 and hi >= 1.0:
            return pd.Series(True, index=s.index)
        roll = s.rolling(self._rank_window, min_periods=self._rank_window // 2)
        lo_thr = roll.quantile(lo) if lo > 0.0 else None
        hi_thr = roll.quantile(hi) if hi < 1.0 else None
        ok = pd.Series(True, index=s.index)
        if lo_thr is not None:
            ok &= s >= lo_thr
        if hi_thr is not None:
            ok &= s <= hi_thr
        # Where the rank could not be computed (warmup), do not trade.
        return ok.fillna(False)

    def _regime_mask(self, df: pd.DataFrame) -> np.ndarray:
        """Per-bar boolean: is the bar inside the productive regime band?"""
        atr_s = atr(df, 14)
        rr_s = (
            df["high"].rolling(RR_LOOKBACK).max() - df["low"].rolling(RR_LOOKBACK).min()
        ) / df["close"]
        ok = self._band_pass(atr_s, self._atr_min, self._atr_max) & self._band_pass(
            rr_s, self._rr_min, self._rr_max
        )
        return ok.to_numpy(dtype=bool)

    # --- Strategy interface --------------------------------------------------
    def reset(self) -> None:  # noqa: D102 (override)
        super().reset()
        self._inner.reset()

    def precompute(self, bars: list[Bar]) -> dict[datetime, Signal] | None:  # noqa: D102
        if not bars:
            return {}
        df = pd.DataFrame(
            {
                "open": [b.open for b in bars],
                "high": [b.high for b in bars],
                "low": [b.low for b in bars],
                "close": [b.close for b in bars],
                "volume": [b.volume for b in bars],
            },
            index=pd.DatetimeIndex([b.timestamp for b in bars], name="timestamp"),
        )
        mask = self._regime_mask(df)
        inner_map = self._inner.precompute(bars)
        if inner_map is not None:
            pos = {ts: i for i, ts in enumerate(df.index)}
            return {
                ts: sig
                for ts, sig in inner_map.items()
                if mask[pos[pd.Timestamp(ts)]]
            }
        # Inner uses the per-bar path: drive it once over the full series.
        self._inner.reset()
        out: dict[datetime, Signal] = {}
        for i, bar in enumerate(bars):
            sig = self._inner.push(bar)
            if sig is not None and mask[i]:
                out[bar.timestamp] = sig
        return out

    def on_bar(self, bar: Bar) -> Signal | None:  # noqa: D102 (inherited)
        # Backtests go through precompute; this keeps the live/per-bar path honest.
        self._bars = self._bars[-self.max_buffer :]
        sig = self._inner.push(bar)
        if sig is None:
            return None
        mask = self._regime_mask(self.buffer_frame())
        return sig if (mask.size and bool(mask[-1])) else None

    def push(self, bar: Bar) -> Signal | None:  # noqa: D102 (override)
        # Maintain our own buffer (for the regime window) and delegate gating to
        # on_bar; warmup is enforced here as in the base class.
        self._bars.append(bar)
        if len(self._bars) > self.max_buffer:
            self._bars = self._bars[-self.max_buffer :]
        if len(self._bars) < self.warmup:
            self._inner.push(bar)  # keep inner buffer warm even pre-warmup
            return None
        return self.on_bar(bar)

    def get_exit_rules(self) -> ExitConfig:  # noqa: D102 (inherited)
        return self._inner.get_exit_rules()


class DensityBreakoutVolgateStrategy(RegimeGatedStrategy):
    """density_breakout, gated to the upper-half ATR volatility regime."""

    name = "density_breakout_volgate"
    description = (
        "density_breakout entries kept only when ATR(14) is in the upper half of "
        "its trailing 500-bar percentile (the robust IS+OOS regime cell). "
        "Harness-level signal-agnostic gate; judge net of the frequency it costs."
    )

    def __init__(self) -> None:
        """Wrap the default density_breakout in the ATR upper-half regime band."""
        super().__init__(
            DensityBreakoutStrategy(),
            atr_rank_min=0.5,
            atr_rank_max=1.0,
        )


class DensityMultiVolgateStrategy(RegimeGatedStrategy):
    """density_multi_breakout (the high-volume multi-position funnel), ATR-gated."""

    name = "density_multi_volgate"
    description = (
        "density_multi_breakout entries kept only in the upper-half ATR volatility "
        "regime. Tests the harness regime gate on the project's high-trade-count "
        "edge; judged by equity Sharpe net of the frequency it costs."
    )

    def __init__(self) -> None:
        """Wrap density_multi_breakout in the ATR upper-half regime band."""
        super().__init__(
            DensityMultiBreakoutStrategy(),
            atr_rank_min=0.5,
            atr_rank_max=1.0,
        )
