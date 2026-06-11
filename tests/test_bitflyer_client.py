"""Tests for the read-only bitFlyer private client (no live calls)."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

import pytest

from src.config import Settings
from src.execution.bitflyer_client import (
    API_ROOT,
    BitflyerClient,
    account_client_from_settings,
    trading_client_from_settings,
)


class _FakeResp:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class _CapturingSession:
    """Captures the request and returns a queued payload (no network)."""

    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.url: str | None = None
        self.headers: dict[str, str] | None = None

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> _FakeResp:
        self.url = url
        self.headers = headers
        return _FakeResp(self.payload)

    def post(self, url: str, *, headers: dict[str, str], data: str, timeout: float) -> _FakeResp:
        self.url = url
        self.headers = headers
        self.body = data
        return _FakeResp(self.payload)


def _client(payload: Any) -> tuple[BitflyerClient, _CapturingSession]:
    c = BitflyerClient("KEY123", "SECRET456", product_code="FX_BTC_JPY")
    sess = _CapturingSession(payload)
    c._session = sess  # type: ignore[assignment]
    return c, sess


def test_requires_key_and_secret() -> None:
    with pytest.raises(ValueError):
        BitflyerClient("", "secret")
    with pytest.raises(ValueError):
        BitflyerClient("key", "")


def test_signed_get_signs_path_with_query() -> None:
    c, sess = _client([{"product_code": "FX_BTC_JPY", "side": "BUY", "size": 0.001}])
    c.get_positions()
    assert sess.url == f"{API_ROOT}/v1/me/getpositions?product_code=FX_BTC_JPY"
    h = sess.headers or {}
    assert h["ACCESS-KEY"] == "KEY123"
    # Recompute the expected signature from the captured timestamp.
    ts = h["ACCESS-TIMESTAMP"]
    expected = hmac.new(
        b"SECRET456",
        (ts + "GET" + "/v1/me/getpositions?product_code=FX_BTC_JPY").encode(),
        hashlib.sha256,
    ).hexdigest()
    assert h["ACCESS-SIGN"] == expected


def test_is_read_only_true_without_trade_perms() -> None:
    c, _ = _client(["/v1/me/getbalance", "/v1/me/getpositions", "/v1/me/getexecutions"])
    assert c.is_read_only() is True


def test_is_read_only_false_with_send_perm() -> None:
    c, _ = _client(["/v1/me/getbalance", "/v1/me/sendchildorder"])
    assert c.is_read_only() is False


def test_send_child_order_refuses_when_read_only() -> None:
    # Default client is read-only (allow_orders=False) -> any order is blocked.
    c, _ = _client(None)
    with pytest.raises(PermissionError):
        c.send_child_order("BUY")
    with pytest.raises(PermissionError):
        c.cancel_all_orders()


def test_order_size_hard_capped() -> None:
    c = BitflyerClient("k", "s", allow_orders=True)
    c._session = _CapturingSession({"child_order_acceptance_id": "X"})  # type: ignore[assignment]
    with pytest.raises(ValueError):
        c.send_child_order("BUY", size=0.01)  # 10x the 0.001 cap
    # at the cap it is allowed and signs a POST
    res = c.send_child_order("BUY", size=0.001, order_type="MARKET")
    assert res["child_order_acceptance_id"] == "X"


def test_limit_requires_price() -> None:
    c = BitflyerClient("k", "s", allow_orders=True)
    c._session = _CapturingSession({})  # type: ignore[assignment]
    with pytest.raises(ValueError):
        c.send_child_order("SELL", order_type="LIMIT", price=None)


def _settings(*, use_live: bool, allow_orders: bool = False, key: str = "k", secret: str = "s") -> Settings:
    return Settings(
        env_name="dev",
        database_url="postgresql+psycopg2://x/y",
        use_live_api=use_live,
        allow_orders=allow_orders,
        product_code="FX_BTC_JPY",
        bitflyer_api_key=key,
        bitflyer_api_secret=secret,
        log_level="INFO",
    )


def test_account_factory_refuses_when_not_live() -> None:
    with pytest.raises(RuntimeError):
        account_client_from_settings(_settings(use_live=False))


def test_account_factory_builds_read_only_when_live() -> None:
    c = account_client_from_settings(_settings(use_live=True))
    assert isinstance(c, BitflyerClient)
    assert c.allow_orders is False  # read client cannot order even when live


def test_trading_factory_needs_both_gates() -> None:
    with pytest.raises(RuntimeError):  # live but ALLOW_ORDERS false
        trading_client_from_settings(_settings(use_live=True, allow_orders=False))
    with pytest.raises(RuntimeError):  # ALLOW_ORDERS true but not live
        trading_client_from_settings(_settings(use_live=False, allow_orders=True))
    c = trading_client_from_settings(_settings(use_live=True, allow_orders=True))
    assert c.allow_orders is True
