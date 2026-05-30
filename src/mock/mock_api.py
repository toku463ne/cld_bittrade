"""Mock of the bitFlyer Lightning REST API.

Reproduces the response schema of the endpoints we consume:

- ``GET /v1/getticker``     -> :meth:`MockBitflyerAPI.get_ticker`
- ``GET /v1/getboard``      -> :meth:`MockBitflyerAPI.get_board`
- ``GET /v1/getexecutions`` -> :meth:`MockBitflyerAPI.get_executions`

The payload field names match the real API exactly so that downstream parsing
code is identical in mock and live modes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.mock.synthetic import SyntheticTick, generate_ticks

_ISO = "%Y-%m-%dT%H:%M:%S.%f"


def _fmt(ts: datetime) -> str:
    """Format a UTC datetime like bitFlyer (e.g. ``2026-01-01T00:00:00.000``)."""
    return ts.astimezone(timezone.utc).strftime(_ISO)[:-3]


class MockBitflyerAPI:
    """In-memory stand-in for the bitFlyer REST client.

    Backed by a deterministic synthetic tick stream so it works with no recorded
    data. Construct once and reuse; ticks are materialised lazily on first use.
    """

    def __init__(
        self,
        product_code: str = "FX_BTC_JPY",
        *,
        n_ticks: int = 20_000,
        seed: int = 42,
    ) -> None:
        """Initialise the mock.

        Args:
            product_code: Product to serve (only ``FX_BTC_JPY`` is meaningful).
            n_ticks: Size of the synthetic tick buffer.
            seed: RNG seed for reproducibility.
        """
        self.product_code = product_code
        self._ticks: list[SyntheticTick] = list(
            generate_ticks(count=n_ticks, seed=seed)
        )

    @property
    def ticks(self) -> list[SyntheticTick]:
        """The full synthetic tick buffer (time-ordered)."""
        return self._ticks

    def get_ticker(self, product_code: str | None = None) -> dict[str, Any]:
        """Return a ticker payload matching ``lightning_ticker_FX_BTC_JPY``.

        Args:
            product_code: Optional override; defaults to the instance product.

        Returns:
            A dict with the same keys as the real ticker endpoint.
        """
        last = self._ticks[-1]
        spread = round(last.price * 0.00002, 1)
        return {
            "product_code": product_code or self.product_code,
            "state": "RUNNING",
            "timestamp": _fmt(last.exec_date),
            "tick_id": last.tick_id,
            "best_bid": last.price - spread,
            "best_ask": last.price + spread,
            "best_bid_size": 0.1,
            "best_ask_size": 0.1,
            "total_bid_depth": 1000.0,
            "total_ask_depth": 1000.0,
            "market_bid_size": 0.0,
            "market_ask_size": 0.0,
            "ltp": last.price,
            "volume": sum(t.size for t in self._ticks),
            "volume_by_product": sum(t.size for t in self._ticks),
        }

    def get_board(self, product_code: str | None = None) -> dict[str, Any]:
        """Return a board snapshot matching ``lightning_board_snapshot_FX_BTC_JPY``.

        Args:
            product_code: Optional override; defaults to the instance product.

        Returns:
            A dict with ``mid_price``, ``bids`` and ``asks`` arrays.
        """
        last = self._ticks[-1]
        mid = last.price
        bids = [{"price": mid - 100 * (i + 1), "size": 0.5} for i in range(10)]
        asks = [{"price": mid + 100 * (i + 1), "size": 0.5} for i in range(10)]
        return {"mid_price": mid, "bids": bids, "asks": asks}

    def get_executions(
        self,
        product_code: str | None = None,
        *,
        count: int = 100,
        before: int | None = None,
        after: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent executions matching ``lightning_executions_FX_BTC_JPY``.

        Mirrors the real endpoint's ``count`` / ``before`` / ``after`` paging.
        Results are newest-first, as the real API returns them.

        Args:
            product_code: Optional override; defaults to the instance product.
            count: Max number of executions (real API caps at 500).
            before: Return executions with ``id`` strictly less than this.
            after: Return executions with ``id`` strictly greater than this.

        Returns:
            A list of execution dicts, newest first.
        """
        ticks = self._ticks
        if before is not None:
            ticks = [t for t in ticks if t.tick_id < before]
        if after is not None:
            ticks = [t for t in ticks if t.tick_id > after]
        selected = ticks[-min(count, 500):]
        return [self._exec_payload(t) for t in reversed(selected)]

    @staticmethod
    def _exec_payload(tick: SyntheticTick) -> dict[str, Any]:
        return {
            "id": tick.tick_id,
            "side": tick.side,
            "price": tick.price,
            "size": tick.size,
            "exec_date": _fmt(tick.exec_date),
            "buy_child_order_acceptance_id": f"JRF-MOCK-{tick.tick_id:08d}",
            "sell_child_order_acceptance_id": f"JRF-MOCK-{tick.tick_id:08d}",
        }
