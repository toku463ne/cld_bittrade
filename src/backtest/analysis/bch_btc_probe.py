"""Stage-1 edge probe for Strategy A — BCH referring BTC (cross-asset).

Measures whether `log(BCH/BTC)` mean-reverts tradeably (A2, the recommended primary),
with the lead-lag (A1) cross-correlation as a side diagnostic. Pre-registered Stage-1
pass criteria are in `docs/research/study_plan_new_strategies.md` (A2): half-life < 96 h,
hedged-spread reversion net-of-cost mean > 0 in BOTH halves, |corr(Δratio, ΔBTC)| < 0.30,
edge holding across a majority of (window × k) cells. NET of a realistic 2-leg cost
(0.04%/day funding/leg + 15 bp/leg round-trip spread; BCH spread is the bigger hurdle).

Runs on whatever BCH bars are imported (inner-joined to BTC) — usable on the partial
import as a smoke test, re-run on the full history for the verdict.

Usage::

    uv run --env-file .env.bt python -m src.backtest.analysis.bch_btc_probe --timeframe 1h
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from loguru import logger

from src.core.types import Timeframe
from src.data.cache import load_cache
from src.logging_setup import configure_logging

FUNDING_PER_DAY = 0.0004  # GMO leverage rollover, per leg
SPREAD_PER_LEG = 0.0015  # 15 bp round-trip per leg (BCH spread is the hurdle)
WINDOWS = (120, 168, 336)
KS = (1.5, 2.0, 2.5)
MAX_HOLD = 96  # bars; reversion must complete within the tradeable horizon


def _half_life(x: np.ndarray) -> float:
    """AR(1) half-life of mean reversion (bars); inf if non-reverting."""
    x0, x1 = x[:-1], x[1:]
    m = np.isfinite(x0) & np.isfinite(x1)
    if m.sum() < 50:
        return float("inf")
    b = np.polyfit(x0[m], x1[m], 1)[0]
    return -np.log(2) / np.log(b) if 0.0 < b < 1.0 else float("inf")


def _sim(lr: np.ndarray, btc: np.ndarray, bch: np.ndarray, z: np.ndarray, k: float,
         split: int, direction: int = -1) -> dict[str, float]:
    """Non-overlapping trades: enter at |z|>=k, exit on z-sign-flip or max_hold.

    ``direction=-1`` = reversion (fade the deviation, side=-sign z); ``+1`` = momentum
    (ride the signal, side=+sign z). Exit on a sign flip of the entry signal means
    "deviation reverted" (reversion) or "trend reversed" (momentum).
    """
    n = len(z)
    rows: list[tuple[int, float, float, float, int, int]] = []  # entry, dlr, dbtc, dbch, side, hold
    t = 0
    while t < n:
        if np.isnan(z[t]) or abs(z[t]) < k:
            t += 1
            continue
        side = float(direction) * (1.0 if z[t] > 0 else -1.0)
        e = t
        j = t + 1
        while j < n and (j - e) < MAX_HOLD and not (np.sign(z[j]) != np.sign(z[e]) and not np.isnan(z[j])):
            j += 1
        j = min(j, n - 1)
        rows.append((e, lr[j] - lr[e], np.log(btc[j] / btc[e]), np.log(bch[j] / bch[e]), int(side), j - e))
        t = j + 1
    if not rows:
        return {"n": 0}
    out: dict[str, float] = {"n": float(len(rows))}
    for half, lo, hi in (("e", 0, split), ("l", split, n)):
        sp, bo = [], []
        for e, dlr, dbtc, dbch, side, hold in rows:
            if not (lo <= e < hi):
                continue
            hold_d = hold / 24.0  # actual hold for funding (not the max-hold upper bound)
            sp.append(side * dlr - (2 * SPREAD_PER_LEG + 2 * FUNDING_PER_DAY * hold_d))
            bo.append(side * dbch - (SPREAD_PER_LEG + FUNDING_PER_DAY * hold_d))
        if sp:
            a = np.array(sp)
            out[f"sp_{half}_mean"], out[f"sp_{half}_dr"], out[f"sp_{half}_n"] = a.mean(), float((a > 0).mean()), len(a)
            out[f"bo_{half}_mean"] = float(np.mean(bo))
    return out


MOM_LOOKBACKS = (24, 48, 96)  # A2' ratio-momentum lookbacks (bars)
MOM_STD_WINDOW = 336  # window to z-score the momentum signal


def run(tf: Timeframe, *, mode: str = "reversion") -> None:
    """Probe BCH/BTC ratio reversion (A2) / momentum (A2') + lead-lag (A1)."""
    btc = load_cache(tf, product="GMO_BTC_JPY").bars
    bch = load_cache(tf, product="GMO_BCH_JPY").bars
    if not bch:
        raise RuntimeError("no GMO_BCH_JPY bars — run import_gmo --symbol BCH_JPY first")
    bd = {b.timestamp: b.close for b in bch}
    rows = [(b.timestamp, b.close, bd[b.timestamp]) for b in btc if b.timestamp in bd]
    ts = [r[0] for r in rows]
    a_btc = np.array([r[1] for r in rows], dtype=float)
    a_bch = np.array([r[2] for r in rows], dtype=float)
    n = len(rows)
    logger.info("aligned BCH∩BTC {} bars: {} .. {}  (PARTIAL if import still running)", n, ts[0], ts[-1])
    if n < 500:
        logger.warning("too few aligned bars ({}) — smoke test only", n)
    lr = np.log(a_bch / a_btc)
    split = n // 2

    hl = _half_life(lr)
    corr = float(np.corrcoef(np.diff(lr), np.diff(np.log(a_btc)))[0, 1])
    logger.info("(i)  AR(1) half-life of log(BCH/BTC): {:.0f} bars  [pass < {}]", hl, MAX_HOLD)
    logger.info("(iii) corr(Δlog-ratio, Δlog-BTC): {:+.3f}  [pass |corr| < 0.30]", corr)

    # A1 lead-lag: does BTC return at t predict BCH return at t+lag?
    dbtc, dbch = np.diff(np.log(a_btc)), np.diff(np.log(a_bch))
    ll = ", ".join(
        f"lag{L}={np.corrcoef(dbtc[:-L], dbch[L:])[0,1]:+.3f}" for L in (1, 2, 3, 6)
    )
    logger.info("A1 lead-lag corr(ΔBTC_t, ΔBCH_t+lag): {}", ll)

    # Grid: hedged-spread trade net of cost, early/late. Reversion fades the z-score
    # deviation (direction=-1); momentum rides the L-bar ratio trend (direction=+1).
    lrs = pd.Series(lr)
    direction = -1 if mode == "reversion" else 1
    label = "reversion (A2)" if mode == "reversion" else "MOMENTUM (A2')"
    logger.info("(ii)+(iv) hedged-spread {} net-of-cost (mean per trade):", label)
    logger.info("  par  k   |   n  | early mean (DR) | late mean | [outright BCH e/l]")
    npass = 0
    params = WINDOWS if mode == "reversion" else MOM_LOOKBACKS
    for p in params:
        if mode == "reversion":
            mu = lrs.rolling(p).mean()
            sd = lrs.rolling(p).std(ddof=0)
            z = ((lrs - mu) / sd.replace(0.0, np.nan)).to_numpy()
        else:
            mom = lrs.diff(p)
            z = (mom / mom.rolling(MOM_STD_WINDOW).std(ddof=0).replace(0.0, np.nan)).to_numpy()
        for k in KS:
            r = _sim(lr, a_btc, a_bch, z, k, split, direction)
            if r.get("n", 0) == 0:
                logger.info("  {:>3} {:>3}  |    0 | --", p, k)
                continue
            em, el = r.get("sp_e_mean", float("nan")), r.get("sp_l_mean", float("nan"))
            ok = (em > 0) and (el > 0)
            npass += ok
            logger.info(
                "  {:>3} {:>3}  | {:>4} | {:+.5f} ({:.2f}) | {:+.5f} | [{:+.5f}/{:+.5f}]{}",
                p, k, int(r["n"]), em, r.get("sp_e_dr", float("nan")), el,
                r.get("bo_e_mean", float("nan")), r.get("bo_l_mean", float("nan")),
                "  <= both+" if ok else "",
            )
    logger.info("cells positive in BOTH halves: {}/{}  [pass = majority]", npass, len(WINDOWS) * len(KS))


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="BCH/BTC ratio reversion (A2) / momentum (A2') probe.")
    parser.add_argument("--timeframe", choices=[tf.value for tf in Timeframe], default="1h")
    parser.add_argument("--mode", choices=["reversion", "momentum"], default="reversion")
    args = parser.parse_args()
    configure_logging()
    run(Timeframe(args.timeframe), mode=args.mode)


if __name__ == "__main__":
    main()
