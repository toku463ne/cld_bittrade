"""Probe: multi-position dense-breakout with dense-aware exits.

Tests the user's idea (2026-06-04): make the dense band *closer* so MORE small
intra-trend consolidations register as breakout entries, hold several overlapping
positions (slots), and exit each position when it "faces another dense" — either

  (1) a fresh tight box forms at the new level (the trend stalled into a new
      consolidation), OR
  (3) price reaches the next *pre-existing* dense zone (a target read from a
      longer-window profile at entry),

whichever comes first, on top of the far-edge structural stop and a time stop.

This is isolated from the shipping ``density_breakout`` sign/strategy and the
single-position :class:`~src.simulator.simulator.Simulator` (which drops signals
that fire while a position is open, so it cannot test "more entries"). It sweeps
``window`` x ``max_band_pct`` and reports IS/OOS portfolio metrics vs
buy-and-hold, plus how many fires were generated vs actually taken given the slot
cap.

Exit-reason coding in the output mix: ``stop_loss`` = far-edge structural stop,
``take_profit`` = reached the pre-existing dense target, ``trail_stop`` = stall
(new tight box formed), ``time_stop`` = time backstop, ``end_of_data`` = forced
close at the sample boundary.

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.density_multi_probe

Env knobs: ``DM_TF`` (default 1h), ``DM_PRODUCT`` (default GMO_BTC_JPY),
``DM_SLOTS`` (5), ``DM_UNIT`` (0.001), ``DM_TIMESTOP`` (120),
``DM_TARGET_WINDOW`` (336), ``DM_SL_BUFFER`` (0.10), ``DM_MINHOLD`` (6).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
from loguru import logger

from src.backtest.metrics import buy_and_hold_return, max_drawdown, portfolio_metrics
from src.backtest.sign_benchmark import split_in_out_sample
from src.core.types import Bar, ExitReason, Side, Timeframe, Trade
from src.data.cache import load_cache
from src.indicators.density import time_at_price_profile, value_area
from src.simulator.simulator import DEFAULT_FEE_RATE

# Grid the user chose (2026-06-04).
WINDOWS = (24, 48, 72, 168)
MAX_BAND_PCTS = (0.015, 0.02, 0.03, 0.05)


@dataclass(frozen=True, slots=True)
class Config:
    """Probe configuration for one grid cell."""

    window: int
    max_band_pct: float
    n_bins: int = 48
    coverage: float = 0.70
    max_slots: int = 5
    unit: float = 0.001
    fee_rate: float = DEFAULT_FEE_RATE
    sl_buffer: float = 0.10
    time_stop_bars: int = 120
    min_hold: int = 6
    target_window: int = 336
    target_min_frac: float = 0.40  # a target node must be >= this x the POC weight


@dataclass(slots=True)
class _Pos:
    """An open position in the multi-slot book."""

    side: Side
    entry_price: float
    entry_time: object
    entry_idx: int
    stop: float
    target: float | None
    band_h: float


def _precompute_bands(
    highs: list[float], lows: list[float], window: int, n_bins: int, coverage: float
) -> tuple[np.ndarray, np.ndarray]:
    """Value-area band over ``[t-window, t-1]`` for every bar ``t`` (NaN if short)."""
    n = len(highs)
    bl = np.full(n, np.nan)
    bh = np.full(n, np.nan)
    for t in range(window, n):
        centers, weights = time_at_price_profile(highs[t - window : t], lows[t - window : t], n_bins)
        _poc, lo, hi = value_area(centers, weights, coverage)
        if hi > lo:
            bl[t] = lo
            bh[t] = hi
    return bl, bh


def _next_dense(
    highs: list[float], lows: list[float], e: int, edge: float, side: Side, cfg: Config
) -> float | None:
    """Nearest pre-existing dense node beyond ``edge`` (the target), or ``None``."""
    w0 = max(0, e - cfg.target_window)
    if e - w0 < 10:
        return None
    centers, weights = time_at_price_profile(highs[w0:e], lows[w0:e], cfg.n_bins)
    mask = centers > edge if side is Side.LONG else centers < edge
    if not mask.any():
        return None
    w = weights[mask]
    if w.max() < cfg.target_min_frac * float(weights.max() or 0.0) or w.max() <= 0.0:
        return None
    return float(centers[mask][int(w.argmax())])


def _entry_at(
    t: int, closes: list[float], bl: np.ndarray, bh: np.ndarray, cfg: Config
) -> tuple[Side, float, float] | None:
    """A breakout entry at bar ``t`` (matches the sign at confirm_bars=1), or None.

    Returns ``(side, band_lo, band_hi)``.
    """
    if t < cfg.window or t < 1:
        return None
    lo, hi = bl[t], bh[t]
    if not (hi > lo):  # NaN-safe
        return None
    prev = closes[t - 1]
    if not (lo <= prev <= hi):
        return None
    if (hi - lo) > cfg.max_band_pct * closes[t]:  # tight-box filter
        return None
    if closes[t] > hi:
        return Side.LONG, lo, hi
    if closes[t] < lo:
        return Side.SHORT, lo, hi
    return None


def _check_exit(
    p: _Pos, t: int, bar: Bar, closes: list[float], bl: np.ndarray, bh: np.ndarray, cfg: Config
) -> tuple[ExitReason, float] | None:
    """First exit condition hit on bar ``t`` (stop > target > stall > time)."""
    if p.side is Side.LONG:
        if bar.low <= p.stop:
            return ExitReason.STOP_LOSS, p.stop
        if p.target is not None and bar.high >= p.target:
            return ExitReason.TAKE_PROFIT, p.target
    else:
        if bar.high >= p.stop:
            return ExitReason.STOP_LOSS, p.stop
        if p.target is not None and bar.low <= p.target:
            return ExitReason.TAKE_PROFIT, p.target

    held = t - p.entry_idx
    if held >= cfg.min_hold:  # stall: a fresh tight box at a new level
        lo, hi = bl[t], bh[t]
        c = closes[t]
        if hi > lo and (hi - lo) <= cfg.max_band_pct * c and lo <= c <= hi:
            if abs(0.5 * (lo + hi) - p.entry_price) > p.band_h:  # genuinely a new box
                return ExitReason.TRAIL_STOP, bar.close
    if held >= cfg.time_stop_bars:
        return ExitReason.TIME_STOP, bar.close
    return None


def simulate(
    bars: list[Bar], bl: np.ndarray, bh: np.ndarray, cfg: Config
) -> tuple[list[Trade], int, list[float]]:
    """Run the multi-position book over ``bars``.

    Returns ``(trades, n_fires, equity)`` where ``equity[t]`` is the
    mark-to-market net PnL in JPY (realised + unrealised on open slots) at the
    close of bar ``t`` — the basis for a time-based (not per-trade) Sharpe/DD.
    """
    n = len(bars)
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    trades: list[Trade] = []
    book: list[_Pos] = []
    pending: tuple[Side, float, float] | None = None
    n_fires = 0
    realised = 0.0
    equity: list[float] = []

    for t in range(n):
        bar = bars[t]
        # 1. Exits on the current bar.
        survivors: list[_Pos] = []
        for p in book:
            ex = _check_exit(p, t, bar, closes, bl, bh, cfg)
            if ex is None:
                survivors.append(p)
            else:
                reason, price = ex
                tr = _mk_trade(p, bar, price, reason, t, cfg)
                trades.append(tr)
                realised += tr.pnl
        book = survivors

        # 2. Fill the pending entry at this bar's open (two-bar rule) if a slot is free.
        if pending is not None and len(book) < cfg.max_slots:
            side, band_lo, band_hi = pending
            band_h = band_hi - band_lo
            near = band_hi if side is Side.LONG else band_lo
            far = band_lo if side is Side.LONG else band_hi
            stop = (far - cfg.sl_buffer * band_h) if side is Side.LONG else (far + cfg.sl_buffer * band_h)
            target = _next_dense(highs, lows, t, near, side, cfg)
            book.append(
                _Pos(side, bar.open, bar.timestamp, t, stop, target, band_h)
            )
        pending = None

        # 3. Detect a new fire at this bar -> pending for next bar.
        sig = _entry_at(t, closes, bl, bh, cfg)
        if sig is not None:
            n_fires += 1
            pending = sig

        # Mark-to-market: realised + unrealised on the open book at this close.
        unreal = sum(p.side.sign * (bar.close - p.entry_price) * cfg.unit for p in book)
        equity.append(realised + unreal)

    # Force-close anything still open at the sample boundary.
    if book and bars:
        last = bars[-1]
        for p in book:
            tr = _mk_trade(p, last, last.close, ExitReason.END_OF_DATA, n - 1, cfg)
            trades.append(tr)
            realised += tr.pnl
        if equity:
            equity[-1] = realised
    return trades, n_fires, equity


def _mk_trade(p: _Pos, bar: Bar, price: float, reason: ExitReason, t: int, cfg: Config) -> Trade:
    cost = p.entry_price * cfg.unit * cfg.fee_rate * 2.0
    return Trade(
        side=p.side,
        entry_time=p.entry_time,  # type: ignore[arg-type]
        entry_price=p.entry_price,
        exit_time=bar.timestamp,
        exit_price=price,
        exit_reason=reason,
        size=cfg.unit,
        bars_held=max(1, t - p.entry_idx),
        signal_score=1.0,
        cost=cost,
    )


def _payoff(trades: list[Trade]) -> float:
    rets = np.array([t.return_pct for t in trades], dtype=float)
    wins = rets[rets > 0]
    losses = rets[rets < 0]
    if wins.size == 0 or losses.size == 0:
        return float("nan")
    return float(wins.mean() / -losses.mean())


def _exit_mix(trades: list[Trade]) -> str:
    if not trades:
        return ""
    from collections import Counter

    c = Counter(t.exit_reason.value for t in trades)
    n = len(trades)
    order = ["stop_loss", "take_profit", "trail_stop", "time_stop", "end_of_data"]
    return " ".join(f"{k[:4]}={c[k] / n:.0%}" for k in order if c.get(k))


def _net_jpy(trades: list[Trade]) -> float:
    return float(sum(t.pnl for t in trades))


def _equity_sharpe(equity: list[float], periods_per_year: float) -> tuple[float, float]:
    """Annualised Sharpe and max drawdown (JPY) of the mark-to-market PnL stream."""
    if len(equity) < 3:
        return 0.0, 0.0
    rets = np.diff(np.asarray(equity, dtype=float))
    sd = float(rets.std(ddof=1))
    sharpe = float(rets.mean() / sd * np.sqrt(periods_per_year)) if sd > 0 else 0.0
    return sharpe, max_drawdown(equity)


def run_grid() -> None:
    """Sweep window x max_band_pct and print IS/OOS metrics."""
    tf = Timeframe(os.environ.get("DM_TF", "1h"))
    product = os.environ.get("DM_PRODUCT", "GMO_BTC_JPY")
    slots = int(os.environ.get("DM_SLOTS", 5))
    unit = float(os.environ.get("DM_UNIT", 0.001))
    time_stop = int(os.environ.get("DM_TIMESTOP", 120))
    target_window = int(os.environ.get("DM_TARGET_WINDOW", 336))
    sl_buffer = float(os.environ.get("DM_SL_BUFFER", 0.10))
    min_hold = int(os.environ.get("DM_MINHOLD", 6))

    bars = load_cache(tf, product=product).bars
    if not bars:
        raise RuntimeError(f"No {tf.value} bars for {product}.")
    in_bars, oos_bars = split_in_out_sample(bars)
    bench = buy_and_hold_return(bars[0].close, bars[-1].close)
    logger.info(
        "density_multi_probe {} {}: {} bars (IS {}, OOS {}), B&H={:+.3f}, slots={}",
        product, tf.value, len(bars), len(in_bars), len(oos_bars), bench, slots,
    )

    in_h = [b.high for b in in_bars]
    in_l = [b.low for b in in_bars]
    oos_h = [b.high for b in oos_bars]
    oos_l = [b.low for b in oos_bars]

    ppy = (365 * 24 * 3600) / tf.seconds
    print(f"\n=== density_multi_probe  {product} {tf.value}  B&H={bench:+.3f}  "
          f"slots={slots} time_stop={time_stop} ===")
    print("(eqSh = ANNUALISED Sharpe of the mark-to-market equity = the portfolio "
          "metric for overlapping slots; perSh = per-trade Sharpe, diagnostic)")
    results: list[tuple[float, str, float, float, float, float]] = []
    for window in WINDOWS:
        bl_in, bh_in = _precompute_bands(in_h, in_l, window, 48, 0.70)
        bl_oos, bh_oos = _precompute_bands(oos_h, oos_l, window, 48, 0.70)
        for mbp in MAX_BAND_PCTS:
            cfg = Config(
                window=window, max_band_pct=mbp, max_slots=slots, unit=unit,
                time_stop_bars=time_stop, target_window=target_window,
                sl_buffer=sl_buffer, min_hold=min_hold,
            )
            tr_in, f_in, eq_in = simulate(in_bars, bl_in, bh_in, cfg)
            tr_oos, f_oos, eq_oos = simulate(oos_bars, bl_oos, bh_oos, cfg)
            m_in = portfolio_metrics(tr_in)
            m_oos = portfolio_metrics(tr_oos)
            es_in, edd_in = _equity_sharpe(eq_in, ppy)
            es_oos, edd_oos = _equity_sharpe(eq_oos, ppy)
            tag = f"w={window} mbp={mbp}"
            print(f"\n{tag}")
            print(f"  IS  n={m_in.n_trades:>4}/{f_in:<4} eqSh={es_in:+.2f} eqDD={edd_in:6.0f}JPY "
                  f"perSh={m_in.sharpe:+.3f} win={m_in.win_rate:.0%} payoff={_payoff(tr_in):.2f} "
                  f"net={_net_jpy(tr_in):+8.0f}JPY mix[{_exit_mix(tr_in)}]")
            print(f"  OOS n={m_oos.n_trades:>4}/{f_oos:<4} eqSh={es_oos:+.2f} eqDD={edd_oos:6.0f}JPY "
                  f"perSh={m_oos.sharpe:+.3f} win={m_oos.win_rate:.0%} payoff={_payoff(tr_oos):.2f} "
                  f"net={_net_jpy(tr_oos):+8.0f}JPY mix[{_exit_mix(tr_oos)}]")
            results.append((es_in + es_oos, tag, es_in, es_oos, _net_jpy(tr_in), _net_jpy(tr_oos)))

    print("\n--- top cells by IS+OOS equity-Sharpe (both must be > 0 to be a real edge) ---")
    for score, tag, es_in, es_oos, net_in, net_oos in sorted(results, reverse=True)[:6]:
        flag = "  <-- both positive" if (es_in > 0 and es_oos > 0) else ""
        print(f"  {tag:<18} eqSh IS={es_in:+.2f} OOS={es_oos:+.2f} sum={score:+.2f}  "
              f"net IS={net_in:+.0f} OOS={net_oos:+.0f}{flag}")


if __name__ == "__main__":
    from src.config import get_settings
    from src.logging_setup import configure_logging

    configure_logging(get_settings().log_level)
    run_grid()
