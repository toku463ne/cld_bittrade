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
uv run --env-file .env.prod python -m src.execution.selfcheck      # verify the WHOLE setup
```

`selfcheck` verifies everything except *placing* an order — config + GMO keys, DB +
schema, GMO public + private reads, kline fetch, strategy compute, log writability —
and exits non-zero on any failure. All 6 PASS = the box is ready (you don't wait for
a signal). The one thing it can't test is sending a real order (needs a funded,
approved leverage account); prove that with one manual `gmo_trade ... --execute`
round-trip when funded.
After this the box runs the trader **hourly at HH:05 in dry-run** (it logs intended
actions, places nothing). Dry-run config: `AUTO_BOOKS=density_pullback:BTC_JPY,
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
   - `.env.prod`: set `ALLOW_ORDERS=true`, and switch to the 1-slot book:
     `AUTO_BOOKS=density_pullback_xrp:XRP_JPY:1` (the dry-run both-full-slots config
     exceeds `EXEC_MAX_SLOTS=1` and so is monitor-only — it would place nothing). To go
     beyond one slot later, follow "Changing the slot count".
   - service: add `--execute` to the `ExecStart` line, then reload:
     ```bash
     sudo sed -i 's#auto_trader$#auto_trader --execute#' /etc/systemd/system/btc-autotrader.service
     sudo systemctl daemon-reload
     ```
5. **Run once, watch**: `sudo systemctl start btc-autotrader.service` then check the log.

## Changing the slot count

Slots — not lot size — are how this book scales capital: lot increases are forbidden
until the benchmark passes, while the backtest *modelled* concurrency. PnL saturates at
**6 slots** (99% for `density_pullback`; 12 wastes 2-3x the capital — `portfolio.md`).
Peak exposure is exactly `slots x min lot x price` — it therefore **moves with price**,
which is what `MAX_BOOK_NOTIONAL_JPY` has to be sized for. Measured 2026-09-04 at six
slots: BTC 76,172 JPY (0.001 x 12.70M), XRP 13,604 (10 x 226.7).

**Step 0 — settle the exchange semantics first (blocking).**
**P1 is ANSWERED (2026-08-06): one settle order per 建玉, second returns `ERR-200`** — see
the execution-fidelity note above; the executor now rests the STOP only. Still open, and
still worth a two-position manual probe on XRP before step 2: **P2** does `/v1/activeOrders`
name the settle target (if it does, exit attribution becomes a direct join instead of the
slot matching in `_assign_close_orders`); **P3** the active-order and private-rate ceilings
(6 slots ⇒ up to 12 resting orders — 6 stops + 6 entries — and ~18 POSTs per cycle vs ~3
at 1 slot; the client now throttles to 5/s). Confirm a surgical `cancel_order` on one
position leaves the other's stop intact, then flatten.

**Step 1 — dry-run differential.** `AUTO_BOOKS=density_pullback_xrp:XRP_JPY:6` with
`EXEC_MAX_SLOTS` unset. Several days. Check `orders.jsonl` for: no bulk cancels, at most
one place-action per (position, exit type) per cycle, entries never exceeding free slots,
and `peak_notional` in `heartbeat.jsonl` matching the hand calculation.

**Step 2 — 2 slots live on XRP** (`:2` + `EXEC_MAX_SLOTS=2`), the cheapest place to be
wrong (~2k JPY/slot). At least a week / 4 round trips. Verify against GMO's execution
history that each position got its own stop, that a ratchet on one slot left the other's
orders untouched, and that the correct 建玉 was closed on a strategy exit.

**Step 3 — 6 slots**, XRP first, then `density_pullback:BTC_JPY:6` after a clean week.

> **Done 2026-09-04 — both books at once**, deviating from the XRP-first order above.
> Measured 6-slot occupancy says the XRP-first probe cannot produce the evidence it is
> meant to: XRP is flat **89%** of hours and holds >=3 positions only **2.6%**, so a clean
> week on it would most likely observe nothing. BTC is the book that actually exercises
> >=3 (**5.0%** of hours, ~2 days/month) and had already run two concurrent positions
> cleanly — independent stops, independent stop-outs, 2026-09-01/02. **P3 stays open**,
> but 6/6 occupancy is **0.37%** of hours — ~32 hours a year — so the 12-resting-order /
> 18-POST ceiling is rare rather than routine (episode count not measured).

Rollback at any step is one env edit (`EXEC_MAX_SLOTS=1`) — no code revert — plus `KILL`
for an emergency flatten.

**The three variables move together.** `AUTO_BOOKS`'s `:slots`, `EXEC_MAX_SLOTS` and
`MAX_BOOK_NOTIONAL_JPY` all gate the same change, and moving only one leaves a state
**worse than either endpoint**. Both half-edits fail silently:

- **`:slots` > `EXEC_MAX_SLOTS`** -> `book_slots <= exec_max_slots()` is false, so
  `reconcile()` is never called for that book. It goes **MONITOR-ONLY and stops
  maintaining exits** — no ratchet, no strategy-exit close, no orphan cleanup. Open
  positions keep only the stop already resting at the exchange, so risk is bounded but
  the book is unmanaged. The one `MONITOR-ONLY` WARNING is the only sign, and it is
  emitted only under `--execute`.
- **`:slots` beyond what `MAX_BOOK_NOTIONAL_JPY` covers** -> `entries_allowed=false`:
  exits are still maintained but the book places **no entries at all**. The cap is
  per book, so it can silence the expensive book while the cheap one keeps trading —
  the failure looks like an ordinary dry spell.

Hit live **2026-09-04** going 2 -> 6: `AUTO_BOOKS` was edited alone, with the timer
already restarted, leaving both books monitor-only while a BTC long was open.

