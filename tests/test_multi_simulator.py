"""Tests for MultiSimulator's ``tp_at_next_open`` venue-fidelity flag."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.core.types import Bar, ExitConfig, ExitReason, Side, Signal
from src.simulator import MultiSimulator
from src.strategy.base import Strategy

_T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _bar(i: int, o: float, h: float, low: float, c: float) -> Bar:
    return Bar(timestamp=_T0 + timedelta(hours=i), open=o, high=h, low=low, close=c,
               volume=1.0)


class _OneLongWithTarget(Strategy):
    """Enters LONG once on the first bar with a +5% target and a far-away stop."""

    name = "_one_long_with_target"
    max_slots = 1

    def precompute(self, bars: list[Bar]) -> dict[object, Signal] | None:  # type: ignore[override]
        cfg = ExitConfig(tp_pct=0.05, sl_pct=0.50)
        first = bars[0]
        return {first.timestamp: Signal(side=Side.LONG, timestamp=first.timestamp,
                                        price=first.close, exit_config=cfg)}

    def on_bar(self, bar: Bar) -> Signal | None:
        return None

    def get_exit_rules(self) -> ExitConfig:
        return ExitConfig(tp_pct=0.05, sl_pct=0.50)


# Entry fills at bar 1's open (100). Bar 2 spikes through the 105 target and falls back;
# bar 3 opens at 98 — so the intrabar fill (105) and the next-open fill (98) are clearly
# distinguishable, and the venue rule is unambiguously the worse one here.
_BARS = [_bar(0, 100, 100, 100, 100), _bar(1, 100, 100, 100, 100),
         _bar(2, 100, 110, 99, 100), _bar(3, 98, 99, 97, 98), _bar(4, 98, 99, 97, 98)]


def _tp_trades(res: object) -> list[object]:
    return [t for t in res.trades if t.exit_reason is ExitReason.TAKE_PROFIT]  # type: ignore[attr-defined]


def test_take_profit_fills_intrabar_at_the_target_by_default() -> None:
    # The default MUST stay the historical behaviour: changing it would silently move
    # every committed benchmark number.
    res = MultiSimulator(_OneLongWithTarget(), size=1.0, fee_rate=0.0).run(_BARS)
    tp = _tp_trades(res)
    assert len(tp) == 1
    assert tp[0].exit_price == 105.0  # type: ignore[attr-defined]


def test_tp_at_next_open_defers_the_exit_to_the_next_bars_open() -> None:
    """GMO allows ONE resting settle order per 建玉 and the STOP holds it.

    Confirmed live 2026-08-06 07:05 (BTC pos 289850034): the take-profit that followed
    the accepted STOP returned ERR-200. So a target touch is not filled intrabar — the
    strategy drops the position at the bar close and the hourly reconcile market-closes
    it ~5 min into the next bar, i.e. at that bar's open.
    """
    res = MultiSimulator(_OneLongWithTarget(), size=1.0, fee_rate=0.0,
                         tp_at_next_open=True).run(_BARS)
    tp = _tp_trades(res)
    assert len(tp) == 1
    assert tp[0].exit_price == 98.0  # type: ignore[attr-defined]


def test_deferred_take_profit_is_strictly_worse_here_and_holds_the_slot_longer() -> None:
    base = MultiSimulator(_OneLongWithTarget(), size=1.0, fee_rate=0.0).run(_BARS)
    venue = MultiSimulator(_OneLongWithTarget(), size=1.0, fee_rate=0.0,
                           tp_at_next_open=True).run(_BARS)
    b, v = _tp_trades(base)[0], _tp_trades(venue)[0]
    assert v.pnl < b.pnl  # type: ignore[attr-defined]
    # The extra bar of exposure is live-accurate: the position really is still open
    # until the reconcile, so it keeps occupying its slot and can block an entry.
    assert v.bars_held > b.bars_held  # type: ignore[attr-defined]


def test_flag_is_inert_when_nothing_exits_on_a_target() -> None:
    # A book whose targets never fire must be byte-identical under the flag.
    flat = [_bar(i, 100, 100.5, 99.5, 100) for i in range(6)]
    base = MultiSimulator(_OneLongWithTarget(), size=1.0, fee_rate=0.0).run(flat)
    venue = MultiSimulator(_OneLongWithTarget(), size=1.0, fee_rate=0.0,
                           tp_at_next_open=True).run(flat)
    assert [t.exit_price for t in base.trades] == [t.exit_price for t in venue.trades]
    assert [t.pnl for t in base.trades] == [t.pnl for t in venue.trades]
