"""Maker viability probe: spread captured vs adverse selection on the real tape.

The maker/market-making pivot's go/no-go question: on commission-free FX_BTC_JPY,
does a passive quoter EARN more spread than it loses to adverse selection (getting
filled by informed flow right before the price moves against it)? If spread >>
adverse selection, market-making is viable; if not, the informed flow eats it.

Measured from the **real bitFlyer trade tape** already collected in the bt DB
(~1.36M executions w/ aggressor side) — no order book, so this uses tape-only
estimators (the standard approach absent full depth):

- **Effective spread**: (a) Roll estimator 2·√(−cov(Δp,Δp₋₁)) from the bid-ask
  bounce, and (b) a direct side-based estimate (|Δprice| across consecutive
  opposite-aggressor trades). A maker round-trip grosses ~the full spread.
- **Adverse selection**: after a fill, the price drift AGAINST the maker over a
  horizon. A SELL-aggressor trade means the maker's resting bid was hit (maker now
  long at the bid); adverse if price then falls. Measured as −E[maker_dir · fwd_ret]
  at several trade-horizons.
- **Net per round-trip ≈ spread − 2·adverse** (rough; ignores queue position and
  inventory). The decision number.

This is a SIGNAL/economics probe, not a strategy. It does not model queue priority
(we have no book) — so realistic fills are *worse* than "filled on any trade-through";
treat the net as an UPPER BOUND on the maker edge.
Run: uv run --env-file .env.bt python -m src.backtest.analysis.maker_spread_probe
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.db import get_engine

PRODUCT = "FX_BTC_JPY"


def main() -> None:
    df = pd.read_sql(
        f"SELECT exec_date, price, size, side FROM execution "
        f"WHERE product = '{PRODUCT}' AND side IS NOT NULL ORDER BY id",
        get_engine(),
    )
    n = len(df)
    p = df["price"].to_numpy(dtype=float)
    side = df["side"].to_numpy()
    mp = float(p.mean())
    span_min = (df["exec_date"].iloc[-1] - df["exec_date"].iloc[0]).total_seconds() / 60.0
    print(f"{PRODUCT} tape: {n:,} trades  {df['exec_date'].iloc[0]} .. "
          f"{df['exec_date'].iloc[-1]}  ({span_min/60/24:.1f} days)")
    print(f"  ~{n/span_min:.0f} trades/min  median size={np.median(df['size']):.4f} BTC  "
          f"mean price={mp:,.0f} JPY\n")

    # --- Effective spread ---
    dp = np.diff(p)
    cov = float(np.cov(dp[1:], dp[:-1])[0, 1])
    roll = 2.0 * np.sqrt(-cov) if cov < 0 else float("nan")
    roll_bps = roll / mp * 1e4
    flip = side[1:] != side[:-1]
    direct = np.abs(dp)[flip]
    direct_bps = float(np.median(direct)) / mp * 1e4
    print(f"effective spread:  Roll={roll_bps:.2f} bp   side-based(median)={direct_bps:.2f} bp "
          f"  half-spread≈{direct_bps/2:.2f} bp")

    # --- Adverse selection at several trade-horizons ---
    # maker_dir: a SELL-aggressor trade hits the maker's bid -> maker long (+1);
    # a BUY-aggressor trade lifts the maker's ask -> maker short (-1).
    maker_dir = np.where(side == "SELL", 1.0, -1.0)
    print(f"\n{'horizon':>8} {'adverse(bp)':>12} {'net≈spread−2·adv(bp)':>22}")
    print("-" * 44)
    for H in (5, 20, 100, 500):
        fwd = (p[H:] - p[:-H]) / p[:-H]
        maker_fwd = maker_dir[:-H] * fwd
        adv_bp = -float(maker_fwd.mean()) * 1e4   # >0 = price moved against fills
        net = direct_bps - 2.0 * adv_bp
        print(f"{H:>8} {adv_bp:>12.2f} {net:>22.2f}")
    print("\nViable only if net > 0 at a horizon matching realistic quote lifetime. "
          "Net is an UPPER BOUND (no queue priority modelled).")


if __name__ == "__main__":
    main()
