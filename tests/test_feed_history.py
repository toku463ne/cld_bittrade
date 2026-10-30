"""Tests for the feeds' resumable pagination cursors (no DB, no network)."""

from __future__ import annotations

import pytest
import requests

from src.data.feed import _LiveFeed, _MockFeed


def _ids(execs: list[dict[str, object]]) -> list[int]:
    return [int(e["id"]) for e in execs]


def test_iter_history_newest_first_and_capped() -> None:
    feed = _MockFeed("FX_BTC_JPY")
    out = list(feed.iter_history(10))
    assert len(out) == 10
    ids = _ids(out)
    assert ids == sorted(ids, reverse=True)  # newest-first


def test_before_is_exclusive_upper_bound() -> None:
    feed = _MockFeed("FX_BTC_JPY")
    out = list(feed.iter_history(5, before=100))
    ids = _ids(out)
    assert max(ids) < 100
    # Should return the 5 ids immediately below the cursor: 99..95.
    assert ids == [99, 98, 97, 96, 95]


def test_stop_at_id_is_exclusive_lower_bound() -> None:
    feed = _MockFeed("FX_BTC_JPY")
    out = list(feed.iter_history(10_000, before=50, stop_at_id=45))
    ids = _ids(out)
    # Only ids strictly between 45 and 50: 49,48,47,46.
    assert ids == [49, 48, 47, 46]


def test_zero_max_ticks_yields_nothing() -> None:
    feed = _MockFeed("FX_BTC_JPY")
    assert list(feed.iter_history(0)) == []


def test_forward_cursor_collects_only_newer() -> None:
    feed = _MockFeed("FX_BTC_JPY")
    # Simulate "catch up": collect everything newer than id 19990.
    out = list(feed.iter_history(10_000, stop_at_id=19_990))
    ids = _ids(out)
    assert min(ids) > 19_990
    assert max(ids) == len(feed._api.ticks)  # newest available


class _FakeResp:
    def __init__(self, status: int, body: list[dict[str, object]]) -> None:
        self.status_code = status
        self._body = body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error")

    def json(self) -> list[dict[str, object]]:
        return self._body


class _FakeSession:
    def __init__(self, resp: _FakeResp) -> None:
        self._resp = resp

    def get(self, *args: object, **kwargs: object) -> _FakeResp:
        return self._resp


def test_live_backward_cursor_past_retention_ends_history() -> None:
    # bitFlyer returns 400 for a ``before`` older than its retention window.
    feed = _LiveFeed("FX_BTC_JPY")
    feed._session = _FakeSession(_FakeResp(400, []))  # type: ignore[assignment]
    assert list(feed.iter_history(500, before=2643674473)) == []


def test_live_400_without_cursor_still_raises() -> None:
    feed = _LiveFeed("FX_BTC_JPY")
    feed._session = _FakeSession(_FakeResp(400, []))  # type: ignore[assignment]
    with pytest.raises(requests.HTTPError):
        list(feed.iter_history(500))
