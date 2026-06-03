"""One-entry-per-dense (band dedup) sweep vs cost, for density_multi.

The chart showed a single breakout re-firing into several stacked LONG slots from
the *same* dense box (price pulls back in and breaks out again, or the trailing
band drifts). This tests a per-side **band dedup**: suppress a same-side re-entry
until the band center has moved ≥ ``dedup_band_frac × band_height`` from the last
accepted same-side entry — i.e. "one entry per side per dense box".

Anchored on the shipped config (w=168, mbp=0.03, 5 slots,
``target_min_dist_frac=1.5``). Sweeps ``dedup_band_frac`` × round-trip cost,
reporting the annualised mark-to-market equity Sharpe and trade counts so the
correlated-stacking reduction is visible.

Run::

    uv run --env-file .env.bt python -m src.backtest.analysis.density_multi_dedup
"""

from __future__ import annotations

import os
from dataclasses import replace

from loguru import logger

from src.backtest.analysis.density_multi_probe import (
    Config,
    _equity_sharpe,
    _precompute_bands,
    simulate,
)
from src.backtest.sign_benchmark import split_in_out_sample
from src.core.types import Timeframe
from src.data.cache import load_cache

WINDOW = 168
MAX_BAND_PCT = 0.03
FEES = (0.0002, 0.001, 0.002)  # per side; round-trip = 2x
DEDUPS = (0.0, 0.5, 1.0, 1.5, 2.0)


def run() -> None:
    """Sweep dedup_band_frac x cost and print equity-Sharpe + trade counts."""
    tf = Timeframe(os.environ.get("DM_TF", "1h"))
    product = os.environ.get("DM_PRODUCT", "GMO_BTC_JPY")
    ppy = (365 * 24 * 3600) / tf.seconds

    bars = load_cache(tf, product=product).bars
    if not bars:
        raise RuntimeError(f"No {tf.value} bars for {product}.")
    in_bars, oos_bars = split_in_out_sample(bars)
    logger.info("dedup sweep {} {}: precomputing w={} bands", product, tf.value, WINDOW)
    bl_in, bh_in = _precompute_bands([b.high for b in in_bars], [b.low for b in in_bars], WINDOW, 48, 0.70)
    bl_oos, bh_oos = _precompute_bands([b.high for b in oos_bars], [b.low for b in oos_bars], WINDOW, 48, 0.70)

    base = Config(
        window=WINDOW, max_band_pct=MAX_BAND_PCT, max_slots=5,
        use_target=True, target_min_dist_frac=1.5,
    )
    print(f"\n=== density_multi band-dedup vs cost  {product} {tf.value} "
          f"(w={WINDOW} mbp={MAX_BAND_PCT} 5 slots, target dist 1.5)  [B&H IS eqSh +0.64] ===")
    print("    persistent = no same-side re-entry until band moves; concurrent = only one OPEN per box")

    for concurrent in (False, True):
        mode = "concurrent" if concurrent else "persistent"
        print(f"\n--- mode: {mode} ---")
        for dedup in DEDUPS:
            cfg0 = replace(base, dedup_band_frac=dedup, dedup_concurrent=concurrent, fee_rate=0.0002)
            tr_in0, fires_in, _eq = simulate(in_bars, bl_in, bh_in, cfg0)
            tr_oos0, fires_oos, _eq2 = simulate(oos_bars, bl_oos, bh_oos, cfg0)
            tag = "off" if dedup == 0.0 else f"{dedup}"
            row = []
            for fee in FEES:
                cfg = replace(cfg0, fee_rate=fee)
                _ti, _fi, eq_in = simulate(in_bars, bl_in, bh_in, cfg)
                _to, _fo, eq_oos = simulate(oos_bars, bl_oos, bh_oos, cfg)
                row.append((_equity_sharpe(eq_in, ppy)[0], _equity_sharpe(eq_oos, ppy)[0]))
            cells = "  ".join(f"{int(f * 2e4)}bp IS{a:+.2f}/OOS{b:+.2f}" for f, (a, b) in zip(FEES, row, strict=True))
            print(f"  dedup={tag:>4}  trIS={len(tr_in0):>3} trOOS={len(tr_oos0):>3}  | {cells}")


if __name__ == "__main__":
    from src.config import get_settings
    from src.logging_setup import configure_logging

    configure_logging(get_settings().log_level)
    run()
