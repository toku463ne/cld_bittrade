# BTC/JPY Scalping Bot — Claude Code Instructions

## Project Overview

A BTC/JPY scalping bot using the bitFlyer Lightning API.
Live trading uses real funds — minimum lot size (0.001 BTC) only until benchmark passes.
**Development and testing must go through the mock layer. Never hit the live API during development.**
The architecture is strategy-agnostic: multiple strategies can be added, backtested,
and benchmarked independently.

---

## Environment & Package Management

- Runtime: Python 3.11+ managed via **uv**
- Never use `pip` directly — always use `uv` commands
- Virtual environment is created and managed automatically by uv

---

## Environment Files

| File      | Purpose                  | DB          |
|-----------|--------------------------|-------------|
| .env.dev  | Development / live feed  | btc_bot_dev |
| .env.bt   | Backtest (read-heavy)    | btc_bot_bt  |

- Never mix credentials between environments
- Dev tasks:      `uv run --env-file .env.dev python -m src.data.collect`
- Backtest tasks: `uv run --env-file .env.bt  python -m src.backtest.cycle`

---

## Tech Stack

- Python 3.11+
- PostgreSQL (local): port 5432
  - Dev DB:      `btc_bot_dev`
  - Backtest DB: `btc_bot_bt`
- Key libraries: requests, websockets, pandas, numpy, ta, sqlalchemy, psycopg2, loguru
- Visualization: Dash + Plotly (interactive web app)

---

## Directory Structure

- `src/data/`        : bitFlyer price feed, OHLCV collection (all external API calls go here only)
- `src/indicators/`  : Technical indicators (EMA, ATR, RSI, BB, etc.)
- `src/signs/`       : Signal detectors — each inherits from `signs/base.py`
- `src/strategy/`    : Strategy definitions — each inherits from `strategy/base.py`
- `src/simulator/`   : Bar-based trade simulator (DO NOT use backtrader)
- `src/backtest/`    : Backtest runners, metrics, benchmark pipeline
- `src/exit/`        : Exit rules (ATR trail, time stop, fixed TP/SL)
- `src/portfolio/`   : Position tracking, capital management
- `src/execution/`   : bitFlyer order execution (live, minimum lot only)
- `src/mock/`        : Mock layer for development and testing
- `src/viz/`         : Dash web application (chart viewer + backtest viewer + maintenance)

---

## API Endpoints (bitFlyer Lightning)

- REST:       `https://api.bitflyer.com/v1`
- WebSocket:  `wss://ws.bitflyer.com/v1`
- Board:      `lightning_board_snapshot_FX_BTC_JPY`
- Ticker:     `lightning_ticker_FX_BTC_JPY`
- Executions: `lightning_executions_FX_BTC_JPY`

---

## Mock Layer (implement first, before anything else)

- `src/mock/mock_api.py` — mocks bitFlyer REST API responses
- `src/mock/mock_ws.py`  — replays historical tick data to simulate WebSocket feed
- All tests must run through the mock layer
- Switch to live API only via environment variable: `USE_LIVE_API=true`
- The mock must faithfully reproduce the real API response schema

---

## Strategy Architecture

Each strategy lives in `src/strategy/` and inherits from `strategy/base.py`.

### strategy/base.py must define:

- `name: str`                          — unique identifier
- `description: str`                   — human-readable summary
- `on_bar(bar: Bar) -> Signal | None`  — core logic, called on every new bar
- `get_exit_rules() -> ExitConfig`     — TP/SL/time stop parameters
- `required_indicators: list[str]`     — declared upfront for dependency injection

### Example strategy (reference implementation):

`strategy/ema_atr_breakout.py` — EMA(9/21) cross + ATR volatility filter

- Long:  EMA(9) crosses above EMA(21) AND ATR(14) > 20-bar ATR average
- Short: EMA(9) crosses below EMA(21) AND ATR(14) > 20-bar ATR average
- TP: entry ± ATR × 1.5 / SL: entry ± ATR × 0.8 / Time stop: 5 min

