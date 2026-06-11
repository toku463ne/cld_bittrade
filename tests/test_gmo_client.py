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
    _fmt,
    _unwrap,
    gmo_account_client_from_settings,
    gmo_trading_client_from_settings,
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

        self.body: str | None = None

    def get(self, url: str, *, headers: dict[str, str], params: Any, timeout: float) -> _FakeResp:
        self.url, self.headers, self.params = url, headers, params
        return _FakeResp(self.payload)

    def post(self, url: str, *, headers: dict[str, str], data: str, timeout: float) -> _FakeResp:
        self.url, self.headers, self.body = url, headers, data
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


def test_fmt_strips_trailing_zeros() -> None:
    assert _fmt(0.01) == "0.01"
    assert _fmt(10.0) == "10"
    assert _fmt(0.1) == "0.1"


def test_send_order_refuses_read_only() -> None:
    c, _ = _client(None)
    with pytest.raises(PermissionError):
        c.send_order("BTC_JPY", "BUY")
    with pytest.raises(PermissionError):
        c.cancel_bulk("BTC_JPY")


def _trading(payload: Any) -> tuple[GmoClient, _CapturingSession]:
    c = GmoClient("KEY", "SEC", allow_orders=True)
    sess = _CapturingSession(payload)
    c._session = sess  # type: ignore[assignment]
    return c, sess


def test_send_order_caps_per_symbol() -> None:
    c, _ = _trading({"status": 0, "data": "ORD1"})
    with pytest.raises(ValueError):
        c.send_order("BTC_JPY", "BUY", size=0.1)  # 10x the 0.01 cap
    with pytest.raises(ValueError):
        c.send_order("FOO_JPY", "BUY")  # not in the permitted set
    oid = c.send_order("BTC_JPY", "SELL")  # min lot, short open
    assert oid == "ORD1"


def test_send_order_signs_post_path_and_body() -> None:
    import hashlib as _h
    import hmac as _m
    c, sess = _trading({"status": 0, "data": "ORD2"})
    c.send_order("XRP_JPY", "BUY")
    assert sess.url == f"{PRIVATE_BASE}/v1/order"
    assert sess.body is not None and '"size": "10"' in sess.body
    h = sess.headers or {}
    ts = h["API-TIMESTAMP"]
    expected = _m.new(b"SEC", (ts + "POST" + "/v1/order" + sess.body).encode(), _h.sha256).hexdigest()
    assert h["API-SIGN"] == expected


def test_close_position_settle_body() -> None:
    c, sess = _trading({"status": 0, "data": "ORD3"})
    c.close_position("XRP_JPY", position_id=12345, side="SELL", size=10.0)
    assert sess.url == f"{PRIVATE_BASE}/v1/closeOrder"
    assert sess.body is not None
    assert '"positionId": 12345' in sess.body and '"settlePosition"' in sess.body


def test_limit_open_requires_price() -> None:
    c, _ = _trading({"status": 0, "data": "X"})
    with pytest.raises(ValueError):
        c.send_order("BTC_JPY", "BUY", execution_type="LIMIT", price=None)


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


def test_trading_factory_needs_both_gates() -> None:
    with pytest.raises(RuntimeError):
        gmo_trading_client_from_settings(_settings(use_live=True))  # ALLOW_ORDERS false
    s = _settings(use_live=True)
    object.__setattr__(s, "allow_orders", True)
    c = gmo_trading_client_from_settings(s)
    assert c.allow_orders is True
