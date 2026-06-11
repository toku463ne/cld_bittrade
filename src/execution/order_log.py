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


def record(symbol: str, action: str, *, execute: bool, result: Any = None) -> None:
    """Append one order action as a JSON line. Never raises into the caller."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "execute": execute,
        "action": action,
        "result": result,
    }
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError as e:  # logging must never break trading
        logger.warning("order_log write failed: {}", e)
