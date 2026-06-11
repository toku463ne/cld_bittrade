"""Tests for the read-only GMO client (no live calls; GMO-specific auth/envelope)."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

import pytest

from src.config import Settings
from src.execution.gmo_client import (
    PRIVATE_BASE,
    GmoApiError,
    GmoClient,
    _unwrap,
    gmo_account_client_from_settings,
)


class _FakeResp:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class _CapturingSession:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.url: str | None = None
        self.headers: dict[str, str] | None = None
        self.params: dict[str, Any] | None = None

    def get(self, url: str, *, headers: dict[str, str], params: Any, timeout: float) -> _FakeResp:
        self.url, self.headers, self.params = url, headers, params
        return _FakeResp(self.payload)


def _client(payload: Any) -> tuple[GmoClient, _CapturingSession]:
    c = GmoClient("KEY", "SEC")
    sess = _CapturingSession(payload)
    c._session = sess  # type: ignore[assignment]
    return c, sess


def test_requires_key_secret() -> None:
    with pytest.raises(ValueError):
        GmoClient("", "s")


def test_unwrap_success_and_error() -> None:
    assert _unwrap({"status": 0, "data": {"x": 1}}) == {"x": 1}
    with pytest.raises(GmoApiError):
        _unwrap({"status": 5, "messages": [{"message_code": "ERR"}]})


def test_get_signs_path_only_ms_timestamp() -> None:
    c, sess = _client({"status": 0, "data": {"list": []}})
    c.get_open_positions("BTC_JPY")
    # query is passed via params, NOT in the signed path
    assert sess.url == f"{PRIVATE_BASE}/v1/openPositions"
    assert sess.params == {"symbol": "BTC_JPY"}
    h = sess.headers or {}
    ts = h["API-TIMESTAMP"]
    assert ts.isdigit() and len(ts) >= 13  # milliseconds
    expected = hmac.new(b"SEC", (ts + "GET" + "/v1/openPositions").encode(), hashlib.sha256).hexdigest()
    assert h["API-SIGN"] == expected
    assert h["API-KEY"] == "KEY"


def test_list_endpoints_unwrap_list() -> None:
    c, _ = _client({"status": 0, "data": {"list": [{"positionId": 1}], "pagination": {}}})
    assert c.get_open_positions("XRP_JPY") == [{"positionId": 1}]


def test_get_error_envelope_raises() -> None:
    c, _ = _client({"status": 4, "messages": [{"message_code": "ERR-201"}]})
    with pytest.raises(GmoApiError):
        c.get_margin()


def test_send_order_refuses_read_only() -> None:
    c, _ = _client(None)
    with pytest.raises(NotImplementedError):
        c.send_order()


def _settings(*, use_live: bool) -> Settings:
    return Settings(
        env_name="dev",
        database_url="postgresql+psycopg2://x/y",
        use_live_api=use_live,
        allow_orders=False,
        product_code="FX_BTC_JPY",
        bitflyer_api_key="",
        bitflyer_api_secret="",
        gmo_api_key="gk",
        gmo_api_secret="gs",
        log_level="INFO",
    )


def test_factory_refuses_when_not_live() -> None:
    with pytest.raises(RuntimeError):
        gmo_account_client_from_settings(_settings(use_live=False))


def test_factory_builds_when_live() -> None:
    c = gmo_account_client_from_settings(_settings(use_live=True))
    assert isinstance(c, GmoClient)
    assert c.allow_orders is False
