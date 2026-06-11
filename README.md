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

# 4. Launch the viz app (Chart / Backtest / Live trading / Maintenance tabs)
uv run --env-file .env.dev python -m src.viz.app   # http://localhost:8050

# 5. Trades are executed MANUALLY by the human (minimum 0.001 BTC)

# 6. Register an executed position
uv run --env-file .env.dev python -m src.portfolio.register \
    --side long --price 5000000 --strategy ema_atr_breakout
```

## Live trading (GMO Coin)

The live venue is **GMO Coin** leverage (the `*_JPY` symbols — the exact source of
our backtest data, and BTC/ETH/XRP are all *shortable*, which the bidirectional
strategies need). bitFlyer is BTC-only for shorts, so it is not used for the
multi-asset book. Backtests stay on the PC (`.env.bt`); the live auto-trader runs
on a small box (`.env.prod`, e.g. an AWS t3.micro — adequate for one hourly book).

**Three safety gates** are required to place a real order: `USE_LIVE_API=true`
(live reads) **and** `ALLOW_ORDERS=true` (order placement) in the env file, **and**
an explicit `--execute` on the command — plus a hard min-lot cap, an anomaly halt,
and a `KILL` kill-switch in code. See **`docs/deploy.md`** for the full runbook.

```bash
# Credentials: put a GMO key in the gitignored env file (.env.dev on the PC,
# .env.prod on the live box). Start read-only; add order permission only when ready.
#   GMO_API_KEY=...   GMO_API_SECRET=...
#   USE_LIVE_API=true        # enables live reads
#   ALLOW_ORDERS=false       # keep false until you are ready to send orders

# Verify the WHOLE setup at once (config, DB, GMO read, bars, strategy, logs) — no
# orders, no waiting for a signal. All PASS = ready. (On the prod box use .env.prod.)
uv run --env-file .env.dev python -m src.execution.selfcheck

# Or just see account/positions/margin (read-only, no orders)
uv run --env-file .env.dev python -m src.execution.gmo_account

# Manual trade tools — min-lot, leverage long/short, DRY-RUN unless --execute
uv run --env-file .env.dev python -m src.execution.gmo_trade status --symbol XRP_JPY
uv run --env-file .env.dev python -m src.execution.gmo_trade short  --symbol XRP_JPY            # dry-run preview
uv run --env-file .env.dev python -m src.execution.gmo_trade short  --symbol XRP_JPY --execute  # real (needs both gates)

# Auto-trader — computes each book's desired state from live GMO bars and logs the
# intended reconcile actions. DRY-RUN by default; --execute trades (1-slot books).
uv run --env-file .env.dev python -m src.execution.auto_trader
AUTO_BOOKS=density_pullback_xrp:XRP_JPY:1 \
    uv run --env-file .env.dev python -m src.execution.auto_trader   # one XRP slot, min size
```

### Production box (t3.micro)

```bash
git clone https://github.com/toku463ne/cld_bittrade.git ~/cld_bittrade && cd ~/cld_bittrade
DB_PASSWORD='strong-pw' bash scripts/setup_prod.sh   # swap, postgres+db, deps, schema, hourly timer
# then: add GMO keys to .env.prod, verify with gmo_account, watch the dry-run:
#   journalctl -u btc-autotrader.service -f
# Going live is the staged checklist in docs/deploy.md (ALLOW_ORDERS=true + --execute).
# Emergency: touch ~/cld_bittrade/KILL   (next run cancels all + flattens)
```

### Always-on viz UI (nginx)

Run the Dash viz as a persistent service behind nginx, so it is always up (no
hand-starting) and reachable from a browser. One idempotent installer:

```bash
bash scripts/setup_viz_service.sh      # systemd unit + nginx reverse proxy
# then open  http://<host-ip>/
```

It installs a `btc-viz.service` (binds **127.0.0.1** only, `Restart=always`, starts
on boot) and an nginx site that proxies **:80 → 127.0.0.1:8050**. The env file is
auto-picked (`.env.prod` if present, else `.env.dev`; override with `ENV_FILE=`).

- The **Live trading** tab is DB-free — it pulls hourly bars straight from GMO (the
  same source the bot uses), shows the last 14 days with per-strategy signal colours,
  and the live book state. It works on any host (incl. the t3.micro).
- The **Chart/Backtest** tabs read the local DB, so they are populated only where the
  `.env` DB has OHLCV.

nginx listens on `0.0.0.0:80` (internet-facing); the app stays on loopback behind it.
Plain HTTP with **no auth** — restrict source IPs in the AWS security group (/ ufw),
or add TLS + basic-auth, before exposing it. Details + management commands:
**`deploy/README.md`**.

```bash
systemctl status btc-viz      # service health
journalctl -u btc-viz -f      # app logs
systemctl restart btc-viz     # after a code change / git pull
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
| `src/viz/`        | Dash app (Chart / Backtest / Live trading / Maintenance tabs); `deploy/` + `scripts/setup_viz_service.sh` run it always-on behind nginx |
| `src/execution/`  | Live clients (GMO + bitFlyer), manual trade CLIs, auto-trader |

The live execution layer (`src/execution/`) is built: read-only account clients,
gated min-lot manual trade CLIs, and a dry-run/gated auto-trader (1-slot executor).
GMO Coin is the live venue; see **Live trading** above and `docs/deploy.md`.
