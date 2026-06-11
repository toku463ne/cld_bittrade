"""Tests for the structured order log."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.execution.order_log import record


def test_record_appends_json_line(tmp_path: Path, monkeypatch: Any) -> None:
    p = tmp_path / "sub" / "orders.jsonl"
    monkeypatch.setenv("ORDER_LOG", str(p))
    record("XRP_JPY", "place LIMIT entry XRP_JPY SELL @ 179.5", execute=False)
    record("XRP_JPY", "place protective STOP", execute=True, result="ORD123")

    lines = p.read_text().strip().splitlines()
    assert len(lines) == 2
    first, second = json.loads(lines[0]), json.loads(lines[1])
    assert first["symbol"] == "XRP_JPY" and first["execute"] is False and first["result"] is None
    assert "entry" in first["action"] and "ts" in first
    assert second["execute"] is True and second["result"] == "ORD123"
