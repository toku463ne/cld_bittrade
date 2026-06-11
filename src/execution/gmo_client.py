"""GMO Coin REST client — READ-ONLY private endpoints (leverage venue).

GMO Coin is the live target: its leverage (レバレッジ) ``*_JPY`` symbols are the
**exact** symbols our backtest data comes from (zero venue gap), and BTC_JPY /
ETH_JPY / XRP_JPY are all **shortable** — so the full bidirectional portfolio runs
as validated. Funding is ~0.04%/day, the ``daily_swap_rate`` we already model.

Differences from the bitFlyer client (deliberate, GMO-specific):
- Response envelope ``{"status": 0, "data": ...}``; ``status != 0`` is an error
  (``messages`` array). Numeric fields are **strings**.
- Auth: ``API-KEY`` / ``API-TIMESTAMP`` (milliseconds) / ``API-SIGN`` =
  ``HMAC_SHA256(secret, timestamp + method + path + body)``. For GET the signed
  ``path`` is **without** the query string (params are sent unsigned).
- Bases: ``…/public`` (keyless) and ``…/private``.

**Read-only by design** (same posture as the bitFlyer client): only GET endpoints;
:meth:`GmoClient.send_order` is a guarded stub until the order phase.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import requests
from loguru import logger

from src.config import Settings, get_settings

PUBLIC_BASE = "https://api.coin.z.com/public"
PRIVATE_BASE = "https://api.coin.z.com/private"
_TIMEOUT = 10.0

# GMO leverage minimum order sizes (取引数量) — VERIFY against the current GMO spec
# before trading; not exposed via the API. These set the live "minimum amount".
LEVERAGE_MIN_SIZE: dict[str, float] = {
    "BTC_JPY": 0.01,
    "ETH_JPY": 0.1,
    "XRP_JPY": 10.0,
}


def _fmt(x: float) -> str:
    """Format a size/price for GMO (strings, no trailing zeros): 0.01, 10, 0.1."""
    return f"{x:.8f}".rstrip("0").rstrip(".")


class GmoApiError(RuntimeError):
    """Raised when GMO returns a non-zero ``status``."""


def _unwrap(payload: dict[str, Any]) -> Any:
    """Return ``data`` on success (``status == 0``); raise on a GMO error envelope."""
    if payload.get("status") != 0:
        raise GmoApiError(f"GMO API error: {payload.get('messages', payload)}")
    return payload.get("data")


def fetch_status() -> str:
    """Exchange status (``OPEN`` / ``PREOPEN`` / ``MAINTENANCE``); public, keyless."""
    r = requests.get(f"{PUBLIC_BASE}/v1/status", timeout=_TIMEOUT)
    r.raise_for_status()
    return str(_unwrap(r.json()).get("status"))


def fetch_ticker(symbol: str) -> dict[str, Any]:
    """Latest ticker for ``symbol`` (public, keyless). Numeric fields are strings."""
    r = requests.get(f"{PUBLIC_BASE}/v1/ticker", params={"symbol": symbol}, timeout=_TIMEOUT)
    r.raise_for_status()
    rows = _unwrap(r.json())
    return dict(rows[0]) if rows else {}


class GmoClient:
    """Read-only authenticated GMO Coin client (leverage account / positions / orders).

    Args:
        api_key: GMO API key.
        api_secret: GMO API secret.
        allow_orders: ``False`` (default) makes order methods raise — read-only.

    Raises:
        ValueError: If ``api_key`` or ``api_secret`` is empty.
    """

    def __init__(self, api_key: str, api_secret: str, *, allow_orders: bool = False) -> None:
        if not api_key or not api_secret:
            raise ValueError(
                "GMO API key/secret missing. Set GMO_API_KEY / GMO_API_SECRET in "
                ".env.dev (never commit them)."
            )
        self._key = api_key
        self._secret = api_secret.encode("utf-8")
        self.allow_orders = allow_orders
        self._session = requests.Session()

    # ---- signing + transport ------------------------------------------------

    def _headers(self, method: str, path: str, body: str = "") -> dict[str, str]:
        """ACCESS headers; ``path`` excludes the query (GMO signs path-only for GET)."""
        ts = str(int(time.time() * 1000))  # milliseconds
        sign = hmac.new(
            self._secret, (ts + method + path + body).encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return {"API-KEY": self._key, "API-TIMESTAMP": ts, "API-SIGN": sign}

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Signed GET. ``path`` is the private path (e.g. ``/v1/openPositions``)."""
        resp = self._session.get(
            PRIVATE_BASE + path,
            headers=self._headers("GET", path),  # query is NOT signed
            params=params,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return _unwrap(resp.json())

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        """Signed POST (the body IS signed). Used by the order phase."""
        payload = json.dumps(body)
        resp = self._session.post(
            PRIVATE_BASE + path,
            headers=self._headers("POST", path, payload),
            data=payload,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return _unwrap(resp.json())

    # ---- read-only endpoints ------------------------------------------------

    def get_margin(self) -> dict[str, Any]:
        """Leverage account margin / available funds (``GET /v1/account/margin``)."""
        return dict(self._get("/v1/account/margin"))

    def get_assets(self) -> list[dict[str, Any]]:
        """Spot asset balances (``GET /v1/account/assets``)."""
        return list(self._get("/v1/account/assets"))

    def get_open_positions(self, symbol: str) -> list[dict[str, Any]]:
        """Open leverage positions / 建玉 (``GET /v1/openPositions``)."""
        data = self._get("/v1/openPositions", {"symbol": symbol})
        return list(data.get("list", [])) if isinstance(data, dict) else []

    def get_active_orders(self, symbol: str) -> list[dict[str, Any]]:
        """Active (unfilled) orders (``GET /v1/activeOrders``)."""
        data = self._get("/v1/activeOrders", {"symbol": symbol})
        return list(data.get("list", [])) if isinstance(data, dict) else []

    def get_latest_executions(self, symbol: str, *, count: int = 100) -> list[dict[str, Any]]:
        """Recent own executions (``GET /v1/latestExecutions``)."""
        data = self._get("/v1/latestExecutions", {"symbol": symbol, "count": count})
        return list(data.get("list", [])) if isinstance(data, dict) else []

    # ---- order placement — guarded, minimum-lot only ------------------------

    def _guard_orders(self, symbol: str, size: float) -> None:
        """Enforce the hard guards before any order leaves this client."""
        if not self.allow_orders:
            raise PermissionError(
                "Order placement disabled (allow_orders=False). Use "
                "gmo_trading_client_from_settings() with USE_LIVE_API=true and "
                "ALLOW_ORDERS=true."
            )
        cap = LEVERAGE_MIN_SIZE.get(symbol)
        if cap is None:
            raise ValueError(
                f"{symbol} is not in the permitted leverage set {list(LEVERAGE_MIN_SIZE)}."
            )
        if size > cap + 1e-9:
            raise ValueError(
                f"size {size} exceeds the min-lot cap {cap} for {symbol}. Lot increases "
                "are forbidden until the benchmark passes (CLAUDE.md)."
            )

    def send_order(
        self,
        symbol: str,
        side: str,
        *,
        size: float | None = None,
        execution_type: str = "MARKET",
        price: float | None = None,
        time_in_force: str | None = None,
    ) -> str:
        """Open a leverage position (``POST /v1/order``). Minimum-lot only.

        Args:
            symbol: ``BTC_JPY`` / ``ETH_JPY`` / ``XRP_JPY``.
            side: ``"BUY"`` (long) or ``"SELL"`` (short).
            size: Defaults to the symbol's minimum lot; hard-capped at it.
            execution_type: ``"MARKET"`` / ``"LIMIT"`` / ``"STOP"``.
            price: Required for non-MARKET; sent as a string.
            time_in_force: Optional override (``FAK`` / ``FAS`` / ``FOK``); GMO
                defaults FAK for MARKET, FAS for LIMIT.

        Returns:
            The GMO ``orderId`` (string).

        Raises:
            PermissionError / ValueError: On a closed guard or an out-of-cap size.
        """
        sz = (LEVERAGE_MIN_SIZE.get(symbol, 0.0) if size is None else size)
        self._guard_orders(symbol, sz)  # raises cleanly if symbol unknown / size over cap
        s = side.upper()
        if s not in {"BUY", "SELL"}:
            raise ValueError(f"side must be BUY or SELL, got {side!r}")
        et = execution_type.upper()
        body: dict[str, Any] = {"symbol": symbol, "side": s, "executionType": et, "size": _fmt(sz)}
        if et != "MARKET":
            if price is None:
                raise ValueError(f"{et} order requires a price")
            body["price"] = _fmt(price)
        if time_in_force:
            body["timeInForce"] = time_in_force
        logger.warning("LIVE GMO OPEN -> {} {} {} {} @ {}", symbol, s, et, _fmt(sz), price)
        return str(self._post("/v1/order", body))

    def close_position(
        self,
        symbol: str,
        position_id: int,
        side: str,
        size: float,
        *,
        execution_type: str = "MARKET",
        price: float | None = None,
    ) -> str:
        """Settle one open 建玉 by id (``POST /v1/closeOrder``).

        Args:
            symbol: The position's symbol.
            position_id: The ``positionId`` from :meth:`get_open_positions`.
            side: The CLOSING order side — opposite of the position
                (``SELL`` to close a long, ``BUY`` to close a short).
            size: Size to settle (the position's size; min-lot capped).
            execution_type: ``"MARKET"`` (default) / ``"LIMIT"``.
            price: Required for non-MARKET.

        Returns:
            The GMO ``orderId`` (string).
        """
        self._guard_orders(symbol, size)
        s = side.upper()
        et = execution_type.upper()
        body: dict[str, Any] = {
            "symbol": symbol,
            "side": s,
            "executionType": et,
            "settlePosition": [{"positionId": int(position_id), "size": _fmt(size)}],
        }
        if et != "MARKET":
            if price is None:
                raise ValueError(f"{et} close requires a price")
            body["price"] = _fmt(price)
        logger.warning("LIVE GMO CLOSE -> {} pos={} {} {} {}", symbol, position_id, s, et, _fmt(size))
        return str(self._post("/v1/closeOrder", body))

    def cancel_bulk(self, symbol: str) -> None:
        """Cancel all active orders for ``symbol`` (``POST /v1/cancelBulkOrder``)."""
        if not self.allow_orders:
            raise PermissionError("Order cancel disabled (allow_orders=False).")
        self._post("/v1/cancelBulkOrder", {"symbols": [symbol]})


def gmo_account_client_from_settings(settings: Settings | None = None) -> GmoClient:
    """Build a live read-only :class:`GmoClient` from the environment.

    Raises:
        RuntimeError: If ``USE_LIVE_API`` is not true (no accidental live calls).
        ValueError: If the GMO key/secret are unset.
    """
    s = settings or get_settings()
    if not s.use_live_api:
        raise RuntimeError(
            "USE_LIVE_API is false — the GMO account client is live-only. Set "
            "USE_LIVE_API=true in .env.dev to enable."
        )
    logger.warning("LIVE GMO account client enabled (read-only)")
    return GmoClient(s.gmo_api_key, s.gmo_api_secret)


def gmo_trading_client_from_settings(settings: Settings | None = None) -> GmoClient:
    """Build an order-capable GMO client — requires ``USE_LIVE_API`` AND ``ALLOW_ORDERS``.

    The trade CLI additionally requires ``--execute``, and size is hard-capped at the
    per-symbol minimum lot inside the client.

    Raises:
        RuntimeError: If ``USE_LIVE_API`` or ``ALLOW_ORDERS`` is not true.
        ValueError: If the GMO key/secret are unset.
    """
    s = settings or get_settings()
    if not s.use_live_api:
        raise RuntimeError("USE_LIVE_API is false — cannot place GMO orders.")
    if not s.allow_orders:
        raise RuntimeError(
            "ALLOW_ORDERS is false — order placement is gated. Set ALLOW_ORDERS=true "
            "in .env.dev (the trade CLI still needs --execute)."
        )
    logger.warning("LIVE GMO TRADING client enabled (orders ALLOWED)")
    return GmoClient(s.gmo_api_key, s.gmo_api_secret, allow_orders=True)
