"""Horizon-matched entry-edge probe for density_breakout (5m/15m).

The sign benchmark scores a fire by the FIRST zigzag swing (~30 bars, first
0.3% move). For a trend-RIDE entry that is designed to sit through an immediate
pullback (far-edge structural stop) and harvest a multi-day move, that horizon
is mismatched — it records the pullback, not the ride. This probe instead
measures the *signed forward return at a fixed horizon* over a range of horizons,
so we can see whether the breakout fire has directional edge at the timescale the
strategy actually trades, with large n on 5m/15m.

For each fire it computes ``signed_fwd = side_sign * (close[t+H]-close[t])/close[t]``
for several H, pooled over the in-sample bars. Reports DR (fraction > 0), mean_r,
and the per-trade Sharpe (mean/std) at each horizon. No exit logic — pure entry
quality.

Usage::

    uv run --env-file .env.bt python -m src.backtest.analysis.entry_horizon_probe \
        --sign density_breakout --timeframe 5m --product GMO_BTC_JPY
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from loguru import logger

from src.backtest.sign_benchmark import split_in_out_sample
from src.core.types import Side, Timeframe
from src.data.cache import load_cache
from src.logging_setup import configure_logging
from src.signs.registry import get_sign

# Horizons in HOURS — converted to bars per timeframe so the comparison is on a
# wall-clock basis across 5m/15m.
HORIZON_HOURS = [1, 4, 12, 48, 96, 168]


def _bars_per_hour(tf: Timeframe) -> float:
    minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}[tf.value]
    return 60.0 / minutes


def run(sign_name: str, tf: Timeframe, *, product: str | None) -> None:
    """Compute pooled fixed-horizon forward-return stats for a sign's fires."""
    cache = load_cache(tf, product=product)
    in_sample, _ = split_in_out_sample(cache.bars)
    df = pd.DataFrame(
        {
            "open": [b.open for b in in_sample],
            "high": [b.high for b in in_sample],
            "low": [b.low for b in in_sample],
            "close": [b.close for b in in_sample],
            "volume": [b.volume for b in in_sample],
        },
        index=pd.DatetimeIndex([b.timestamp for b in in_sample], name="timestamp"),
    )
    closes = df["close"].to_numpy(dtype=float)
    ts_to_idx = {ts: i for i, ts in enumerate(df.index)}

    fires = get_sign(sign_name).detect(df)
    sides = []
    idxs = []
    for f in fires:
        i = ts_to_idx[pd.Timestamp(f.fired_at)]
        idxs.append(i)
        sides.append(1.0 if f.side is Side.LONG else -1.0)
    idxs_a = np.array(idxs)
    sides_a = np.array(sides)
    bph = _bars_per_hour(tf)
    n_total = len(closes)

    logger.info(
        "{} {} — {} fires (in-sample), {} bars", sign_name, tf.value, len(fires), n_total
    )
    logger.info("  horizon |    n |   DR  |  mean_r  | per-trade Sharpe")
    for h in HORIZON_HOURS:
        hb = int(round(h * bph))
        end_idx = idxs_a + hb
        valid = end_idx < n_total
        if not valid.any():
            continue
        ent = closes[idxs_a[valid]]
        ex = closes[end_idx[valid]]
        signed = sides_a[valid] * (ex - ent) / ent
        dr = float((signed > 0).mean())
        mean_r = float(signed.mean())
        sharpe = mean_r / float(signed.std()) if signed.std() > 0 else 0.0
        logger.info(
            "  {:>4}h ({:>4}b) | {:>4} | {:.3f} | {:+.5f} | {:+.4f}",
            h,
            hb,
            int(valid.sum()),
            dr,
            mean_r,
            sharpe,
        )


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Horizon-matched entry-edge probe.")
    parser.add_argument("--sign", required=True)
    parser.add_argument("--timeframe", choices=[tf.value for tf in Timeframe], default="5m")
    parser.add_argument("--product", default=None)
    args = parser.parse_args()
    configure_logging()
    run(args.sign, Timeframe(args.timeframe), product=args.product)


if __name__ == "__main__":
    main()
