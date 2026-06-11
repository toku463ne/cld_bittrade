"""Strategy: combo_dp_ver — density_pullback + vol_expansion_ride on one shared book.

A portfolio composition, not a new edge: merges the signal streams of the two
shipped strategies into a single ``max_slots=12`` book — the same peak-capital
budget as ``density_pullback`` alone, which historically peaks at 10 concurrent
positions while ``vol_expansion_ride`` peaks at 4; combined they peak at 11 with
**zero** slot contention over the full backtest, so the shared book equals the
sum of the separate books at no extra peak capital.

Mechanically exact: both components use the identical inherited ride-exit
machinery (the ``RandomHedgeStrategy.dynamic_exit`` ratchet with
``recalc_bars=48``; each position's trail band derives from its own signal's
``exit_config``), so the merged book reproduces each component's exits
bar-for-bar. No parameter is tuned here — it composes two already-shipped
configs, which is what keeps the selection risk minimal.

Why it works (see ``docs/strategy/combo_dp_ver.md``): the components' weak
walk-forward folds are complementary (dp's 2022-bear fold is ver's best regime;
ver's 2023-bull fold is covered by dp), correlation is low (cDP +0.10), and the
combined book lifts quarterly consistency to 94% (vs 80/82% alone, B&H 62%).
"""

from __future__ import annotations

from datetime import datetime

from src.core.types import Bar, Signal
from src.strategy.base import Strategy
from src.strategy.density_pullback import DensityPullbackStrategy
from src.strategy.random_hedge import RandomHedgeStrategy
from src.strategy.vol_expansion_ride import VolExpansionRideStrategy


class ComboDpVerStrategy(RandomHedgeStrategy):
    """density_pullback + vol_expansion_ride signal streams, one 12-slot book."""

    name = "combo_dp_ver"
    description = (
        "Shared 12-slot book running density_pullback + vol_expansion_ride "
        "together (complementary regimes, zero historical slot contention); "
        "identical per-position ride exits as each component alone."
    )
    max_slots = 12

    def __init__(self, *, max_slots: int = 12) -> None:
        """Initialise.

        Args:
            max_slots: Shared concurrency cap across both components (peak
                exposure = ``max_slots × per-slot lot``). The historical combined
                peak is 11, so the default 12 keeps density_pullback's existing
                live budget guarantee.
        """
        # The shared exit framework: both components run the inherited ratchet at
        # recalc_bars=48, so one wrapper-level configuration reproduces both.
        super().__init__(recalc_bars=48)
        self.max_slots = max_slots
        self._dp = DensityPullbackStrategy()
        self._ver = VolExpansionRideStrategy()

    @property
    def components(self) -> list[Strategy]:
        """The two merged signal sources, for per-source attribution/colouring."""
        return [self._dp, self._ver]

    def precompute_multi(self, bars: list[Bar]) -> dict[datetime, list[Signal]] | None:  # noqa: D102
        out: dict[datetime, list[Signal]] = {}
        for sub in (self._dp, self._ver):
            sub.reset()
            for ts, sigs in (sub.precompute_multi(bars) or {}).items():
                out.setdefault(ts, []).extend(sigs)
        return out
