"""Research probe: does Binance BTC/USDT LEAD GMO BTC/JPY by a tradeable lag?

The cross-venue hypothesis (after OHLCV directional edges all failed on deep data):
the global price leader (Binance BTC/USDT) moves first and the Japanese venue
(bitFlyer / our GMO proxy) lags, so a fresh Binance move predicts the JP venue's
NEXT bar. This is exogenous information OHLCV-on-JP-alone cannot contain.

This probe answers the kill-question cheaply BEFORE building any collector:
  1. Lead-lag cross-correlation corr(binance_ret[t], jpy_ret[t+k]) for k=-3..+3.
     - k=0 large but k>=1 ~ 0  -> the move is already arbitraged within the bar;
       NO tradeable lag for a REST/WS retail bot -> STOP.
     - k>=1 materially positive -> Binance genuinely leads; worth pursuing.
  2. Fee-aware next-bar test: take GMO at open[t+1] in Binance's last-bar
     direction when |binance_ret[t]| is in its top quantile, exit at close[t+1];
     report mean NET return vs the 0.2% round-trip fee, and the catch-up DR.

PRE-REGISTERED READ:
  PURSUE (build a Binance collector + full strategy) only if BOTH:
    (G1) lag-1 cross-corr >= +0.05 (Binance leads beyond contemporaneous), AND
    (G2) the top-quantile next-bar mean NET return > 0 (clears fees).
  Else: the lag is intra-bar / fee-dominated -> drop cross-venue.

Data: Binance 5m klines pulled from data.binance.vision monthly dumps (free, no
key); GMO BTC/JPY 5m from the bt DB. Aligned on UTC instants (GMO is stored JST).
Research-only network read (not bitFlyer, not live trading).
Run: LL_YEAR=2024 uv run --env-file .env.bt python -m src.backtest.analysis.cross_venue_leadlag_probe
"""

from __future__ import annotations

import io
import os
import zipfile

import numpy as np
import pandas as pd
import requests

from src.core.types import Timeframe
from src.data.cache import load_cache

# Per-side taker slippage (FX_BTC_JPY commission = 0; this models half-spread).
# Override with env FEE to sweep; default 2 bps/side (calm-market estimate).
FEE_RATE = float(os.getenv("FEE", "0.0002"))
_TF = {"1m": Timeframe.M1, "5m": Timeframe.M5}


def fetch_binance(year: int, interval: str) -> pd.DataFrame:
    """Binance BTCUSDT klines for one year, UTC-indexed close prices (vision dumps)."""
    base = f"https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/{interval}"
    frames: list[pd.DataFrame] = []
    for month in range(1, 13):
        url = f"{base}/BTCUSDT-{interval}-{year}-{month:02d}.zip"
        r = requests.get(url, timeout=60)
        if r.status_code != 200:
            continue  # month not published (e.g. future months)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            raw = z.read(z.namelist()[0])
        df = pd.read_csv(io.BytesIO(raw), header=None, usecols=[0, 4])
        df.columns = ["open_time", "close"]
        # Drop a stray header row if present; coerce types.
        df = df[pd.to_numeric(df["open_time"], errors="coerce").notna()]
        ot = df["open_time"].astype("int64")
        # Binance switched some 2025 dumps to microseconds; normalise to ms.
        if ot.iloc[0] > 1_000_000_000_000_000:
            ot = ot // 1000
        idx = pd.to_datetime(ot, unit="ms", utc=True)
        frames.append(pd.DataFrame({"binance": df["close"].astype(float).to_numpy()}, index=idx))
    if not frames:
        raise RuntimeError(f"No Binance dumps fetched for {year}")
    return pd.concat(frames).sort_index()


def main() -> None:
    year = int(os.getenv("LL_YEAR", "2024"))
    tf_str = os.getenv("LL_TF", "5m")
    bn = fetch_binance(year, tf_str)
    print(f"Binance BTCUSDT {tf_str} {year}: {len(bn)} bars  {bn.index[0]} -> {bn.index[-1]}")

    g = load_cache(_TF[tf_str], product="GMO_BTC_JPY").to_frame()
    g = g.tz_convert("UTC") if getattr(g.index, "tz", None) is not None else g.tz_localize("UTC")
    g = g[(g.index >= bn.index[0]) & (g.index <= bn.index[-1])]
    gmo = pd.DataFrame({"jpy_open": g["open"].to_numpy(), "jpy_close": g["close"].to_numpy()}, index=g.index)

    df = bn.join(gmo, how="inner").dropna()
    print(f"aligned 5m bars: {len(df)}\n")

    bret = np.log(df["binance"].to_numpy())
    bret = np.diff(bret, prepend=bret[0])
    jret = np.log(df["jpy_close"].to_numpy())
    jret = np.diff(jret, prepend=jret[0])

    # 1. Lead-lag cross-correlation. k>0 = Binance return at t vs JP return at t+k.
    print("lead-lag corr(binance_ret[t], jpy_ret[t+k])  (k>0 = Binance leads):")
    for k in range(-3, 4):
        if k >= 0:
            a, b = bret[: len(bret) - k], jret[k:]
        else:
            a, b = bret[-k:], jret[: len(jret) + k]
        c = float(np.corrcoef(a, b)[0, 1])
        tag = "  <= contemporaneous" if k == 0 else ("  <= LEAD (tradeable?)" if k > 0 else "")
        print(f"  k={k:+d}  corr={c:+.4f}{tag}")

    # 2. Fee-aware next-bar test: enter GMO at open[t+1] in Binance's last-bar
    #    direction when |binance_ret[t]| is in the top quantile; exit at close[t+1].
    j_open = df["jpy_open"].to_numpy()
    j_close = df["jpy_close"].to_numpy()
    print("\nfee-aware next-bar test (enter open[t+1], exit close[t+1], NET of 0.2%):")
    for q in (0.0, 0.8, 0.9, 0.95):
        thr = float(np.quantile(np.abs(bret), q))
        rows = []
        wins = 0
        for t in range(len(df) - 1):
            if abs(bret[t]) < thr or bret[t] == 0.0:
                continue
            side = 1.0 if bret[t] > 0 else -1.0
            captured = side * (j_close[t + 1] - j_open[t + 1]) / j_open[t + 1]
            rows.append(captured - 2.0 * FEE_RATE)
            if captured > 0:
                wins += 1
        if rows:
            a = np.array(rows)
            dr = wins / len(rows)
            gross = a.mean() * 100 + 2.0 * FEE_RATE * 100  # add back the round-trip cost
            print(f"  |binance_ret| top {1-q:>4.0%}  n={len(rows):>6}  "
                  f"catchup_DR={dr:.3f}  mean_net={a.mean()*100:+.4f}%  "
                  f"sum_net={a.sum()*100:+.2f}%  gross_mean={gross:+.4f}%")
    print("\nPursue only if lag-1 corr >= +0.05 AND a top-quantile mean_net > 0.")


if __name__ == "__main__":
    main()
