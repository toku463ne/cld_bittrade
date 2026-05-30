"""Mock of the bitFlyer Lightning WebSocket feed.

Replays a tick sequence as JSON-RPC channel messages identical in shape to the
real ``wss://ws.bitflyer.com/v1`` feed, so the consuming code path is the same
in mock and live modes. Used by :mod:`src.data.feed` during development.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from src.mock.mock_api import _fmt
from src.mock.synthetic import SyntheticTick, generate_ticks


class MockBitflyerWS:
    """Replays synthetic executions as WebSocket channel messages.

    The real feed pushes JSON-RPC 2.0 notifications of the form::

        {"jsonrpc": "2.0", "method": "channelMessage",
         "params": {"channel": "lightning_executions_FX_BTC_JPY",
                    "message": [ <execution>, ... ]}}

    This mock yields the same structure, optionally batching ticks per message.
    """

    def __init__(
        self,
        product_code: str = "FX_BTC_JPY",
        *,
        ticks: list[SyntheticTick] | None = None,
        n_ticks: int = 20_000,
        seed: int = 42,
        batch_size: int = 1,
    ) -> None:
        """Initialise the mock WS.

        Args:
            product_code: Product whose channel is replayed.
            ticks: Pre-built tick list; if ``None`` a synthetic stream is made.
            n_ticks: Number of synthetic ticks when ``ticks`` is ``None``.
            seed: RNG seed for reproducibility.
            batch_size: Executions per ``channelMessage`` (real feed batches).
        """
        self.product_code = product_code
        self.channel = f"lightning_executions_{product_code}"
        self.batch_size = max(1, batch_size)
        self._ticks: list[SyntheticTick] = ticks or list(
            generate_ticks(count=n_ticks, seed=seed)
        )

    def stream(self) -> Iterator[dict[str, Any]]:
        """Yield JSON-RPC ``channelMessage`` notifications for the exec channel.

        Yields:
            Notification dicts matching the real WS schema.
        """
        batch: list[dict[str, Any]] = []
        for tick in self._ticks:
            batch.append(
                {
                    "id": tick.tick_id,
                    "side": tick.side,
                    "price": tick.price,
                    "size": tick.size,
                    "exec_date": _fmt(tick.exec_date),
                    "buy_child_order_acceptance_id": f"JRF-MOCK-{tick.tick_id:08d}",
                    "sell_child_order_acceptance_id": f"JRF-MOCK-{tick.tick_id:08d}",
                }
            )
            if len(batch) >= self.batch_size:
                yield self._wrap(batch)
                batch = []
        if batch:
            yield self._wrap(batch)

    def _wrap(self, message: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "method": "channelMessage",
            "params": {"channel": self.channel, "message": message},
        }
