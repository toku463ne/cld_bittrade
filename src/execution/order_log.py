"""Append-only structured log of every order action (entry / stop / TP / close / cancel).

One JSON object per line in ``logs/orders.jsonl`` (override with ``ORDER_LOG``):
``{ts, symbol, execute, action, result}``. Records in BOTH dry-run (``execute``
false → intended action) and live (``execute`` true → with the GMO ``result``,
e.g. the orderId), so it is the durable audit trail + the forward record. The
authoritative *fill* record is separately GMO's execution history.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

_DEFAULT = Path(__file__).resolve().parents[2] / "logs" / "orders.jsonl"

# Actions that rest a settle order for ONE named position, e.g.
#   "place protective STOP close BTC_JPY BUY @ 1.31686e+07 (pos 295008441)"
#   "ratchet STOP -> 1.29435e+07 (pos 295008441: cancel 9045381148 + replace)"
_SETTLE_ACTION = re.compile(r"^(?:place protective STOP|place TP LIMIT|ratchet STOP)\b"
                            r".*\(pos (\d+)[:)]")


def log_path() -> Path:
    """Resolve the order-log path (``ORDER_LOG`` env or ``logs/orders.jsonl``)."""
    return Path(os.environ.get("ORDER_LOG") or _DEFAULT)


def heartbeat_path() -> Path:
    """Per-run desired-book snapshots — sibling of the order log."""
    return log_path().parent / "heartbeat.jsonl"


def _append(path: Path, obj: dict[str, Any]) -> None:
    """Append one JSON line. Never raises into the caller (logging != trading)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, default=str) + "\n")
    except OSError as e:
        logger.warning("log write failed ({}): {}", path.name, e)


def record(symbol: str, action: str, *, execute: bool, result: Any = None) -> None:
    """Append one order action (entry/stop/TP/close/cancel) as a JSON line."""
    _append(log_path(), {
        "ts": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "execute": execute,
        "action": action,
        "result": result,
    })


def settle_order_owners(symbol: str) -> dict[int, int]:
    """``{orderId: positionId}`` for every settle order this bot placed on ``symbol``.

    GMO's activeOrders response does not name the position a CLOSE order settles, but
    the bot itself chose it (``settlePosition``) and wrote both ids to this log when it
    placed the order. That record is exact, which price-based attribution is not when
    several positions share one stop level. Only successful live placements count:
    dry-run lines and ``FAILED:`` lines never created an order.

    Args:
        symbol: GMO leverage symbol to filter on.

    Returns:
        The mapping; empty when the log is missing or unreadable (callers then fall back
        to price-based attribution, so a lost log degrades rather than breaks).
    """
    owners: dict[int, int] = {}
    try:
        with log_path().open(encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    if not row.get("execute") or row.get("symbol") != symbol:
                        continue
                    m = _SETTLE_ACTION.match(str(row.get("action", "")))
                    if m is None:
                        continue
                    owners[int(str(row.get("result")))] = int(m.group(1))
                except (ValueError, TypeError, AttributeError):
                    continue  # malformed line or non-numeric result: no claim to record
    except OSError:
        return {}
    return owners


def snapshot(fields: dict[str, Any]) -> None:
    """Append one per-run heartbeat (desired book state) as a JSON line."""
    _append(heartbeat_path(), {"ts": datetime.now(timezone.utc).isoformat(), **fields})
