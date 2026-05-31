"""Probe: is BTC<->SP500 moving correlation useful for the BTC strategies?

Self-contained exploration (no DB writes, no collector). Downloads an equity
proxy via yfinance (default ES=F, ~24h; ^GSPC for comparison), aligns it to the
1h BTC bars in btc_bot_bt by forward-fill (causal), computes the rolling
return-correlation, and asks two questions:

  A. Regime split — do the existing signs' fire DRs differ across correlation
     regimes (coupled / decoupled / negative)?
  B. Lead-lag — does the equity's last-bar return predict the next BTC bar's
     direction, overall and conditioned on a high positive correlation?

Usage::

    uv run --env-file .env.bt python -m src.backtest.analysis.sp500_corr_probe
    uv run --env-file .env.bt python -m src.backtest.analysis.sp500_corr_probe --code ^GSPC --window 48
"""

from __future__ import annotations

import argparse
import warnings

import numpy as np
import pandas as pd

from src.backtest.sign_benchmark import measure_fires
from src.core.types import Timeframe
from src.data.cache import load_cache
from src.indicators.moving_corr import moving_corr


def _fetch_close(code: str, start: str, end: str, interval: str = "1h") -> pd.Series:
    """Download a UTC-indexed close series via yfinance."""
    import yfinance as yf

    warnings.filterwarnings("ignore")
    df = yf.Ticker(code).history(
        interval=interval, start=start, end=end, auto_adjust=True, actions=False
    )
    if df.empty:
        raise RuntimeError(f"yfinance returned no data for {code}")
    s: pd.Series = df["Close"].dropna()
    idx = pd.DatetimeIndex(s.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    s.index = idx.tz_convert("UTC")
    return pd.Series(s)


def _aligned_corr(btc_close: pd.Series, sp_close: pd.Series, window: int) -> pd.Series:
    """Forward-fill the equity series onto BTC timestamps, then rolling corr."""
    btc_utc = pd.DatetimeIndex(btc_close.index).tz_convert("UTC")
    sp_on_btc = sp_close.reindex(btc_utc, method="ffill")  # causal: last known <= t
    sp_on_btc.index = btc_close.index  # relabel back to BTC (JST) timestamps
    return moving_corr(btc_close, sp_on_btc, window=window)


def _regime(corr: float) -> str:
    if np.isnan(corr):
        return "n/a"
    if corr >= 0.4:
        return "coupled(+)"
    if corr <= -0.2:
        return "negative"
    return "decoupled"


def _dr_table(measured: list, corr_by_iso: dict[str, float]) -> dict[str, tuple[int, float, float]]:  # type: ignore[type-arg]
    """Bucket fires by correlation regime -> (n, DR, mean_signed_return)."""
    buckets: dict[str, list[float]] = {}
    for m in measured:
        if m.signed_return == 0.0:
            continue
        c = corr_by_iso.get(pd.Timestamp(m.fire.fired_at).isoformat(), float("nan"))
        buckets.setdefault(_regime(c), []).append(m.signed_return)
    out: dict[str, tuple[int, float, float]] = {}
    for k, rs in buckets.items():
        arr = np.array(rs)
        out[k] = (len(arr), float((arr > 0).mean()), float(arr.mean()))
    return out


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="BTC<->SP500 moving-corr probe.")
    parser.add_argument("--code", default="ES=F", help="yfinance code (ES=F or ^GSPC).")
    parser.add_argument("--window", type=int, default=24, help="Corr window (bars).")
    args = parser.parse_args()

    cache = load_cache(Timeframe.H1)
    df = cache.to_frame()
    if df.empty:
        raise RuntimeError("No 1h BTC bars in this DB.")
    start = str(df.index.min().date())
    end = str((df.index.max() + pd.Timedelta(days=1)).date())
    btc_close = df["close"]

    sp = _fetch_close(args.code, start, end)
    corr = _aligned_corr(btc_close, sp, args.window)
    corr_by_iso = {
        ts.isoformat(): float(v)
        for ts, v in zip(pd.DatetimeIndex(corr.index), corr.to_numpy(), strict=False)
    }

    valid = corr.dropna()
    print(f"\n=== BTC vs {args.code}  (1h, corr window {args.window}) ===")
    print(f"bars: {len(df)} | sp rows: {len(sp)} | corr defined on {len(valid)} bars")
    print(f"corr: mean {valid.mean():+.2f}  min {valid.min():+.2f}  max {valid.max():+.2f}")
    reg_counts = valid.map(_regime).value_counts().to_dict()
    print("regime time-share:", {k: f"{v}b" for k, v in reg_counts.items()})

    # A. Regime split of each sign's fire DR.
    for sign in ("ema_atr_breakout", "zigzag_bounce"):
        measured = measure_fires(cache.bars, sign)
        print(f"\n--- {sign}: fire DR by correlation regime ---")
        print(f"{'regime':>12} | {'n':>4} {'DR':>6} {'mean_r':>8}")
        for reg, (n, dr, mr) in sorted(_dr_table(measured, corr_by_iso).items()):
            print(f"{reg:>12} | {n:>4} {dr:>6.3f} {mr:>8.4f}")

    # B. Lead-lag: equity last-bar return vs next BTC bar direction.
    sp_on = sp.reindex(pd.DatetimeIndex(btc_close.index).tz_convert("UTC"), method="ffill")
    sp_on.index = btc_close.index
    sp_ret = sp_on.pct_change()
    btc_fwd = btc_close.pct_change().shift(-1)  # next bar's BTC return
    lead = pd.concat([sp_ret.rename("sp"), btc_fwd.rename("btc"), corr.rename("c")], axis=1).dropna()
    same = (np.sign(lead["sp"]) == np.sign(lead["btc"])).mean()
    hi = lead[lead["c"] >= 0.4]
    same_hi = (np.sign(hi["sp"]) == np.sign(hi["btc"])).mean() if len(hi) else float("nan")
    print("\n--- lead-lag: P(next BTC bar same direction as last equity bar) ---")
    print(f"  all bars (n={len(lead)}): {same:.3f}   [0.5 = no edge]")
    print(f"  coupled(+) bars (n={len(hi)}): {same_hi:.3f}")
    print("\nNOTE: ~1 month, tiny n — exploratory only. Re-run with more history.")


if __name__ == "__main__":
    main()
