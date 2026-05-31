"""Simulator, exit-rule and zigzag tests (mock-driven, no DB)."""

from __future__ import annotations

from datetime import datetime, timezone

from src.backtest.zigzag import first_zigzag_peak
from src.core.types import Bar, ExitConfig, ExitReason, Side, Trade
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


def test_trade_cost_deducted_from_pnl_and_return() -> None:
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # entry 100, exit 110, size 0.001, fee 0.001 round-trip -> cost = 100*0.001*0.001*2
    cost = 100.0 * 0.001 * 0.001 * 2.0
    t = Trade(
        side=Side.LONG,
        entry_time=ts,
        entry_price=100.0,
        exit_time=ts,
        exit_price=110.0,
        exit_reason=ExitReason.TAKE_PROFIT,
        size=0.001,
        bars_held=1,
        signal_score=1.0,
        cost=cost,
    )
    assert t.gross_pnl == 10.0 * 0.001
    assert t.pnl == t.gross_pnl - cost
    # Return haircut equals 2*fee_rate of notional = 0.002.
    assert abs(t.gross_return_pct - 0.1) < 1e-12
    assert abs((t.gross_return_pct - t.return_pct) - 0.002) < 1e-12


def test_zero_cost_trade_matches_gross() -> None:
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t = Trade(
        side=Side.SHORT,
        entry_time=ts,
        entry_price=200.0,
        exit_time=ts,
        exit_price=190.0,
        exit_reason=ExitReason.TAKE_PROFIT,
        size=0.001,
        bars_held=1,
        signal_score=1.0,
    )
    assert t.cost == 0.0
    assert t.pnl == t.gross_pnl
    assert t.return_pct == t.gross_return_pct


def test_simulator_applies_round_trip_fee() -> None:
    from src.core.types import Timeframe
    from src.data.ohlcv import aggregate_ticks
    from src.mock.mock_api import MockBitflyerAPI
    from src.simulator import Simulator
    from src.strategy.registry import get_strategy

    api = MockBitflyerAPI(seed=7)
    bars = aggregate_ticks(
        [(t.exec_date, t.price, t.size) for t in api.ticks], Timeframe.M1
    )
    res = Simulator(get_strategy("ema_atr_breakout"), size=0.001, fee_rate=0.001).run(bars)
    assert res.trades, "expected at least one trade from the mock data"
    for tr in res.trades:
        expected = tr.entry_price * 0.001 * 0.001 * 2.0
        assert abs(tr.cost - expected) < 1e-9
        assert abs(tr.pnl - (tr.gross_pnl - tr.cost)) < 1e-9


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
