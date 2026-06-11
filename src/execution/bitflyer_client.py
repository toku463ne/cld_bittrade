"""Authenticated bitFlyer Lightning REST client — READ-ONLY private endpoints.

The single gateway to the bitFlyer **private** API (account, positions, orders,
own executions). Public market data stays in :mod:`src.data.feed`; this module
adds HMAC-SHA256 authentication for the ``/v1/me/*`` endpoints.

**Read-only by design.** A read-only API key cannot place orders, and the project
forbids live trading before the benchmark passes (CLAUDE.md). Accordingly only GET
(read) endpoints are implemented; :meth:`BitflyerClient.send_child_order` exists as
a guarded stub that refuses, documenting the path without enabling it.

Safety:
- The live client is constructed only when ``USE_LIVE_API=true`` and a key is set;
  otherwise :func:`account_client_from_settings` raises (no silent live calls).
- The secret is read from the environment via :func:`~src.config.get_settings`
  (i.e. ``.env.dev``) and is never logged.
- Auth signing follows the bitFlyer spec: ``ACCESS-SIGN = HMAC_SHA256(secret,
  timestamp + method + path_with_query + body)``.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any
from urllib.parse import urlencode

import requests
from loguru import logger

from src.config import Settings, get_settings

API_ROOT = "https://api.bitflyer.com"  # paths below include the leading /v1
_TIMEOUT = 10.0


class BitflyerClient:
    """Read-only authenticated client for the bitFlyer private REST API.

    Args:
        api_key: API key (read-only).
        api_secret: API secret.
        product_code: Default product for position/order/execution queries.

    Raises:
        ValueError: If ``api_key`` or ``api_secret`` is empty.
    """

    def __init__(self, api_key: str, api_secret: str, product_code: str = "FX_BTC_JPY") -> None:
        if not api_key or not api_secret:
            raise ValueError(
                "bitFlyer API key/secret missing. Set BITFLYER_API_KEY / "
                "BITFLYER_API_SECRET in .env.dev (never commit them)."
            )
        self._key = api_key
        self._secret = api_secret.encode("utf-8")
        self.product_code = product_code
        self._session = requests.Session()

    # ---- signing + transport ------------------------------------------------

    def _headers(self, method: str, path_with_query: str, body: str = "") -> dict[str, str]:
        """Build the ACCESS-* auth headers for one request (never logs the sign)."""
        ts = str(int(time.time()))
        text = ts + method + path_with_query + body
        sign = hmac.new(self._secret, text.encode("utf-8"), hashlib.sha256).hexdigest()
        return {
            "ACCESS-KEY": self._key,
            "ACCESS-TIMESTAMP": ts,
            "ACCESS-SIGN": sign,
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Signed GET. ``path`` starts at ``/v1/me/...``; query is signed too."""
        query = urlencode(params) if params else ""
        path_with_query = f"{path}?{query}" if query else path
        resp = self._session.get(
            API_ROOT + path_with_query,
            headers=self._headers("GET", path_with_query),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    # ---- read-only endpoints ------------------------------------------------

    def get_permissions(self) -> list[str]:
        """Endpoints this key may call (``GET /v1/me/getpermissions``).

        A read-only key omits ``/v1/me/sendchildorder`` etc. — see
        :meth:`is_read_only`.
        """
        result = self._get("/v1/me/getpermissions")
        return list(result) if isinstance(result, list) else []

    def is_read_only(self) -> bool:
        """True if the key lacks any order-placing permission (the expected state)."""
        perms = set(self.get_permissions())
        trade = {"/v1/me/sendchildorder", "/v1/me/sendparentorder", "/v1/me/cancelchildorder"}
        return not (perms & trade)

    def get_balance(self) -> list[dict[str, Any]]:
        """Per-currency balances (``GET /v1/me/getbalance``)."""
        return list(self._get("/v1/me/getbalance"))

    def get_collateral(self) -> dict[str, Any]:
        """Margin/collateral status for the FX account (``GET /v1/me/getcollateral``)."""
        return dict(self._get("/v1/me/getcollateral"))

    def get_positions(self, product_code: str | None = None) -> list[dict[str, Any]]:
        """Open FX positions (``GET /v1/me/getpositions``)."""
        return list(self._get("/v1/me/getpositions", {"product_code": product_code or self.product_code}))

    def get_active_orders(self, product_code: str | None = None) -> list[dict[str, Any]]:
        """Active (unfilled) child orders (``GET /v1/me/getchildorders?...ACTIVE``)."""
        return list(self._get(
            "/v1/me/getchildorders",
            {"product_code": product_code or self.product_code, "child_order_state": "ACTIVE"},
        ))

    def get_my_executions(
        self, product_code: str | None = None, *, count: int = 100
    ) -> list[dict[str, Any]]:
        """This account's own executions (``GET /v1/me/getexecutions``)."""
        return list(self._get(
            "/v1/me/getexecutions",
            {"product_code": product_code or self.product_code, "count": count},
        ))

    # ---- order placement — deliberately disabled ----------------------------

    def send_child_order(self, *_args: Any, **_kwargs: Any) -> None:
        """Refuses. Order placement is intentionally not enabled.

        Raises:
            NotImplementedError: Always. Live order placement requires (1) a
                trade-enabled key (this client is read-only), (2) the benchmark
                to have PASSED with a confirmed forward record, and (3) an
                explicit, audited opt-in. Until then trading is human-executed at
                the 0.001 minimum lot (CLAUDE.md). Enable in a separate, reviewed
                change — do not relax this guard casually.
        """
        raise NotImplementedError(
            "Order placement is disabled: read-only client, and no strategy has a "
            "confirmed forward record yet. Trade manually at 0.001 lot (CLAUDE.md)."
        )


def account_client_from_settings(settings: Settings | None = None) -> BitflyerClient:
    """Build a live :class:`BitflyerClient` from the active environment.

    Args:
        settings: Optional pre-loaded settings; defaults to :func:`get_settings`.

    Returns:
        A configured read-only client.

    Raises:
        RuntimeError: If ``USE_LIVE_API`` is not true (no accidental live calls in
            dev/test — those must use the mock layer per CLAUDE.md).
        ValueError: If the API key/secret are unset.
    """
    s = settings or get_settings()
    if not s.use_live_api:
        raise RuntimeError(
            "USE_LIVE_API is false — the private account client is live-only. "
            "Set USE_LIVE_API=true in .env.dev to enable, or use the mock layer."
        )
    logger.warning("LIVE bitFlyer account client enabled (read-only) for {}", s.product_code)
    return BitflyerClient(s.bitflyer_api_key, s.bitflyer_api_secret, s.product_code)
