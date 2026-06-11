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

    # ---- order placement — deliberately disabled (read-only phase) -----------

    def send_order(self, *_args: Any, **_kwargs: Any) -> None:
        """Refuses while read-only — order placement arrives in the order phase.

        Raises:
            NotImplementedError: Always, in this read-only build. GMO leverage
                orders (``POST /v1/order``, side BUY/SELL to open; close via
                ``/v1/closeOrder``) will be added behind the same allow_orders +
                min-lot guards as the bitFlyer client, in a separate reviewed change.
        """
        raise NotImplementedError(
            "GMO order placement not enabled in the read-only build. Verify reads "
            "first (python -m src.execution.gmo_account), then add orders behind guards."
        )


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
