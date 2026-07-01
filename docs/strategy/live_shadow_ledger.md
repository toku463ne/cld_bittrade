# Live Shadow-Fill Ledger

Running record of the **live monitor shadow trades** on the GMO t3.micro stack
(`ip-172-31-2-96`), reconstructed from `logs/*.jsonl` position-state records.

**This is NOT the lockbox test.** `src/backtest/paper_forward.py` scores shipped
strategies on public backtest data the strategy never touched. *This* file tracks the
`--execute false`, monitor-only book running against the real GMO feed — the plumbing
proof that precedes Gate-4 auto-arm. No real funds; `AUTO_BOOKS` in dry-run.

## Method / caveats
- P&L reconstructed from the position-state log, which records **state (entry/stop),
  not the exit fill price**. Exits are approximated at the **first bar after the
  position vanished** (two-bar fill rule). Stop-out exits carry burst-spread exposure.
- Approximation is **conservative on trailed-stop winners**: e.g. short #2's stop sat
  ~1.6% below the post-exit bar close used here, so its true fill was ~+5.7% (table
  shows +4.13%). Net figures are therefore a floor.
- Cost models: **Calm** = 2bp/side (`DEFAULT_FEE_RATE`), no swap. **Realistic** =
  2bp/side + 0.04%/day swap + 5× burst on stop exits (bitFlyer-realistic).
- These are **not** ship evidence — n is far too small for a Sharpe vs. the lockbox
  (combo IS +2.20 / OOS +1.57). The ledger exists to accumulate honest live samples.

## Trades

Table below is **auto-generated** — regenerate with
`uv run python -m src.backtest.analysis.live_shadow_ledger`.

<!-- BEGIN AUTO -->
| # | Book | Sym | Side | Entry→Exit | entry bar | held | Exit | Calm | Realistic |
|---|------|-----|------|-----------|-----------|------|------|------|-----------|
| 1 | combo_dp_ver | BTC_JPY | L | 10,460,115→~10,530,402 | 2026-06-14 22:00 | 49b | stop | +0.63% | +0.47% |
| 2 | density_pullback | BTC_JPY | S | 10,142,875→~9,720,025 | 2026-06-24 11:00 | 49b | stop | +4.13% | +3.97% |
| 3 | density_pullback | BTC_JPY | S | 9,595,025→~9,660,652 | 2026-06-30 14:00 | 23b | signal | −0.72% | −0.76% |
| 4 | density_pullback | BTC_JPY | S | 9,577,984→~9,660,652 | 2026-07-01 08:00 | 5b | signal | −0.90% | −0.91% |
| 5 | density_pullback | BTC_JPY | S | 9,560,942→~9,660,652 | 2026-07-01 13:00 | 0b | signal | −1.08% | −1.08% |

**Net (unit-weighted, 5 closed):** Calm **+2.05%** · Realistic **+1.68%**

## Open (unrealized)

| Book | Sym | Side | Entry | Held | Unrealized (calm) |
|------|-----|------|-------|------|-------------------|
| density_pullback_xrp | XRP_JPY | L | 171.4233 | 1b | +0.58% (mark to live) |
<!-- END AUTO -->

**Net excluding trade #2:** Calm −2.08% · Realistic −2.29% (result is load-bearing on one short).

> Correction vs. first hand-computed pass: the three pyramid shorts (#3–5) exited
> **below** their stops (close 9,660,652 < stops 9,684k–9,731k) — a **signal/book
> close, not a stop-out** — so the 5× burst does *not* apply to them. Realistic net is
> **+1.68%**, not the +1.44% I first charged. The generator is the source of truth.

## Notes
- Non-fills (resting orders that expired unfilled) are excluded: 06-13 combo LONG,
  06-23 dp SHORT.
- Ratchet-stop clamp (`83d3ed7`) observed working on trade #1: stop ratcheted above
  market at held-49, closed at market instead of a phantom above-bar fill.
- Pyramid cluster (#3–5) is the worst contributor (−2.7% aggregate) — three stacked
  shorts closed together on the bounce (signal/book close, below their stops, so no
  burst). Expected diversifier shape; watch this pattern.

---
_Last updated: 2026-07-02. Reconstructed from live monitor log (dry-run, execute=false).
Append new closed trades as they land; recompute net. Boundary: first live bar
2026-06-11 12:00 UTC._