### Adding a new strategy:

1. Create `src/strategy/<strategy_name>.py` inheriting `strategy/base.py`
2. Register it in `src/strategy/registry.py`
3. Run the full benchmark pipeline before using it live

### Strategy registry (`strategy/registry.py`):

- Maintains a dict of all available strategies by name
- Allows CLI selection: `--strategy ema_atr_breakout`
- Backtest runner iterates over all registered strategies if `--strategy all`
- Viz app populates strategy dropdown from registry

---

## Simulator / Backtest Model

- **Two-bar fill rule**: signal fires at close of bar T, fill executes at open of bar T+1
- Apply consistently in both simulator and mock
- `DataCache` loads OHLCV; warmup NaN stored as `0.0` — filter with `or None`
- **DO NOT use backtrader** — use `src/simulator/` only

---

## Interactive Web App (`src/viz/`)

Launch:
```
uv run --env-file .env.dev python -m src.viz.app
# open http://localhost:8050
```

### Tabs

| Tab             | Purpose                                                              |
|-----------------|----------------------------------------------------------------------|
| **Chart**       | Live/historical BTC/JPY candlestick with indicators overlaid        |
| **Backtest**    | Backtest result viewer — shows trades on chart, metrics panel        |
| **Maintenance** | Background workers: OHLCV download, benchmark pipeline trigger       |

### Chart Tab — layout

Three panels sharing a single x-axis (Plotly subplots):

1. **Price panel** (candlestick)
   - Overlaid: EMA(9), EMA(21) as lines
   - Overlaid: Bollinger Bands as shaded area (toggle)
   - Entry/exit markers from live positions (▲ long, ▼ short)

2. **ATR panel**
   - ATR(14) as line
   - 20-bar ATR average as dashed reference line
   - Shaded region when ATR > average (volatility filter active)

3. **RSI panel** (toggle)
   - RSI(14) as line
   - Reference lines at 30 and 70

Controls: timeframe selector (1m/5m/15m/1h), strategy selector, date range picker,
toggle switches for each indicator overlay.

### Backtest Tab — layout

Same three-panel chart layout, plus:

- **Trade markers on price panel**:
  - Entry: colored triangle (green = long, red = short)
  - Exit: circle marker (filled = TP hit, open = SL/time stop)
  - Hover tooltip: entry price, exit price, PnL, hold duration, exit reason

- **Metrics panel** (right sidebar):
  - In-sample vs OOS metrics displayed side-by-side
  - If OOS Sharpe < 0 or OOS DD > 2× in-sample DD: flag as OVERFIT
  - Benchmark comparison bar chart (strategy vs Buy-and-hold BTC/JPY)
  - Per-period breakdown table (scrollable)

### Maintenance Tab

- OHLCV download trigger (date range + timeframe)
- Benchmark pipeline trigger per strategy
- Background task status log (loguru output streamed to textarea)

---

## Benchmark Pipeline (mandatory on every logic change)

Run the full rebenchmark whenever signal detection logic or strategy logic changes:

```
scripts/rebenchmark_sign.sh <strategy_name>
```

Steps:
1. Delete old SignBenchmarkRun rows from dev DB for the strategy
2. Run `sign_benchmark_multiyear --phase benchmark validate report`
3. Run `sign_regime_analysis`
4. Run `sign_score_calibration`
5. Run `sign_benchmark_multiyear --phase backtest` (OOS)

---

## Evaluation Philosophy

See `docs/evaluation_guide.md` for metric mathematics (DR, mean_r, perm_p,
Sharpe, Sortino, EV decomposition, A/B test structure, walk-forward structure).
See `docs/evaluation_criteria.md` for the ship/reject rubric.

### Required Backtest Output Metrics (per strategy)

**Portfolio-level metrics (GO/ship criteria)**
- Total return / annualized return
- Maximum Drawdown (DD): largest peak-to-trough decline in cumulative PnL
- Sharpe ratio (annualized)
- Sortino ratio
- Win rate & profit factor
- Benchmark comparison: Buy-and-hold BTC/JPY — **NOT cash**

