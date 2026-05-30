#!/usr/bin/env bash
# Recurring, resumable OHLCV history collection for backtests.
#
# Designed to be driven by cron (see scripts/install_history_cron.sh). Each run:
#   - forward: catches up to now
#   - back:    deepens history further into the past
#   - rebuilds 1m and 5m OHLCV from the full raw-execution set
# The history extender is idempotent and checkpoint-driven, so overlapping or
# repeated runs are safe. A flock guard prevents concurrent runs anyway.
#
# Read-only against bitFlyer's PUBLIC endpoints (no API key). Writes to the
# backtest DB (.env.bt). Tune cadence/size in install_history_cron.sh.

set -euo pipefail

PROJECT_DIR="/home/ubuntu/cld_bittrade"
UV="/home/ubuntu/.local/bin/uv"
MAX_TICKS="${HISTORY_MAX_TICKS:-50000}"
TIMEFRAME="${HISTORY_TIMEFRAME:-1m}"
LOG_DIR="${PROJECT_DIR}/logs"
LOG_FILE="${LOG_DIR}/history.log"
LOCK_FILE="${LOG_DIR}/history.lock"

export PATH="/home/ubuntu/.local/bin:${PATH}"
export USE_LIVE_API=true

cd "${PROJECT_DIR}"
mkdir -p "${LOG_DIR}"

# Refuse to overlap with a still-running collection.
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "$(date -Is) | another history run is in progress; skipping." >>"${LOG_FILE}"
  exit 0
fi

{
  echo "=== $(date -Is) | history run (max_ticks=${MAX_TICKS}, tf=${TIMEFRAME}) ==="
  "${UV}" run --env-file .env.bt python -m src.data.history \
    --direction both --max-ticks "${MAX_TICKS}" --timeframe "${TIMEFRAME}"
  # Keep the 5m series in sync from the same raw set.
  "${UV}" run --env-file .env.bt python -c \
    "from src.data.history import rebuild_ohlcv; from src.core.types import Timeframe; rebuild_ohlcv(Timeframe.M5)"
  echo "=== $(date -Is) | done ==="
} >>"${LOG_FILE}" 2>&1
