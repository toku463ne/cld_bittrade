"""Tests for the structured order log."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.execution.order_log import record, snapshot


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


def test_snapshot_writes_sibling_heartbeat(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("ORDER_LOG", str(tmp_path / "orders.jsonl"))
    snapshot({"strategy": "density_pullback_xrp", "symbol": "XRP_JPY", "n_open": 0, "close": 179.0})
    hb = tmp_path / "heartbeat.jsonl"  # sibling of orders.jsonl
    obj = json.loads(hb.read_text().strip())
    assert obj["symbol"] == "XRP_JPY" and obj["n_open"] == 0 and "ts" in obj


def test_settle_order_owners_reads_only_successful_live_placements(
        tmp_path: Path, monkeypatch: Any) -> None:
    from src.execution.order_log import settle_order_owners

    p = tmp_path / "orders.jsonl"
    monkeypatch.setenv("ORDER_LOG", str(p))
    record("BTC_JPY", "place protective STOP close BTC_JPY BUY @ 1.31686e+07 (pos 295008441)",
           execute=True, result="9045381148")
    record("BTC_JPY", "ratchet STOP -> 1.29435e+07 (pos 295008441: cancel 9045381148 + "
           "replace)", execute=True, result="9052800000")
    record("BTC_JPY", "place protective STOP close BTC_JPY BUY @ 1 (pos 5)",
           execute=False, result=None)                                     # dry run
    record("BTC_JPY", "FAILED: ratchet STOP -> 1 (pos 6: cancel 1 + replace)",
           execute=True, result="ERROR: ERR-200")                          # failed
    record("BTC_JPY", "ratchet STOP -> 1 (pos 7: cancel 1 + replace)",
           execute=True, result=None)                                      # pre-fix line
    record("BTC_JPY", "place LIMIT entry BTC_JPY SELL @ 1.3e+07", execute=True, result="42")
    record("XRP_JPY", "place protective STOP close XRP_JPY SELL @ 234 (pos 8)",
           execute=True, result="99")                                      # other symbol
    with p.open("a") as f:
        f.write("not json\n")
    assert settle_order_owners("BTC_JPY") == {9045381148: 295008441, 9052800000: 295008441}


def test_settle_order_owners_without_a_log_is_empty(tmp_path: Path, monkeypatch: Any) -> None:
    from src.execution.order_log import settle_order_owners

    monkeypatch.setenv("ORDER_LOG", str(tmp_path / "missing.jsonl"))
    assert settle_order_owners("BTC_JPY") == {}
