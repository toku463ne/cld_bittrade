"""Simulator, exit-rule and zigzag tests (mock-driven, no DB)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.backtest.zigzag import first_zigzag_peak
from src.core.types import Bar, ExitConfig, ExitReason, Side
from src.exit.rules import OpenPosition, evaluate_exit


def _bar(ts: datetime, o: float, h: float, low: float, c: float) -> Bar:
    return Bar(ts, o, h, low, c, 1.0)


def test_take_profit_triggers_on_high() -> None:
    pos = OpenPosition(side=Side.LONG, entry_price=100.0, entry_atr=1.0)
    cfg = ExitConfig(tp_atr_mult=1.5, sl_atr_mult=0.8)
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # High reaches entry + 1.5*ATR = 101.5, low stays above SL (99.2).
    res = evaluate_exit(pos, _bar(ts, 100.0, 101.6, 99.5, 101.0), cfg)
    assert res is not None and res[0] is ExitReason.TAKE_PROFIT


def test_stop_loss_checked_before_take_profit() -> None:
    pos = OpenPosition(side=Side.LONG, entry_price=100.0, entry_atr=1.0)
    cfg = ExitConfig(tp_atr_mult=1.5, sl_atr_mult=0.8)
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # Bar spans both TP (101.5) and SL (99.2); SL must win (pessimistic).
    res = evaluate_exit(pos, _bar(ts, 100.0, 101.6, 99.0, 100.5), cfg)
    assert res is not None and res[0] is ExitReason.STOP_LOSS


def test_time_stop_after_n_bars() -> None:
    pos = OpenPosition(side=Side.LONG, entry_price=100.0, entry_atr=1.0)
    pos.bars_held = 5
    cfg = ExitConfig(time_stop_bars=5)
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    res = evaluate_exit(pos, _bar(ts, 100.0, 100.2, 99.9, 100.1), cfg)
    assert res is not None and res[0] is ExitReason.TIME_STOP
    assert res[1] == 100.1  # exits at close


def test_zigzag_detects_up_swing() -> None:
    closes = [100.0] + [100.0 + i for i in range(1, 20)]  # steady rise
    out = first_zigzag_peak(closes, 0, window=30, threshold=0.003)
    assert out.trend_dir == 1
    assert out.signed_return > 0.0


def test_zigzag_detects_down_swing() -> None:
    closes = [100.0] + [100.0 - i for i in range(1, 20)]  # steady fall
    out = first_zigzag_peak(closes, 0, window=30, threshold=0.003)
    assert out.trend_dir == -1
    assert out.signed_return < 0.0