**Signal-level metrics (diagnostic only — never ship criteria)**
- DR (Detection Rate) = wins / total_fires
  - 50% = coin flip, 55-57% = mildly informative, 60%+ = strongly informative
  - Always report alongside sample size n
- mean_r (mean signed return per fire)
- Per-trade EV / per-trade Sharpe

**Per-period breakdown**

| Timeframe | Period unit |
|-----------|-------------|
| 1m        | 1 hour      |
| 5m        | 1 day       |
| 15m       | 1 day       |
| 1h        | 1 week      |

Per-period columns: `period`, `n_fires`, `DR`, `total_return`, `max_DD`, `win_rate`

**OOS (Out-of-Sample) metrics**
- Training: all months except the most recent 20% of available bars
- OOS: most recent 20% of available bars
- Report same full metric set as in-sample, clearly labeled "OOS"
- In-sample vs OOS comparison displayed side-by-side in Backtest tab
- If OOS Sharpe < 0 or OOS DD > 2× in-sample DD: flag as OVERFIT

### Ship criteria

```
SHIP strategy if:
  (a) avg Sharpe ≥ baseline (Buy-and-hold BTC/JPY)
  (b) ≥ 4/5 months non-negative
```

Pre-register this gate in code BEFORE seeing results. Do not change after.

---

## Position Sizing

- Minimum lot: 0.001 BTC
- No increase in lot size until the strategy passes the full benchmark pipeline
- Only one strategy runs live at a time unless portfolio-level correlation is accounted for
- Honest benchmark = displaced capital alternative, not cash

---

## Operation Cycle

See `.claude/commands/cycle.md` for the full interactive guide.

1. **Data Collection**: `uv run --env-file .env.dev python -m src.data.collect`
2. **Strategy Review**: Check `src/backtest/benchmark.md` and `src/strategy/registry.py`
3. **Backtest**: `scripts/rebenchmark_sign.sh <strategy>` if logic changed
4. **Report**: Launch viz app → Backtest tab
5. **Trading**: **Human executes manually** — minimum 0.001 BTC
6. **Position Entry**: `uv run --env-file .env.dev python -m src.portfolio.register`

---

## Agent Debate System

For sign/strategy change decisions, use the iterated debate cycle:

```
/sign-debate <topic> --max-iter 3
```

Cycle: `analyst → historian → proposer → critic → judge`

All agents reference `docs/evaluation_criteria.md` as the shared rubric.
See `.claude/agents/` for agent specs and `.claude/commands/sign-debate.md` for protocol.

---

## Coding Standards

- Type hints required — mypy strict mode
- Google-style docstrings
- All DB access via SQLAlchemy ORM; migrations via Alembic
- All config via `.env` files only — never hardcode API keys
- Never suppress errors; log everything with loguru

---

## Implementation Order (follow strictly)

1. Write benchmark philosophy into `docs/evaluation_guide.md` and `docs/evaluation_criteria.md`
2. Design DB schema and run Alembic migrations
3. Implement mock layer (`src/mock/`)
4. Implement data feed and OHLCV collection (`src/data/`)
5. Implement indicators (`src/indicators/`)
6. Implement strategy base class and registry (`src/strategy/`)
7. Implement first strategy: `ema_atr_breakout`
8. Implement signal detection (`src/signs/`)
9. Implement simulator (`src/simulator/`)
10. Implement backtest and benchmark pipeline (`src/backtest/`)
11. Implement Dash viz app (`src/viz/`) — Chart tab first, then Backtest tab
12. Implement live execution layer last (`src/execution/`)

---

## Strictly Prohibited

- Hardcoding API keys or committing `.env` files
- Using backtrader
- Using per-trade metrics as GO/ship criteria
- Connecting to live API before mock layer is complete
- Lot sizes above 0.001 BTC before benchmark passes
- Running multiple strategies live without portfolio-level correlation check
- Mixing `.env.dev` and `.env.bt` credentials