#!/usr/bin/env bash
# Install the always-on Dash viz as a systemd service behind nginx, so you never
# have to hand-start the viz again. Idempotent — safe to re-run.
#
# Run from the repo on the host (dev box or the live t3.micro), as a sudo-capable
# user (default: the current user):
#   bash scripts/setup_viz_service.sh
#
# Env overrides:
#   ENV_FILE=.env.prod   which env file the viz loads (default: auto — .env.prod if
#                        present, else .env.dev). The viz needs a valid DATABASE_URL
#                        to start (the Chart/Backtest tabs read the DB); the Live tab
#                        itself is DB-free and pulls bars straight from GMO.
#   VIZ_PORT=8050        loopback port the Dash app binds (nginx fronts it on :80).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="$(id -un)"
UV_BIN="${HOME}/.local/bin/uv"
VIZ_PORT="${VIZ_PORT:-8050}"

# Pick the env file: explicit override, else prefer prod, else dev.
if [ -n "${ENV_FILE:-}" ]; then
  : # honour the override
elif [ -f "${REPO_DIR}/.env.prod" ]; then
  ENV_FILE=".env.prod"
elif [ -f "${REPO_DIR}/.env.dev" ]; then
  ENV_FILE=".env.dev"
else
  echo "ERROR: no .env.prod or .env.dev in ${REPO_DIR}; set ENV_FILE=..." >&2
  exit 1
fi
ENV_PATH="${REPO_DIR}/${ENV_FILE}"

log() { echo -e "\n=== $* ==="; }

if [ ! -x "${UV_BIN}" ]; then
  echo "ERROR: uv not found at ${UV_BIN}. Install it or run scripts/setup_prod.sh first." >&2
  exit 1
fi

log "1/4 nginx"
if ! command -v nginx >/dev/null 2>&1; then
  sudo apt-get update -y
  sudo apt-get install -y nginx
fi

log "2/4 systemd unit (btc-viz.service) — env ${ENV_FILE}, 127.0.0.1:${VIZ_PORT}"
sed -e "s#@RUN_USER@#${RUN_USER}#g" \
    -e "s#@REPO_DIR@#${REPO_DIR}#g" \
    -e "s#@UV_BIN@#${UV_BIN}#g" \
    -e "s#@ENV_FILE@#${ENV_PATH}#g" \
    -e "s#@VIZ_PORT@#${VIZ_PORT}#g" \
    "${REPO_DIR}/deploy/btc-viz.service" | sudo tee /etc/systemd/system/btc-viz.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now btc-viz.service

log "3/4 nginx reverse proxy (:80 -> 127.0.0.1:${VIZ_PORT})"
sed -e "s#@VIZ_PORT@#${VIZ_PORT}#g" \
    "${REPO_DIR}/deploy/nginx-btc-viz.conf" | sudo tee /etc/nginx/sites-available/btc-viz.conf >/dev/null
sudo ln -sf /etc/nginx/sites-available/btc-viz.conf /etc/nginx/sites-enabled/btc-viz.conf
# Our server block is `default_server`; drop the stock default to avoid a clash.
if [ -L /etc/nginx/sites-enabled/default ]; then
  sudo rm -f /etc/nginx/sites-enabled/default
fi
sudo nginx -t
sudo systemctl reload nginx

log "4/4 done"
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
cat <<DONE

=== viz service up ===
Service: btc-viz.service  (auto-restart, starts on boot)
URL:     http://${IP:-<this-host>}/    (nginx :80 -> 127.0.0.1:${VIZ_PORT})
Env:     ${ENV_FILE}

Tabs:    Live trading  -> pulls bars live from GMO (no DB needed)
         Chart/Backtest -> need a populated ${ENV_FILE} DB on THIS host, else empty

Manage:  systemctl status btc-viz        |  journalctl -u btc-viz -f
         systemctl restart btc-viz       |  systemctl restart nginx

Security: plain HTTP, no auth. Restrict :80 in the AWS security group / ufw,
          or add TLS + basic-auth before exposing it to the internet.
DONE
