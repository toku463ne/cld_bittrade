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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

_DEFAULT = Path(__file__).resolve().parents[2] / "logs" / "orders.jsonl"


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


def snapshot(fields: dict[str, Any]) -> None:
    """Append one per-run heartbeat (desired book state) as a JSON line."""
    _append(heartbeat_path(), {"ts": datetime.now(timezone.utc).isoformat(), **fields})
