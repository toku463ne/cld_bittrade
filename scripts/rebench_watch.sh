#!/usr/bin/env bash
# Durable (cron-driven) watcher that re-benchmarks a strategy once enough
# backtest history has accumulated in btc_bot_bt. Survives Claude session close.
#
# Usage: rebench_watch.sh [strategy] [timeframe]   (default: ema_atr_breakout 5m)
#
# Readiness (any one), measured on the chosen timeframe's OHLCV span:
#   - span >= 45 days, OR
#   - back-paging STALLED >= 2 consecutive checks AND span >= 5 days, OR
#   - back-paging STALLED >= 6 consecutive checks AND span >= 2 days (topped out).
# "Stalled" = collection_checkpoint.oldest_id unchanged since the previous check
# (the data cron can no longer deepen history).
#
# When ready it runs the full benchmark pipeline, writes a deterministic
# ship/reject verdict to logs/rebench_result_<strategy>_<tf>.md, marks itself
# done, and removes its own cron entry (runs to completion exactly once).
# Read-only + benchmark only: never modifies strategy code, never trades,
# never commits. Per-target state files let multiple watchers coexist.

set -euo pipefail

STRATEGY="${1:-ema_atr_breakout}"
TIMEFRAME="${2:-5m}"
TAG="${STRATEGY}_${TIMEFRAME}"

PROJECT_DIR="/home/ubuntu/cld_bittrade"
UV="/home/ubuntu/.local/bin/uv"
export PATH="/home/ubuntu/.local/bin:${PATH}"
export PGPASSWORD="btc_bot_local"

cd "${PROJECT_DIR}"
LOG_DIR="${PROJECT_DIR}/logs"
mkdir -p "${LOG_DIR}"
LOG="${LOG_DIR}/rebench_watch.log"
STATE="${LOG_DIR}/rebench_watch_${TAG}.state"   # "<oldest_id>:<stall_count>"
RESULT="${LOG_DIR}/rebench_result_${TAG}.md"
DONE_FILE="${LOG_DIR}/rebench_watch_${TAG}.done"
MARKER="# btc_bot rebench watch ${TAG}"
ts="$(date -Is)"

# Already completed — nothing to do.
[ -f "${DONE_FILE}" ] && exit 0

q() { psql -h localhost -U btc_bot -d btc_bot_bt -t -A -c "$1"; }
span="$(q "SELECT COALESCE(round(EXTRACT(EPOCH FROM (max(timestamp)-min(timestamp)))/86400,2),0) FROM ohlcv WHERE timeframe='${TIMEFRAME}';")"
oldest="$(q "SELECT COALESCE(oldest_id::text,'0') FROM collection_checkpoint LIMIT 1;")"

prev_oldest=""
stall=0
if [ -f "${STATE}" ]; then IFS=: read -r prev_oldest stall <"${STATE}" || true; fi
[ -z "${stall:-}" ] && stall=0

# Stalled = oldest_id unchanged since last check (and we have a prior reading).
if [ -n "${prev_oldest}" ] && [ "${oldest}" = "${prev_oldest}" ]; then
  stall=$((stall + 1))
else
  stall=0
fi
echo "${oldest}:${stall}" >"${STATE}"

ge() { awk "BEGIN{exit !($1>=$2)}"; }  # true (0) iff $1 >= $2

ready=0
reason=""
if ge "${span}" 45; then ready=1; reason="span>=45d"; fi
if [ "${ready}" -eq 0 ] && [ "${stall}" -ge 2 ] && ge "${span}" 5; then
  ready=1; reason="stalled ${stall}x & span>=5d"
fi
if [ "${ready}" -eq 0 ] && [ "${stall}" -ge 6 ] && ge "${span}" 2; then
  ready=1; reason="stalled ${stall}x (topped out) & span>=2d"
fi

if [ "${ready}" -eq 0 ]; then
  echo "${ts} | [${TAG}] not ready: span=${span}d oldest=${oldest} stall=${stall}" >>"${LOG}"
  exit 0
fi

echo "${ts} | [${TAG}] READY (${reason}): span=${span}d — running rebenchmark" >>"${LOG}"
scripts/rebenchmark_sign.sh "${STRATEGY}" "${TIMEFRAME}" >>"${LOG}" 2>&1 \
  || echo "${ts} | [${TAG}] rebench pipeline error" >>"${LOG}"

RB_STRATEGY="${STRATEGY}" RB_TF="${TIMEFRAME}" \
  "${UV}" run --env-file .env.bt python - >"${RESULT}" 2>>"${LOG}" <<'PY'
import datetime
import os
from src.backtest.cycle import run_cycle
from src.core.types import Timeframe

strategy = os.environ["RB_STRATEGY"]
tf = Timeframe(os.environ["RB_TF"])
r = run_cycle(strategy, tf)
verdict = "SHIP" if r.ship else "REJECT"
print(f"# {strategy} re-benchmark ({tf.value}) — {datetime.datetime.now().isoformat(timespec='seconds')}\n")
print(f"**Verdict (mechanical ship gate): {verdict}**\n")
print(f"- In-sample Sharpe: {r.in_sample.sharpe:.3f}  |  OOS Sharpe: {r.oos.sharpe:.3f}")
print(f"- Buy-and-hold BTC/JPY: {r.benchmark_return:+.4f}")
print(f"- In-sample trades: {r.in_sample.n_trades}  |  OOS trades: {r.oos.n_trades}")
print(f"- In-sample max DD: {r.in_sample.max_dd:.4f}  |  per-period rows: {len(r.per_period)}")
print("\nSignal-level per-period DR / mean_r / perm_p: see sign_benchmark_run (DB) + rebench_watch.log.")
print("NOTE: polished verdict + benchmark.md narrative pending a Claude session.")
PY

touch "${DONE_FILE}"
( crontab -l 2>/dev/null | grep -v "${MARKER}" || true ) | crontab -
echo "${ts} | [${TAG}] done (${reason}); result in ${RESULT}; self-removed from cron." >>"${LOG}"
