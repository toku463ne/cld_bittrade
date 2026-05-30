# Operation Cycle Guide

Interactive guide through each step of the BTC/JPY scalping cycle.

## Steps

1. **Data Collection** — `uv run --env-file .env.dev python -m src.data.collect --timeframe 5m`
   Fetch latest OHLCV bars for FX_BTC_JPY from bitFlyer Lightning API.
   Adjust `--timeframe` to the active strategy's timeframe (1m / 5m / 15m / 1h).

2. **Strategy Review** — Check if parameter tuning is needed.
   Compare current backtest results in `src/backtest/benchmark.md` against
   the previous cycle. If any strategy parameters were changed, run Step 3.
   Check registered strategies via `src/strategy/registry.py`.

3. **Backtest** — `/sign-debate <strategy> --max-iter 3`
   Re-run if any strategy or sign logic was changed.
   Full rebench: `scripts/rebenchmark_sign.sh <strategy_name>`

4. **Report** — Review backtest metrics in the Dash viz app.
   `uv run --env-file .env.dev python -m src.viz.app`
   Open http://localhost:8050 → Backtest tab.
   Check: Sharpe, max DD, DR, OOS vs in-sample, per-period breakdown.

5. **Execute Trades** — Human decision and manual execution only.
   The program does not place orders. This step is intentionally manual.
   Minimum lot size: 0.001 BTC until benchmark passes.

6. **Register Positions** — `uv run --env-file .env.dev python -m src.portfolio.register`
   Log executed trades into the DB through the portfolio module.

## Important

- Step 5 is always performed by the human. The program never places live orders
  above 0.001 BTC until the strategy has passed the full benchmark pipeline.
- Never mix `.env.dev` and `.env.bt` credentials.
- Run backtest tasks with `.env.bt`: `uv run --env-file .env.bt python -m src.backtest.cycle`
