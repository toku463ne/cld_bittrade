# Live deployment (GMO, t3.micro)

The live auto-trader runs on a small AWS box (t3.micro is adequate — 1 book, hourly,
~600 bars; backtests stay on the PC with `.env.bt`). Venue is **GMO Coin** leverage
(`*_JPY` symbols = our backtest data, BTC/ETH/XRP all shortable).

## Three safety gates (all required to place a real order)

| gate | where | purpose |
|---|---|---|
| `USE_LIVE_API=true` | `.env.prod` | enables LIVE reads (account/positions) |
| `ALLOW_ORDERS=true` | `.env.prod` | enables order placement at all |
| `--execute` | the command / systemd unit | this invocation may send orders |

Plus, always-on in code: **0.001-equivalent min-lot hard cap** per symbol, an
**anomaly halt** (>1 position or oversized → no actions), and a **kill switch**
(`KILL` file in the repo root, or `KILL_SWITCH=1`) → cancel all + flatten.

## First-time provision

```bash
git clone <repo> ~/cld_bittrade && cd ~/cld_bittrade
DB_PASSWORD='strong-pw' bash scripts/setup_prod.sh
# then edit ~/cld_bittrade/.env.prod: add GMO_API_KEY / GMO_API_SECRET
uv run --env-file .env.prod python -m src.execution.gmo_account     # verify reads
```
After this the box runs the trader **hourly at HH:05 in dry-run** (it logs intended
actions, places nothing). Dry-run config: `AUTO_BOOKS=combo_dp_ver:BTC_JPY,
density_pullback_xrp:XRP_JPY` — **both books at full slots** for the most samples to
observe (multi-slot books are monitor-only, so they never place orders regardless of
gates). Watch it: `journalctl -u btc-autotrader.service -f`. For the **first real
trade**, switch to one slot, min size: `AUTO_BOOKS=density_pullback_xrp:XRP_JPY:1`.

## Staged go-live (do NOT skip)

1. **Watch dry-run** for a few days. Confirm the desired book + intended actions look
   right against the real market.
2. **Account ready**: GMO leverage account approved (clears `ERR-5127`) and a little
   JPY funded (`gmo_account` shows `available > 0`).
3. **Manual proof**: one min-lot round-trip by hand — confirms the live order schema:
   ```bash
   uv run --env-file .env.prod python -m src.execution.gmo_trade short --symbol XRP_JPY --execute
   uv run --env-file .env.prod python -m src.execution.gmo_trade status --symbol XRP_JPY
   uv run --env-file .env.prod python -m src.execution.gmo_trade close --symbol XRP_JPY --execute
   ```
   (needs `ALLOW_ORDERS=true`.)
4. **Enable auto-execution** — deliberate edits:
   - `.env.prod`: set `ALLOW_ORDERS=true`, and switch to the 1-slot book the executor
     trades: `AUTO_BOOKS=density_pullback_xrp:XRP_JPY:1` (the dry-run both-full-slots
     config is monitor-only and would place nothing).
   - service: add `--execute` to the `ExecStart` line, then reload:
     ```bash
     sudo sed -i 's#auto_trader$#auto_trader --execute#' /etc/systemd/system/btc-autotrader.service
     sudo systemctl daemon-reload
     ```
5. **Run once, watch**: `sudo systemctl start btc-autotrader.service` then check the log.

## Emergency stop

```bash
touch ~/cld_bittrade/KILL                 # next run cancels all + flattens, takes no new trades
# or stop the timer entirely:
sudo systemctl stop btc-autotrader.timer
```

## Known v1 limitations (the executor)

- **1 slot only.** The executor handles `density_pullback_xrp:XRP_JPY:1`. Multi-slot
  books (e.g. `combo_dp_ver`) run monitor-only.
- **Execution fidelity.** Entry (resting LIMIT), stop (resting STOP) and take-profit
  (resting LIMIT) all fill INTRABAR at the exact strategy levels — exchange-handled,
  no polling needed, matching the backtest. Only the non-price exits (time-stop, and
  bar-evaluated exits like a box stall) act at the hourly reconcile via market close;
  those are inherently 1h-granular, so hourly is correct. The hourly loop just
  maintains the resting orders (ratchet stop updates, OCO leftover cleanup).
- **Logs for analysis.** Two JSONL files in `logs/`:
  - `orders.jsonl` — every *action* (entry/stop/TP/close/cancel): `ts, symbol, execute,
    action, result`. Low-frequency (only when something fires).
  - `heartbeat.jsonl` — a per-run *snapshot* of each book even when flat: `ts, strategy,
    symbol, bar_time, close, n_open/pending/resting, positions[], resting[]`. Dense
    hourly time series of price vs. the desired book.

  Send both (with the date range) for offline analysis — I cross-check the live action
  stream against the backtest. The authoritative *fill* record is GMO's execution
  history (`get_latest_executions`); reconciling fills into the DB is a follow-up.
- **First `--execute` confirms the live order schema** — the order-request shapes are
  GMO-spec + mocked-tested but were not live-tested (no funded account). Do the manual
  round-trip (step 3) first.
