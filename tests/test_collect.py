"""Tests for execution-date parsing (mock + live timestamp shapes)."""

from __future__ import annotations

from datetime import timezone

from src.data.collect import _parse_exec_date


def test_parses_live_7digit_fraction_with_z() -> None:
    dt = _parse_exec_date("2024-05-31T12:34:56.1234567Z")
    assert dt.tzinfo == timezone.utc
    assert dt.year == 2024 and dt.microsecond == 123456


def test_parses_mock_3digit_fraction() -> None:
    dt = _parse_exec_date("2026-01-01T00:00:00.000")
    assert dt.tzinfo == timezone.utc
    assert dt.microsecond == 0


def test_parses_no_fraction() -> None:
    dt = _parse_exec_date("2024-05-31T12:34:56")
    assert dt.tzinfo == timezone.utc
    assert dt.hour == 12 and dt.second == 56
