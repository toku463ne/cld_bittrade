#!/usr/bin/env bash
# One-shot provisioning for a fresh Ubuntu t3.micro to run the LIVE auto-trader.
#
# Installs: a 2 GB swapfile (t3.micro safety), PostgreSQL + the prod DB, uv + the
# project deps, the DB schema (Alembic), and an hourly systemd timer that runs the
# auto-trader in DRY-RUN (places no orders until you flip ALLOW_ORDERS).
#
# Run from the repo root on the t3.micro, as a sudo-capable user (default ubuntu):
#   git clone <repo> ~/cld_bittrade && cd ~/cld_bittrade
#   DB_PASSWORD='pick-a-strong-one' bash scripts/setup_prod.sh
#
# Idempotent: safe to re-run. It does NOT touch secrets — you fill GMO keys into
# .env.prod afterwards (the script prints the remaining steps).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="$(id -un)"
DB_NAME="btc_bot_prod"
DB_USER="btc_bot"
DB_PASSWORD="${DB_PASSWORD:-$(openssl rand -hex 16)}"
UV_BIN="${HOME}/.local/bin/uv"

log() { echo -e "\n=== $* ==="; }

if [ "$(id -u)" = "0" ]; then
  echo "WARNING: running as root. Recommended: run as the 'ubuntu' user (it uses sudo"
  echo "         where needed). As root, uv/.venv and the systemd service end up"
  echo "         root-owned and the trader runs as root. Continuing in 5s (Ctrl-C to abort)..."
  sleep 5
fi

log "1/7 system packages (postgresql, git, curl)"
sudo apt-get update -y
sudo apt-get install -y postgresql postgresql-contrib git curl ca-certificates

log "2/7 swapfile (2 GB) — t3.micro has only 1 GB RAM"
if ! sudo swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
else
  echo "swap already active"
fi

log "3/7 uv (Python toolchain + deps manager)"
if [ ! -x "${UV_BIN}" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="${HOME}/.local/bin:${PATH}"

log "4/7 PostgreSQL role + database (${DB_USER} / ${DB_NAME})"
sudo systemctl enable --now postgresql
# If .env.prod already has a real password, SYNC the role to it (so re-runs don't
# clobber the role password out of step with the file). Else use DB_PASSWORD.
if [ -f "${REPO_DIR}/.env.prod" ]; then
  existing_pw="$(sed -n 's#.*://'"${DB_USER}"':\([^@]*\)@.*#\1#p' "${REPO_DIR}/.env.prod" | head -1)"
  if [ -n "${existing_pw}" ] && [ "${existing_pw}" != "CHANGE_ME" ]; then
    DB_PASSWORD="${existing_pw}"
    echo "synced DB_PASSWORD from existing .env.prod"
  fi
fi
# create role (idempotent) and set the password; create the DB if absent
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1 \
  || sudo -u postgres psql -c "CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';"
sudo -u postgres psql -c "ALTER ROLE ${DB_USER} PASSWORD '${DB_PASSWORD}';"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 \
  || sudo -u postgres createdb -O "${DB_USER}" "${DB_NAME}"

log "5/7 install project deps (uv sync)"
cd "${REPO_DIR}"
"${UV_BIN}" sync

log "6/7 .env.prod (created from example if absent; DATABASE_URL filled in)"
DB_URL="postgresql+psycopg2://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}"
if [ ! -f "${REPO_DIR}/.env.prod" ]; then
  cp "${REPO_DIR}/.env.prod.example" "${REPO_DIR}/.env.prod"
  sed -i "s#DATABASE_URL=.*#DATABASE_URL=${DB_URL}#" "${REPO_DIR}/.env.prod"
  chmod 600 "${REPO_DIR}/.env.prod"
  echo "wrote .env.prod (GMO keys still BLANK — fill them in)"
elif grep -q "CHANGE_ME" "${REPO_DIR}/.env.prod"; then
  # existing file still on the placeholder password -> point it at the real DB_URL
  sed -i "s#DATABASE_URL=.*#DATABASE_URL=${DB_URL}#" "${REPO_DIR}/.env.prod"
  echo "fixed placeholder DATABASE_URL in existing .env.prod"
else
  echo ".env.prod already exists with a real DATABASE_URL — role synced to it."
fi
# Always apply the schema (idempotent — no-op if already at head). Uses whatever
# DATABASE_URL is in .env.prod, so it works whether or not the file pre-existed.
"${UV_BIN}" run --env-file .env.prod alembic upgrade head

log "7/7 hourly systemd timer (auto-trader, runs at HH:05)"
sudo tee /etc/systemd/system/btc-autotrader.service >/dev/null <<UNIT
[Unit]
Description=BTC scalping bot auto-trader (one hourly run)
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=oneshot
User=${RUN_USER}
WorkingDirectory=${REPO_DIR}
ExecStart=${UV_BIN} run --env-file ${REPO_DIR}/.env.prod python -m src.execution.auto_trader
UNIT
sudo tee /etc/systemd/system/btc-autotrader.timer >/dev/null <<'UNIT'
[Unit]
Description=Run the auto-trader hourly (after the 1h bar closes)

[Timer]
OnCalendar=*-*-* *:05:00
Persistent=true

[Install]
WantedBy=timers.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now btc-autotrader.timer

cat <<DONE

=== setup complete ===
DB:      ${DB_USER}@localhost/${DB_NAME}  (password stored in .env.prod, chmod 600)
Trader:  hourly at HH:05, currently DRY-RUN (ALLOW_ORDERS=false) — places NO orders.

Remaining steps (you do these):
  1. Put your GMO key/secret into ${REPO_DIR}/.env.prod (GMO_API_KEY / GMO_API_SECRET).
  2. Verify the read path:   ${UV_BIN} run --env-file .env.prod python -m src.execution.gmo_account
  3. Watch a few dry-run cycles:   journalctl -u btc-autotrader.service -f
  4. When the dry-run log looks right AND your leverage account is funded/approved,
     do the staged go-live in docs/deploy.md: manual round-trip, then set
     ALLOW_ORDERS=true and add --execute to the service ExecStart.
Emergency: touch ${REPO_DIR}/KILL  (next run flattens)  |  systemctl stop btc-autotrader.timer
Manage:  systemctl status btc-autotrader.timer   |   systemctl start btc-autotrader.service (run now)
Runbook: docs/deploy.md
DONE
