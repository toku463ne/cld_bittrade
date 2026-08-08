"""Diversification check: does the Kojiro daily MA-stage diversify the BTC book
(combo_dp_ver / density_pullback)?

Question (sign-debate 2026-06-28): Kojiro's standalone IS Sharpe is only ~B&H parity,
but it is the ONLY book-derived sign that is BOTH-SIDED and bear-protective (+3% in 2022
while B&H −73% and the long-biased density books bled). So its value, if any, is as a
DIVERSIFIER leg, not a standalone. This measures that directly, BEFORE any OOS spend.

METHOD (IS-only, lockbox untouched):
  - BTC book = combo_dp_ver (and density_pullback for reference) via MultiSimulator at the
    capital-efficient 6-slot cap; monthly return-on-required-capital = sum trade return_pct
    in the month / peak concurrency. (Yearly n=4 is too coarse for a correlation; monthly
    ~48 IS points is the honest granularity.)
  - Kojiro = daily 5/20/40 MA-stage + pyr-1.0N (reuses kojiro_pyramid_stage0.walk); daily
    bar_net summed into the same monthly buckets.
  - Align months in the IS window (pre-2025-04-01). Report: monthly-return CORRELATION
    (the diversification headline), each book's monthly Sharpe, and the COMBINED book at
    equal-risk (inverse-vol) weights — combined monthly Sharpe, worst month, and max
    drawdown of the cumulative monthly equity — vs the BTC book ALONE.

READ: Kojiro is worth pursuing as a diversifier ONLY if (a) correlation is low/negative AND
  (b) the equal-risk combination RAISES the combined monthly Sharpe and/or LOWERS max-DD vs
  the BTC book alone. If the combination does not improve on the BTC book, the diversification
  is not real and the OOS lockbox should not be spent on it.
Scale note: monthly streams are on different normalisations (return-on-capital vs ATR-unit
  1%-risk); correlation is scale-invariant and the combination uses inverse-vol (equal-risk)
  weights, so neither output depends on the absolute scales.

Read-only; no DB writes, no production code. IS-only. Run:
  uv run --env-file .env.bt python -m src.backtest.analysis.kojiro_combo_diversify
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.backtest.analysis.kojiro_pyramid_stage0 import (
    ATR_PERIOD, S, M, L, _atr, _resample, _stage, walk,
)
from src.backtest.sign_benchmark import split_lockbox
from src.core.types import Bar, Timeframe, Trade
from src.data.cache import load_cache
from src.simulator import MultiSimulator
from src.strategy.registry import get_strategy

BTC_BOOKS = [("combo_dp_ver", 6), ("density_pullback", 6)]


def _peak_concurrency(trades: list[Trade]) -> int:
    if not trades:
        return 1
    ev = sorted([(t.entry_time, 1) for t in trades] + [(t.exit_time, -1) for t in trades])
    cur = mx = 0
    for _, d in ev:
        cur += d
        mx = max(mx, cur)
    return max(mx, 1)


def _monthly_from_trades(trades: list[Trade], peak: int, months: list[str]) -> np.ndarray:
    acc = {mk: 0.0 for mk in months}
    for t in trades:
        mk = f"{t.exit_time.year}-{t.exit_time.month:02d}"
        if mk in acc:
            acc[mk] += t.return_pct
    return np.array([acc[mk] / peak for mk in months])


def _monthly_sharpe(x: np.ndarray) -> float:
    sd = x.std(ddof=1)
    return float(x.mean() / sd * np.sqrt(12)) if sd > 0 else 0.0


def _max_dd(monthly: np.ndarray) -> float:
    eq = np.cumsum(monthly)
    return float((np.maximum.accumulate(eq) - eq).max())


def main() -> None:
    product = "GMO_BTC_JPY"
    cache = load_cache(Timeframe.H1, product=product)
    is_bars: list[Bar] = split_lockbox(cache.bars)[0]
    boundary = is_bars[-1].timestamp

    # --- Kojiro daily MA-stage pyr-1.0N monthly stream (IS) ---
    dfd = _resample(cache.to_frame(), "1D").loc[:boundary]
    o, h = dfd["open"].to_numpy(), dfd["high"].to_numpy()
    lo, c = dfd["low"].to_numpy(), dfd["close"].to_numpy()
    atrs = _atr(h, lo, c, ATR_PERIOD)
    s = pd.Series(c).rolling(S).mean().to_numpy()
    m = pd.Series(c).rolling(M).mean().to_numpy()
    ll = pd.Series(c).rolling(L).mean().to_numpy()
    st = _stage(s, m, ll)
    bar_net, *_ = walk(o, h, lo, c, atrs, s, m, st, 1.0)
    kdf = pd.DataFrame({"ret": bar_net}, index=dfd.index)
    kmon = kdf.groupby(kdf.index.strftime("%Y-%m"))["ret"].sum()
    months = list(kmon.index)
    kojiro = kmon.to_numpy()

    print(f"{product} IN-SAMPLE diversification check  ({months[0]} -> {months[-1]}, "
          f"{len(months)} months)\n")
    print(f"{'book':22} {'n':>5} {'peak':>5} {'monSharpe':>10} {'worst%':>8} {'maxDD':>8} {'corr_kojiro':>12}")
    print("-" * 74)

    kj_sh = _monthly_sharpe(kojiro)
    print(f"{'kojiro_ma_stage(d)':22} {'-':>5} {'-':>5} {kj_sh:>10.3f} "
          f"{kojiro.min():>8.2f} {_max_dd(kojiro):>8.2f} {'1.00':>12}")

    for name, slots in BTC_BOOKS:
        strat = get_strategy(name)
        strat.max_slots = slots
        trades = MultiSimulator(strat, size=0.001).run(is_bars).trades
        peak = _peak_concurrency(trades)
        btc = _monthly_from_trades(trades, peak, months)
        corr = float(np.corrcoef(btc, kojiro)[0, 1])
        print(f"{name:22} {len(trades):>5} {peak:>5} {_monthly_sharpe(btc):>10.3f} "
              f"{btc.min():>8.2f} {_max_dd(btc):>8.2f} {corr:>12.2f}")

        # equal-risk (inverse-vol) combination vs BTC alone
        vb, vk = btc.std(ddof=1), kojiro.std(ddof=1)
        wb, wk = (1 / vb), (1 / vk)
        wb, wk = wb / (wb + wk), wk / (wb + wk)
        comb = wb * btc + wk * kojiro
        print(f"  -> equal-risk combo (w_btc={wb:.2f}/w_kojiro={wk:.2f}): "
              f"monSharpe {_monthly_sharpe(comb):+.3f}  (vs {name} alone {_monthly_sharpe(btc):+.3f})  "
              f"maxDD {_max_dd(comb):.2f} (vs {_max_dd(btc):.2f})")

    print("\nREAD: pursue as a diversifier only if corr is low/neg AND the combo RAISES monSharpe "
          "and/or LOWERS maxDD vs the BTC book alone. IS-only; lockbox untouched.")


if __name__ == "__main__":
    from src.config import get_settings
    from src.logging_setup import configure_logging

    configure_logging(get_settings().log_level)
    main()
