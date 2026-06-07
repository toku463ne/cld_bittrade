"""Probe: does price BOUNCE at prior zigzag levels on DAILY candles? (DR/EV only)

zigzag_bounce on 1h was a coin flip (DR 0.511). Before reworking its entry into a
maker limit-at-the-level (the user's idea), test whether the *signal* even has a
directional edge on DAILY levels — major daily S/R may behave differently than 1h
micro-levels. This measures the SIGNAL only (DR / mean signed return); it does NOT
model limit fills or maker economics (that needs order-book data — adverse
selection on resting limits cannot be captured from OHLC).

Event (causal): at bar t, price re-reaches a prior CONFIRMED same-type zigzag peak
(the "wall") within ``tol`` for the first time (fresh approach) —
- reach a prior HIGH from below  -> expected rejection -> SHORT
- reach a prior LOW  from above   -> expected bounce    -> LONG
Confirmed peaks are used only from their causal ``known_at`` (idx+size) bar.

Outcome: signed return over the next ``K`` daily bars, ``side·(close[t+K]−close[t])
/close[t]``. DR = fraction > 0 (bounced in the expected direction); mean_r = EV per
event. Compared against the unconditional K-bar drift (the honest baseline, since
BTC trended up). MATERIAL only if DR ≥ ~56% at n ≥ 100 (per evaluation_criteria.md).

Run: uv run --env-file .env.bt python -m src.backtest.analysis.daily_bounce_signal_probe
"""

from __future__ import annotations

import numpy as np

from src.backtest.analysis.daily_momentum_probe import to_daily
from src.backtest.analysis.trendline_fan_probe import CPeak, confirmed_peaks

SIZE = 10       # daily swing scale for a confirmed peak (±10 days)
WIN = 120       # wall lookback (days) — a level is "recent" within this window


def _events(
    highs: list[float], lows: list[float], t: int,
    walls_hi: list[CPeak], walls_lo: list[CPeak], tol: float,
) -> tuple[int, float] | None:
    """Return (side, wall_price) if bar t freshly reaches a prior wall, else None."""
    cand = [p for p in walls_hi if p.known_at <= t and t - WIN <= p.idx < t]
    if cand:
        w = min(cand, key=lambda p: abs(p.price - highs[t]))
        band = tol * w.price
        if abs(highs[t] - w.price) <= band and highs[t - 1] < w.price - band:
            return -1, w.price  # reached resistance from below -> SHORT
    cand = [p for p in walls_lo if p.known_at <= t and t - WIN <= p.idx < t]
    if cand:
        w = min(cand, key=lambda p: abs(p.price - lows[t]))
        band = tol * w.price
        if abs(lows[t] - w.price) <= band and lows[t - 1] > w.price + band:
            return 1, w.price  # reached support from above -> LONG
    return None


def main() -> None:
    d = to_daily()
    highs = d["high"].tolist()
    lows = d["low"].tolist()
    closes = d["close"].to_numpy(dtype=float)
    n = len(closes)
    cp = confirmed_peaks(highs, lows, size=SIZE)
    walls_hi = [p for p in cp if p.is_high]
    walls_lo = [p for p in cp if not p.is_high]
    print(f"GMO daily: {n} bars  {d.index[0]:%Y-%m-%d}..{d.index[-1]:%Y-%m-%d}  "
          f"confirmed peaks={len(cp)} (size={SIZE})\n")

    print(f"{'tol':>5} {'K':>3} {'n':>4} {'DR':>6} {'mean_r':>8} {'base_DR':>8} "
          f"{'n_short':>8} {'DR_sh':>6} {'n_long':>7} {'DR_lg':>6}")
    print("-" * 70)
    for tol in (0.005, 0.01, 0.02):
        for K in (3, 5, 10):
            rows: list[tuple[int, float]] = []
            for t in range(SIZE + 1, n - K):
                ev = _events(highs, lows, t, walls_hi, walls_lo, tol)
                if ev is None:
                    continue
                side, _ref = ev
                r = side * (closes[t + K] - closes[t]) / closes[t]
                rows.append((side, r))
            if not rows:
                continue
            rs = np.array([r for _, r in rows])
            sh = np.array([r for s, r in rows if s == -1])
            lg = np.array([r for s, r in rows if s == 1])
            # Unconditional baseline DR for the SAME directional mix (short events
            # want price down, long events up): drift over all bars at horizon K.
            drift = (closes[K:] - closes[:-K]) / closes[:-K]
            base_dr = (
                (len(sh) * float((-drift > 0).mean()) + len(lg) * float((drift > 0).mean()))
                / len(rows)
            )
            print(f"{tol*100:>4.1f}% {K:>3} {len(rs):>4} {float((rs>0).mean()):>6.3f} "
                  f"{rs.mean()*100:>7.3f}% {base_dr:>8.3f} "
                  f"{len(sh):>8} {float((sh>0).mean()) if sh.size else 0:>6.3f} "
                  f"{len(lg):>7} {float((lg>0).mean()) if lg.size else 0:>6.3f}")
    print("\nMaterial only if DR ≥ ~0.56 at n ≥ 100 AND clearly above base_DR. "
          "Signal only — does NOT model limit fills / adverse selection.")


if __name__ == "__main__":
    main()
