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
import json
import time
from typing import Any
from urllib.parse import urlencode

import requests
from loguru import logger

from src.config import Settings, get_settings
from src.portfolio.position import MIN_LOT  # 0.001 BTC — the only permitted live size

API_ROOT = "https://api.bitflyer.com"  # paths below include the leading /v1
_TIMEOUT = 10.0


def fetch_markets() -> list[dict[str, Any]]:
    """Public, keyless list of all bitFlyer products (``GET /v1/getmarkets``).

    Each entry has ``product_code`` and often ``market_type`` (``Spot`` is long-only;
    ``FX`` / CFD allow shorts). The bidirectional strategies need a shortable product
    per asset — use this to confirm which ``XRP`` / ``ETH`` products (if any) support
    shorting before trading them.
    """
    resp = requests.get(f"{API_ROOT}/v1/getmarkets", timeout=_TIMEOUT)
    resp.raise_for_status()
    return list(resp.json())


class BitflyerClient:
    """Read-only authenticated client for the bitFlyer private REST API.

    Args:
        api_key: API key.
        api_secret: API secret.
        product_code: Default product for position/order/execution queries.
        allow_orders: If ``False`` (default), the order-placing methods raise — the
            client is read-only. Set ``True`` only via :func:`trading_client_from_settings`
            (which additionally requires ``USE_LIVE_API`` and ``ALLOW_ORDERS``).

    Raises:
        ValueError: If ``api_key`` or ``api_secret`` is empty.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        product_code: str = "FX_BTC_JPY",
        *,
        allow_orders: bool = False,
    ) -> None:
        if not api_key or not api_secret:
            raise ValueError(
                "bitFlyer API key/secret missing. Set BITFLYER_API_KEY / "
                "BITFLYER_API_SECRET in .env.dev (never commit them)."
            )
        self._key = api_key
        self._secret = api_secret.encode("utf-8")
        self.product_code = product_code
        self.allow_orders = allow_orders
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

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        """Signed POST. ``path`` starts at ``/v1/me/...``; the JSON body is signed."""
        payload = json.dumps(body)
        resp = self._session.post(
            API_ROOT + path,
            headers=self._headers("POST", path, payload),
            data=payload,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    # ---- public (unsigned) --------------------------------------------------

    def get_markets(self) -> list[dict[str, Any]]:
        """All tradeable products and their types (``GET /v1/getmarkets``, public).

        Use this to confirm which instruments exist and which are *shortable*: spot
        pairs (``XRP_JPY``, ``ETH_JPY`` …) are long-only; the leveraged/CFD products
        (``FX_BTC_JPY`` and any ``market_type`` of ``FX`` / CFD) allow shorts. The
        bidirectional strategies require a shortable product per asset.
        """
        resp = self._session.get(f"{API_ROOT}/v1/getmarkets", timeout=_TIMEOUT)
        resp.raise_for_status()
        return list(resp.json())

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

    # ---- order placement — guarded, minimum-lot only ------------------------

    def _guard_orders(self, size: float) -> None:
        """Enforce the two hard guards before any order leaves this client."""
        if not self.allow_orders:
            raise PermissionError(
                "Order placement disabled (allow_orders=False). Use "
                "trading_client_from_settings() with USE_LIVE_API=true and "
                "ALLOW_ORDERS=true to enable."
            )
        if size > MIN_LOT + 1e-12:
            raise ValueError(
                f"size {size} exceeds the hard minimum-lot cap {MIN_LOT} BTC. Lot "
                "increases are forbidden until the benchmark passes (CLAUDE.md)."
            )

    def send_child_order(
        self,
        side: str,
        *,
        size: float = MIN_LOT,
        order_type: str = "MARKET",
        price: float | None = None,
        product_code: str | None = None,
        minute_to_expire: int = 60,
        time_in_force: str = "GTC",
    ) -> dict[str, Any]:
        """Place one child order (``POST /v1/me/sendchildorder``). Minimum-lot only.

        Args:
            side: ``"BUY"`` or ``"SELL"``.
            size: BTC size; hard-capped at :data:`MIN_LOT` (0.001).
            order_type: ``"MARKET"`` or ``"LIMIT"``.
            price: Required for ``LIMIT``; ignored for ``MARKET``.
            product_code: Defaults to the client's product.
            minute_to_expire: Order expiry in minutes (a resting limit auto-cancels).
            time_in_force: ``GTC`` / ``IOC`` / ``FOK``.

        Returns:
            ``{"child_order_acceptance_id": ...}``.

        Raises:
            PermissionError: If ``allow_orders`` is false.
            ValueError: If ``size`` exceeds the cap, or ``LIMIT`` without a price.
        """
        self._guard_orders(size)
        s = side.upper()
        if s not in {"BUY", "SELL"}:
            raise ValueError(f"side must be BUY or SELL, got {side!r}")
        ot = order_type.upper()
        if ot == "LIMIT" and price is None:
            raise ValueError("LIMIT order requires a price")
        body: dict[str, Any] = {
            "product_code": product_code or self.product_code,
            "child_order_type": ot,
            "side": s,
            "size": size,
            "minute_to_expire": minute_to_expire,
            "time_in_force": time_in_force,
        }
        if ot == "LIMIT":
            body["price"] = price
        logger.warning("LIVE ORDER -> {} {} {} {} @ {}", body["product_code"], s, ot, size, price)
        return dict(self._post("/v1/me/sendchildorder", body))

    def cancel_child_order(self, child_order_acceptance_id: str, product_code: str | None = None) -> None:
        """Cancel one child order (``POST /v1/me/cancelchildorder``)."""
        if not self.allow_orders:
            raise PermissionError("Order cancel disabled (allow_orders=False).")
        self._post("/v1/me/cancelchildorder", {
            "product_code": product_code or self.product_code,
            "child_order_acceptance_id": child_order_acceptance_id,
        })

    def cancel_all_orders(self, product_code: str | None = None) -> None:
        """Cancel all active child orders for the product (``POST /v1/me/cancelallchildorders``)."""
        if not self.allow_orders:
            raise PermissionError("Order cancel disabled (allow_orders=False).")
        self._post("/v1/me/cancelallchildorders", {"product_code": product_code or self.product_code})


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


def trading_client_from_settings(settings: Settings | None = None) -> BitflyerClient:
    """Build an order-capable client — requires BOTH ``USE_LIVE_API`` and ``ALLOW_ORDERS``.

    The trade CLIs additionally require an explicit ``--execute`` flag, so live
    order placement needs three deliberate gates. Size is hard-capped at
    :data:`MIN_LOT` inside the client regardless.

    Raises:
        RuntimeError: If ``USE_LIVE_API`` or ``ALLOW_ORDERS`` is not true.
        ValueError: If the API key/secret are unset.
    """
    s = settings or get_settings()
    if not s.use_live_api:
        raise RuntimeError("USE_LIVE_API is false — cannot place orders.")
    if not s.allow_orders:
        raise RuntimeError(
            "ALLOW_ORDERS is false — order placement is gated. Set ALLOW_ORDERS=true "
            "in .env.dev to enable (and the trade CLI still needs --execute)."
        )
    logger.warning("LIVE bitFlyer TRADING client enabled (orders ALLOWED) for {}", s.product_code)
    return BitflyerClient(
        s.bitflyer_api_key, s.bitflyer_api_secret, s.product_code, allow_orders=True
    )