**Verify with a dry-run AFTER the edit** (`uv run --env-file .env.prod python -m
src.execution.auto_trader`, no `--execute`, timer stopped). A dry-run from before the
edit validates the OLD config and proves nothing — check the slot count it prints. Four
things must hold, per book:

1. `(N slots)` is the NEW count, in both the `MultiSimulated` and `peak notional` lines
2. **no `MONITOR-ONLY` warning**
3. `peak notional ... <= cap` (else `entries_allowed: false`)
4. `in sync (desired == live)`, i.e. `n_unadopted: 0` in `logs/heartbeat.jsonl`

Growing a book is safe to do while it is **near-flat** (check `n_open`): the phantom
count below is what the replay retroactively holds, so the fewer positions in flight, the
fewer phantoms the change can conjure. At the 2026-09-04 change the desired book was
identical at 2 and 6 slots (1 open, same entry and stop) — zero phantoms.

**Shrinking a book** (e.g. 6 → 2) while more positions are open than the new cap trips
the anomaly halt and would freeze the book, exits included. Set `LIVE_DRAIN_OK=1` to
downgrade that one case to **drain mode**: exits are still maintained and unmatched
positions closed, but no new entries are placed. Unset it once occupancy is back within
the new cap.

**Growing a book** (e.g. 1 → 2) has the mirror-image failure. The desired book is a
stateless replay, so at the new slot count it retroactively "holds" positions the
smaller book never opened — **phantoms**: desired positions with no live 建玉. They are
never adopted mid-flight (entering now at an arbitrary price is a different trade from
the one the backtest measured), but they still reserve a slot, and a book whose every
slot is phantom opens **nothing**. Watch `n_unadopted` in `logs/heartbeat.jsonl`; the
`WARNING` naming the count is on every affected run.

This normally clears itself once the phantoms exit the replay window — for a book at
~20% occupancy that is a day or two. To resume immediately, set
`LIVE_IGNORE_PHANTOM_SLOTS=1`: phantoms stop reserving live slots. Live exposure is
still capped at `slots` by the independent live-exposure bound, so this costs
trade-for-trade correspondence with the backtest, **not** risk containment. Unset it
once `n_unadopted` is back to 0. (Happened live 2026-08-08: a manual 1 → 2 change left
BTC at 2/2 phantoms with `room=0`.)

**Guardrails.** `MAX_BOOK_NOTIONAL_JPY` (per book) is asserted at startup and in
`selfcheck` — a book whose full occupancy would breach it refuses to run. Free margin is
checked every cycle and gates **entries only**; exits, cancels, ratchets and the kill
switch are never blocked by margin state. A hard ceiling of 8 slots is compiled in, so a
mis-typed `AUTO_BOOKS` cannot authorise an unbounded book.

## Emergency stop

```bash
touch ~/cld_bittrade/KILL                 # next run cancels all + flattens, takes no new trades
# or stop the timer entirely:
sudo systemctl stop btc-autotrader.timer
```

## Known v1 limitations (the executor)

- **Slots are gated by `EXEC_MAX_SLOTS` (default 1).** The executor holds N positions,
  but only books whose `max_slots <= EXEC_MAX_SLOTS` execute; larger ones stay
  monitor-only. Default 1 = the original single-position behaviour, so raising the live
  slot count is always a deliberate env change. See "Changing the slot count" below.
- **Execution fidelity: the take-profit is 1h-granular, not intrabar.** GMO permits
  exactly **one resting settle order per 建玉** — the first reserves the whole position
  (`orderdSize` on `/v1/openPositions`). Confirmed live **2026-08-06 07:05** (BTC pos
  `289850034`): the STOP was accepted and the TP that followed returned
  `ERR-200 "There are open positions that the settlement quantity exceeds the settable
  quantity"`. So the backtest's OCO stop+target pair does not exist on this venue.

  The **protective STOP takes the slot** (protection first — never invert this) and
  fills intrabar at the exact ratchet level, as does the entry LIMIT. The **take-profit
  is realised at the hourly reconcile**: the simulator drops the position on the bar its
  target is touched, and the next reconcile market-closes it — up to an hour later, at
  whatever price is then available. The non-price exits (time-stop, box stall) were
  always 1h-granular.

  **Measured cost (`src/backtest/analysis/tp_next_open_ab.py`, 2026-08-08): small.**
  Re-running both live books with the target realised at the next bar's open instead of
  intrabar: `density_pullback` IS eqSharpe +1.370 → +1.349, OOS +0.505 → +0.492, 98.3% of
  IS PnL retained; `density_pullback_xrp` +0.721 → +0.722 / +2.047 → +2.053, 100.5%
  retained. Walk-forward stays 5/6 for both and ship gate A still passes. The reason it
  is small: only ~8.6% of trades exit on a target at all — these are trail-ride books
  whose dominant exits are ratchet stops and time stops. Do not let this gate a rollout.

  Before the fix this rejection also **aborted the rest of that book's cycle** (entries
  and orphan cleanup were skipped) and never reached `orders.jsonl` — only the journal.
  Action failures are now contained and recorded.
- **Never hand-run the trader twice inside one bar.** A pending **MARKET** entry leaves
  no resting artifact on the exchange, so a second run before the simulator advances a
  bar re-sends it — and the freshly-filled position looks unwanted to the desired book
  (0 open + 1 pending), so it gets closed and re-entered. Churn plus double exposure.
  This is not new to multi-slot (the 1-slot executor behaved identically); the hourly
  HH:05 timer is what keeps it safe. Re-running to *inspect* is fine only without
  `--execute`. Pinned by `test_known_hazard_market_entry_repeats_if_rerun_inside_the_same_bar`.
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
