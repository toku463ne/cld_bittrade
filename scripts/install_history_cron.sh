#!/usr/bin/env bash
# Install (or update) the recurring history-collection cron entry for the
# current user. Idempotent: re-running replaces the existing entry.
#
# Usage:
#   scripts/install_history_cron.sh                 # default: every 30 min
#   scripts/install_history_cron.sh "*/15 * * * *"  # custom schedule
#   scripts/install_history_cron.sh --remove        # uninstall

set -euo pipefail

SCRIPT="/home/ubuntu/cld_bittrade/scripts/collect_history.sh"
MARKER="# btc_bot history collector"

if [[ "${1:-}" == "--remove" ]]; then
  crontab -l 2>/dev/null | grep -v "${MARKER}" | crontab - || true
  echo "Removed btc_bot history cron entry (if present)."
  exit 0
fi

SCHEDULE="${1:-*/30 * * * *}"
LINE="${SCHEDULE} ${SCRIPT} ${MARKER}"

# Drop any prior marker line, then append the new one.
( crontab -l 2>/dev/null | grep -v "${MARKER}" || true; echo "${LINE}" ) | crontab -

echo "Installed cron entry:"
crontab -l | grep "${MARKER}"
