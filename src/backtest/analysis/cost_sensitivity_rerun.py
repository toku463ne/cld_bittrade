"""Re-run zigzag_bounce on deep GMO data across a per-side cost SWEEP.

Motivation: every prior backtest deducted 0.1%/side (0.2% round-trip) — the
bitFlyer SPOT fee, wrongly applied to FX_BTC_JPY, which is **commission-free**
(verified from the API: gettradingcommission returns 0). The real taker cost is
SLIPPAGE (half-spread), ~1-2 bps calm / wider in volatile bursts. Since we have no
order-book history to measure realised spread, we don't guess one number — we
sweep cost ∈ {0, 2, 5, 10 bps/side} and report where the strategy crosses zero,
so the conclusion is read against the assumption, not hidden inside it.

The gap between the 0-bp column (frictionless / upper bound) and the realistic
columns is the alpha that exists before costs; the gap between a taker column and
0 bp is roughly what a MAKER (who earns rather than pays the spread) would recover.

Run: COST_TF=1h uv run --env-file .env.bt python -m src.backtest.analysis.cost_sensitivity_rerun
"""

from __future__ import annotations

import os

from src.backtest.cycle import run_cycle
from src.core.types import Timeframe

_TF = {"1m": Timeframe.M1, "5m": Timeframe.M5, "15m": Timeframe.M15, "1h": Timeframe.H1}
COSTS = [0.0, 0.0002, 0.0005, 0.001]  # per side: frictionless, 2bps, 5bps, 10bps(old)


def main() -> None:
    tf = _TF[os.getenv("COST_TF", "1h")]
    strat = os.getenv("COST_STRAT", "zigzag_bounce")
    product = os.getenv("COST_PRODUCT", "GMO_BTC_JPY")
    print(f"{strat} on {product} {tf.value} — cost sweep (per-side slippage)\n")
    print(f"{'cost/side':>10} {'IS_Sharpe':>10} {'IS_net':>10} {'OOS_Sharpe':>11} "
          f"{'OOS_net':>10} {'IS_trades':>9}")
    print("-" * 64)
    for c in COSTS:
        r = run_cycle(strat, tf, product=product, fee_rate=c)
        print(f"{c*1e4:>8.0f}bp {r.in_sample.sharpe:>10.3f} "
              f"{r.in_sample.total_return:>10.4f} {r.oos.sharpe:>11.3f} "
              f"{r.oos.total_return:>10.4f} {r.in_sample.n_trades:>9}")
    print("\nIS_net/OOS_net are summed per-trade returns (fraction). "
          "Read where Sharpe/net cross 0 vs the assumed slippage.")


if __name__ == "__main__":
    main()
