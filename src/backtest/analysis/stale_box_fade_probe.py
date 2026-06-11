"""Stage-1 edge probe: fade breakouts from STALE value-area boxes (Strategy D).

The anti-density_pullback, built from the base-length diagnostics: breakouts from
mature boxes (long acceptance streaks) run DR 0.12–0.18 on both BTC and ETH — and
``max_base_bars=64`` now makes dp *skip* them. This probe measures the OTHER side:
enter AGAINST the stale-box breakout at the next open, TP at the event-time POC,
SL one box-height beyond entry, time stop 96 bars. Same-bar TP/SL collision books
as SL (pessimistic). Events are independent (no slot/book interaction) — this is
an event-level edge measurement, not a strategy backtest.

Pre-registered kill bars (study plan §D): at the primary cell (streak>48, s=1.0,
BTC+ETH lockbox-IS pooled): mean net > 0 at 4 bp RT in BOTH IS halves, still > 0
at 10 bp RT, worst loss <= 3x median win, regime sub-periods reported, n >= 100.
Both lockbox OOS windows are held out.

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.stale_box_fade_probe
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from src.backtest.sign_benchmark import split_lockbox
from src.core.types import Bar, Timeframe
from src.data.cache import load_cache
from src.indicators.density import time_at_price_profile, value_area
from src.strategy.density_pullback import DensityPullbackStrategy, _recency_weights

PRODUCTS = ("GMO_BTC_JPY", "GMO_ETH_JPY")
THRESHOLDS = (32, 48, 64)
STOPS = (0.5, 1.0, 1.5)
PRIMARY = (48, 1.0)  # (streak threshold, stop mult) — the pre-registered cell
TIME_STOP = 96
FEES_RT = (0.0004, 0.0010)  # 4 bp and 10 bp round-trip, as fractions


@dataclass(slots=True)
class FadeEvent:
    """One stale-box breakout fade, simulated independently."""

    ts: datetime
    streak: int
    side_short: bool  # True = fading an UP-break (short fade)
    ret: dict[float, float]  # stop mult -> gross return (per unit notional)
    reason: dict[float, str]


def _bands_with_poc(
    highs: list[float], lows: list[float], s: DensityPullbackStrategy
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Rolling recency value-area bands + POC (mirrors dp's box, adds the POC)."""
    n = len(highs)
    bl = np.full(n, np.nan)
    bh = np.full(n, np.nan)
    poc = np.full(n, np.nan)
    w = _recency_weights(s.window, s.recency)
    for t in range(s.window, n):
        centers, weights = time_at_price_profile(
            highs[t - s.window : t], lows[t - s.window : t], s.density_bins, weights=w
        )
        p, lo, hi = value_area(centers, weights, s.coverage)
        if hi > lo:
            bl[t], bh[t], poc[t] = lo, hi, p
    return bl, bh, poc


def _events(bars: list[Bar]) -> list[FadeEvent]:
    """Detect stale-box breakouts and simulate the fade at each stop mult."""
    s = DensityPullbackStrategy()  # box geometry source (window/bins/coverage/recency)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    opens = [b.open for b in bars]
    bl, bh, poc = _bands_with_poc(highs, lows, s)

    # acceptance streak (def B): consecutive closes inside their own band.
    streaks: list[int] = []
    st = 0
    for j in range(len(bars)):
        lo_j, hi_j = float(bl[j]), float(bh[j])
        st = st + 1 if (hi_j > lo_j and lo_j <= closes[j] <= hi_j) else 0
        streaks.append(st)

    out: list[FadeEvent] = []
    warmup = s.window + 2
    for t in range(warmup, len(bars) - 1):
        lo, hi, p = float(bl[t]), float(bh[t]), float(poc[t])
        if not (hi > lo):
            continue
        if not (lo <= closes[t - 1] <= hi):
            continue
        c = closes[t]
        if c > hi:
            short = True
        elif c < lo:
            short = False
        else:
            continue
        if (hi - lo) > s.max_band_pct * c:
            continue  # same tight-box condition as dp — the validated event family
        streak = streaks[t - 1]
        if streak <= min(THRESHOLDS):
            continue
        # fade: enter next open against the break; TP at POC, SL k*box beyond entry.
        entry = opens[t + 1]
        box_h = hi - lo
        sign = -1.0 if short else 1.0  # PnL sign for the fade position
        ev = FadeEvent(bars[t].timestamp, streak, short, {}, {})
        for k in STOPS:
            tp = p
            sl = entry + (box_h * k) if short else entry - (box_h * k)
            ret, reason = 0.0, "time"
            for j in range(t + 1, min(t + 1 + TIME_STOP, len(bars))):
                hit_sl = highs[j] >= sl if short else lows[j] <= sl
                hit_tp = lows[j] <= tp if short else highs[j] >= tp
                if hit_sl:  # pessimistic: SL wins same-bar collisions
                    ret, reason = sign * (sl - entry) / entry, "sl"
                    break
                if hit_tp:
                    ret, reason = sign * (tp - entry) / entry, "tp"
                    break
            else:
                j_end = min(t + TIME_STOP, len(bars) - 1)
                ret, reason = sign * (closes[j_end] - entry) / entry, "time"
            ev.ret[k] = ret
            ev.reason[k] = reason
        out.append(ev)
    return out


