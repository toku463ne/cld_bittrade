# BTC/JPY Scalping Bot

A strategy-agnostic BTC/JPY scalping framework for the bitFlyer Lightning API.
**Development and testing go through the mock layer; the live API is reached only
when `USE_LIVE_API=true`.** See `CLAUDE.md` for the full project contract.

## Setup

```bash
# Install dependencies (uv manages Python 3.11+ automatically)
uv sync --extra dev

# Create the environment files from templates and fill them in
cp .env.dev.example .env.dev
cp .env.bt.example  .env.bt

# Create the databases (once)
createdb btc_bot_dev
createdb btc_bot_bt

# Apply migrations to each DB
uv run --env-file .env.dev alembic upgrade head
uv run --env-file .env.bt  alembic upgrade head
```

## Operation cycle

```bash
# 1. Collect OHLCV bars (mock feed unless USE_LIVE_API=true)
uv run --env-file .env.dev python -m src.data.collect --timeframe 5m

# 1b. Resumable history (read-only, no API key): re-run to extend deeper/forward.
#     Stores raw executions + per-product cursors, rebuilds OHLCV from the full set.
USE_LIVE_API=true uv run --env-file .env.dev python -m src.data.history \
    --direction both --max-ticks 10000 --timeframe 1m
#     direction: back (deeper past) | forward (catch up to now) | both
#     Pure reset (drop a product's raw execs + checkpoint + OHLCV, no fetch):
#       uv run --env-file .env.bt python -m src.data.history --reset --max-ticks 0 --no-rebuild

# 2. Backtest a strategy
uv run --env-file .env.bt python -m src.backtest.cycle --strategy ema_atr_breakout

# 3. Full rebenchmark (run on every sign/strategy logic change)
scripts/rebenchmark_sign.sh ema_atr_breakout

# 4. Launch the viz app
uv run --env-file .env.dev python -m src.viz.app   # http://localhost:8050

# 5. Trades are executed MANUALLY by the human (minimum 0.001 BTC)

# 6. Register an executed position
uv run --env-file .env.dev python -m src.portfolio.register \
    --side long --price 5000000 --strategy ema_atr_breakout
```

## Layout

| Path              | Purpose                                              |
|-------------------|------------------------------------------------------|
| `src/data/`       | bitFlyer feed + OHLCV collection (only external I/O) |
| `src/mock/`       | Mock REST/WS layer (development + tests)             |
| `src/indicators/` | EMA, ATR, RSI, Bollinger                             |
| `src/signs/`      | Signal detectors (inherit `signs/base.py`)          |
| `src/strategy/`   | Strategies + registry (inherit `strategy/base.py`)  |
| `src/exit/`       | Exit rules (ATR/fixed TP/SL, trail, time stop)      |
| `src/simulator/`  | Two-bar-fill bar simulator (NOT backtrader)         |
| `src/backtest/`   | Metrics, benchmark pipeline, A/B, cycle runner      |
| `src/portfolio/`  | Position tracking + manual registration             |
| `src/viz/`        | Dash app (Chart / Backtest / Maintenance tabs)      |
| `src/execution/`  | Live order execution — **not yet implemented**      |

The live execution layer (`src/execution/`, Implementation Order step 12) is
intentionally deferred.
