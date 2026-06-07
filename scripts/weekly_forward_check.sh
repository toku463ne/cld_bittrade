#!/usr/bin/env bash
# Weekly forward/lockbox confirmation for the shipped strategies (density_pullback,
# vol_expansion_ride).
#
# Each run: (1) imports the latest ~2 weeks of GMO 1h BTC_JPY klines (idempotent —
# skip_existing dedupes, so re-runs only fetch new days), then (2) runs the
# forward/lockbox paper-trade evaluator, which scores the strategy ONLY on bars after
# the frozen lockbox boundary and prints ACCRUING / CONFIRMED / NOT CONFIRMED.
#
# Local-only: reads/writes the backtest DB (.env.bt) and reads public GMO klines
# (no exchange private/order API; this is paper — it places no orders). Drive it
# from cron — see the install line at the bottom of this file.

set -euo pipefail

PROJECT_DIR="/home/ubuntu/cld_bittrade"
UV="/home/ubuntu/.local/bin/uv"
PRODUCT="${FORWARD_PRODUCT:-GMO_BTC_JPY}"
# Space-separated list of shipped strategies to forward-check (override via env).
STRATEGIES="${FORWARD_STRATEGIES:-density_pullback vol_expansion_ride}"
LOG_DIR="${PROJECT_DIR}/logs"
LOG_FILE="${LOG_DIR}/forward.log"
LOCK_FILE="${LOG_DIR}/forward.lock"

export PATH="/home/ubuntu/.local/bin:${PATH}"
cd "${PROJECT_DIR}"
mkdir -p "${LOG_DIR}"

# Refuse to overlap with a still-running check.
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "$(date -Is) | another forward run is in progress; skipping." >>"${LOG_FILE}"
  exit 0
fi

FROM="$(date -d '-14 days' +%F)"
TO="$(date +%F)"

{
  echo "=== $(date -Is) | weekly forward check (${STRATEGIES}; ${PRODUCT}) ==="
  "${UV}" run --env-file .env.bt python -m src.data.import_gmo \
    --from "${FROM}" --to "${TO}" --timeframe 1h --product "${PRODUCT}"
  for STRATEGY in ${STRATEGIES}; do
    "${UV}" run --env-file .env.bt python -m src.backtest.paper_forward \
      --strategy "${STRATEGY}" --timeframe 1h --product "${PRODUCT}"
  done
  echo "=== $(date -Is) | done ==="
} >>"${LOG_FILE}" 2>&1

# Install (Mondays 09:00 local):
#   ( crontab -l 2>/dev/null | grep -v '# btc_bot forward check'; \
#     echo '0 9 * * 1 /home/ubuntu/cld_bittrade/scripts/weekly_forward_check.sh # btc_bot forward check' ) | crontab -
# Remove:
#   crontab -l | grep -v '# btc_bot forward check' | crontab -
# Tail results:  tail -f /home/ubuntu/cld_bittrade/logs/forward.log