def _report(events: list[FadeEvent], k: float, fee_rt: float, label: str) -> None:
    if not events:
        print(f"  {label}: n=0")
        return
    r = np.array([e.ret[k] - fee_rt for e in events])
    wins = r[r > 0]
    worst = float(r.min())
    med_win = float(np.median(wins)) if len(wins) else float("nan")
    tail = abs(worst) / med_win if med_win and med_win > 0 else float("inf")
    print(
        f"  {label}: n={len(r)} mean={r.mean():+.5f} DR={(r > 0).mean():.2f} "
        f"sum={r.sum():+.3f} worst={worst:+.4f} medwin={med_win:+.4f} tail={tail:.1f}x"
    )


def main() -> None:
    """Run the probe over both assets' lockbox-IS windows."""
    all_ev: dict[str, list[FadeEvent]] = {}
    for product in PRODUCTS:
        bars = load_cache(Timeframe("1h"), product=product).bars
        is_bars, _ = split_lockbox(bars)  # lockbox OOS held out
        all_ev[product] = _events(is_bars)
        print(f"{product}: IS {is_bars[0].timestamp:%Y-%m-%d}..{is_bars[-1].timestamp:%Y-%m-%d}, "
              f"events(streak>{min(THRESHOLDS)})={len(all_ev[product])}")

    k_primary = PRIMARY[1]
    for thresh in THRESHOLDS:
        print(f"\n=== streak > {thresh} (s={k_primary}, fees 4bp RT) ===")
        pooled: list[FadeEvent] = []
        for product in PRODUCTS:
            ev = [e for e in all_ev[product] if e.streak > thresh]
            pooled.extend(ev)
            _report(ev, k_primary, FEES_RT[0], product)
        _report(pooled, k_primary, FEES_RT[0], "POOLED")
        # early/late halves of the pooled set (by time)
        pooled.sort(key=lambda e: e.ts)
        half = len(pooled) // 2
        _report(pooled[:half], k_primary, FEES_RT[0], "POOLED early-half")
        _report(pooled[half:], k_primary, FEES_RT[0], "POOLED late-half")
        _report(pooled, k_primary, FEES_RT[1], "POOLED @10bp RT")

    # primary cell extras: stop sensitivity + regime sub-periods + exit mix
    print(f"\n=== PRIMARY cell extras (streak>{PRIMARY[0]}) ===")
    pooled = sorted(
        (e for p in PRODUCTS for e in all_ev[p] if e.streak > PRIMARY[0]),
        key=lambda e: e.ts,
    )
    for k in STOPS:
        _report(pooled, k, FEES_RT[0], f"stop={k}")
    for y0, y1, nm in ((2022, 2023, "2022 crash"), (2024, 2025, "2024 bull")):
        seg = [e for e in pooled if y0 <= e.ts.year < y1]
        _report(seg, k_primary, FEES_RT[0], nm)
    from collections import Counter

    mix = Counter(e.reason[k_primary] for e in pooled)
    print(f"  exit mix @s={k_primary}: {dict(mix)}")


if __name__ == "__main__":
    from src.config import get_settings
    from src.logging_setup import configure_logging

    configure_logging(get_settings().log_level)
    main()
