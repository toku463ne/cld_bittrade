"""bitFlyer Lightning price feed.

This module is the single gateway to external market data. By default it serves
the mock layer; the live REST/WS client is used only when ``USE_LIVE_API=true``.

The live client is intentionally minimal here and is exercised only in
production; development and tests must run through the mock (per CLAUDE.md).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any, Protocol

import requests
from loguru import logger

from src.config import get_settings
from src.mock.mock_api import MockBitflyerAPI
from src.mock.mock_ws import MockBitflyerWS

REST_BASE = "https://api.bitflyer.com/v1"
WS_URL = "wss://ws.bitflyer.com/v1"

# Public getexecutions paging: max 500 rows/call; pace to stay under the
# ~500 req / 5 min public rate limit.
_PAGE_SIZE = 500
_PAGE_SLEEP_SEC = 0.4


class PriceFeed(Protocol):
    """Common interface implemented by both mock and live feeds."""

    def get_ticker(self, product_code: str | None = None) -> dict[str, Any]: ...

    def get_executions(
        self, product_code: str | None = None, *, count: int = 100
    ) -> list[dict[str, Any]]: ...

    def iter_history(
        self,
        max_ticks: int,
        *,
        before: int | None = None,
        stop_at_id: int | None = None,
    ) -> Iterator[dict[str, Any]]: ...

    def stream_executions(self) -> Iterator[dict[str, Any]]: ...


class _MockFeed:
    """Adapter exposing :class:`PriceFeed` over the mock REST/WS classes."""

    def __init__(self, product_code: str) -> None:
        self._api = MockBitflyerAPI(product_code)
        self._ws = MockBitflyerWS(product_code, ticks=self._api.ticks)

    def get_ticker(self, product_code: str | None = None) -> dict[str, Any]:
        return self._api.get_ticker(product_code)

    def get_executions(
        self, product_code: str | None = None, *, count: int = 100
    ) -> list[dict[str, Any]]:
        return self._api.get_executions(product_code, count=count)

    def iter_history(
        self,
        max_ticks: int,
        *,
        before: int | None = None,
        stop_at_id: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        # The mock buffer is ascending by id. Apply the same cursor semantics as
        # the live feed: ``before`` is an exclusive upper id bound, ``stop_at_id``
        # an exclusive lower id bound. Yield newest-first, capped at max_ticks.
        if max_ticks <= 0:
            return
        ticks = self._api.ticks
        selected = [
            t
            for t in ticks
            if (before is None or t.tick_id < before)
            and (stop_at_id is None or t.tick_id > stop_at_id)
        ]
        for tick in reversed(selected[-max_ticks:]):
            yield self._api._exec_payload(tick)

    def stream_executions(self) -> Iterator[dict[str, Any]]:
        for note in self._ws.stream():
            for execution in note["params"]["message"]:
                yield execution


class _LiveFeed:
    """Live bitFlyer REST feed (public endpoints only).

    Only reached when ``USE_LIVE_API=true``. WebSocket streaming is left as an
    explicit not-implemented surface to avoid accidental live connections during
    development.
    """

    def __init__(self, product_code: str) -> None:
        self.product_code = product_code
        self._session = requests.Session()
        logger.warning("LIVE bitFlyer feed enabled for {}", product_code)

    def get_ticker(self, product_code: str | None = None) -> dict[str, Any]:
        resp = self._session.get(
            f"{REST_BASE}/getticker",
            params={"product_code": product_code or self.product_code},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    def get_executions(
        self, product_code: str | None = None, *, count: int = 100
    ) -> list[dict[str, Any]]:
        params: dict[str, str | int] = {
            "product_code": product_code or self.product_code,
            "count": count,
        }
        resp = self._session.get(
            f"{REST_BASE}/getexecutions",
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    def iter_history(
        self,
        max_ticks: int,
        *,
        before: int | None = None,
        stop_at_id: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield up to ``max_ticks`` executions newest-first, via REST paging.

        Read-only: walks the public ``getexecutions`` endpoint backwards using
        the ``before=<id>`` cursor. Paces requests with a short sleep to stay
        under bitFlyer's public rate limit (~500 requests / 5 minutes per IP).
        No API key required.

        Args:
            max_ticks: Maximum number of executions to retrieve.
            before: Start strictly below this execution id (backward cursor for
                resumable deep-history paging). ``None`` starts from the latest.
            stop_at_id: Stop once an execution id ``<= stop_at_id`` is reached
                (forward cursor: collect only what is newer than a known id).

        Yields:
            Execution dicts (same schema as :meth:`get_executions`), newest-first.
        """
        remaining = max_ticks
        cursor = before
        pages = 0
        while remaining > 0:
            count = min(_PAGE_SIZE, remaining)
            params: dict[str, str | int] = {
                "product_code": self.product_code,
                "count": count,
            }
            if cursor is not None:
                params["before"] = cursor
            resp = self._session.get(
                f"{REST_BASE}/getexecutions", params=params, timeout=10
            )
            resp.raise_for_status()
            page: list[dict[str, Any]] = resp.json()
            if not page:
                logger.info("History exhausted after {} pages.", pages)
                break

            reached_stop = False
            for execution in page:  # newest-first
                if stop_at_id is not None and int(execution["id"]) <= stop_at_id:
                    reached_stop = True
                    break
                yield execution
                remaining -= 1
                if remaining <= 0:
                    break

            cursor = min(int(e["id"]) for e in page)
            pages += 1
            logger.debug("Fetched page {} ({} execs), before -> {}", pages, len(page), cursor)
            if reached_stop or len(page) < count:
                break
            time.sleep(_PAGE_SLEEP_SEC)

    def stream_executions(self) -> Iterator[dict[str, Any]]:
        raise NotImplementedError(
            "Live WS streaming is implemented in the execution layer (step 12), "
            "not in development. Use the mock feed."
        )


def get_feed(product_code: str | None = None) -> PriceFeed:
    """Return the active price feed (mock unless ``USE_LIVE_API=true``).

    Args:
        product_code: Override product; defaults to the configured one.

    Returns:
        A :class:`PriceFeed` implementation.
    """
    settings = get_settings()
    product = product_code or settings.product_code
    if settings.use_live_api:
        return _LiveFeed(product)
    logger.debug("Using MOCK feed for {}", product)
    return _MockFeed(product)
