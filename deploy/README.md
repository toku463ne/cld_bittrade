# Always-on viz (nginx + systemd)

Run the Dash viz (`src.viz.app`) as a persistent service behind nginx, so you don't
have to hand-start it. One command installs everything; it's idempotent.

```bash
# from the repo root, on the host (dev box or the live t3.micro)
bash scripts/setup_viz_service.sh
# then open  http://<host-ip>/
```

## What it installs

| Piece | Path | Role |
|-------|------|------|
| systemd unit | `/etc/systemd/system/btc-viz.service` | runs `uv run --env-file <env> python -m src.viz.app`, `Restart=always`, starts on boot. Binds **127.0.0.1:8050** only (`VIZ_HOST`). |
| nginx site | `/etc/nginx/sites-available/btc-viz.conf` → `sites-enabled/` | reverse-proxies **:80 → 127.0.0.1:8050**. Replaces the stock `default` site. |

Templates live in `deploy/btc-viz.service` and `deploy/nginx-btc-viz.conf`; the
script substitutes this host's real user / repo path / `uv` path / env file / port.

## Env file & the DB caveat

The script picks the env file automatically: **`.env.prod` if present, else `.env.dev`**
(override with `ENV_FILE=...`). The viz process needs a valid `DATABASE_URL` to
start because the **Chart** and **Backtest** tabs read OHLCV from the DB.

- The **Live trading** tab is **DB-free** — it pulls hourly bars straight from GMO
  (the same `recent_bars` source the live bot uses), so it works on any host.
- On the t3.micro, the **Chart/Backtest** tabs will be empty unless that host's DB
  (`btc_bot_prod`) is populated with OHLCV. That's expected; the Live tab is the
  one you want there.

## Live trading tab

Left pane: pick a live book (the selector mirrors `btc-autotrader`'s `AUTO_BOOKS` /
defaults — `density_pullback:BTC_JPY`, `density_pullback_xrp:XRP_JPY`), toggle
Bollinger/RSI, and **Refresh** to re-pull GMO. The status panel shows the
authoritative live book state (last bar, close, open/pending/resting — mirrors
`logs/heartbeat.jsonl`).

Right pane: the last 14 days of hourly candles with trade signals; side is the
triangle direction. (A multi-component book like `combo_dp_ver`, if selected, colours
its signals **per component** — `density_pullback` green, `vol_expansion_ride` blue.)
Hover, TP/SL lines and zoom-autoscale behave exactly like the Backtest tab.

## Manage / troubleshoot

```bash
systemctl status btc-viz
journalctl -u btc-viz -f          # app logs
systemctl restart btc-viz         # after a code change
sudo nginx -t && sudo systemctl reload nginx
```

## Security

Plain HTTP, **no auth**. Restrict port 80 in the AWS security group (or `ufw`) to
your IP, or put TLS + basic-auth in front before exposing it to the internet.
