#!/usr/bin/env bash
# Full rebenchmark pipeline for one strategy/sign (see CLAUDE.md § Benchmark Pipeline).
#
# Steps:
#   1. Delete old SignBenchmarkRun rows from the DB for the strategy.
#   2. sign_benchmark_multiyear --phase benchmark validate report
#   3. sign_regime_analysis
#   4. sign_score_calibration
#   5. sign_benchmark_multiyear --phase backtest   (OOS)
#
# Always runs against the backtest DB (.env.bt). Never .env.dev.
#
# Usage: scripts/rebenchmark_sign.sh <strategy_name> [timeframe]

set -euo pipefail

STRATEGY="${1:-}"
TIMEFRAME="${2:-5m}"
ENV_FILE=".env.bt"

if [[ -z "${STRATEGY}" ]]; then
  echo "Usage: scripts/rebenchmark_sign.sh <strategy_name> [timeframe]" >&2
  exit 1
fi

echo "==> Rebenchmark '${STRATEGY}' (timeframe=${TIMEFRAME}) against ${ENV_FILE}"

echo "==> [1/5] Deleting old SignBenchmarkRun rows for '${STRATEGY}'"
uv run --env-file "${ENV_FILE}" python -c "
from src.db import get_session
from src.models import SignBenchmarkRun
from sqlalchemy import delete
with get_session() as s:
    s.execute(delete(SignBenchmarkRun).where(SignBenchmarkRun.sign_type == '${STRATEGY}'))
print('deleted old runs for ${STRATEGY}')
"

echo "==> [2/5] Multi-month benchmark / validate / report"
uv run --env-file "${ENV_FILE}" python -m src.backtest.sign_benchmark_multiyear \
  --sign "${STRATEGY}" --timeframe "${TIMEFRAME}" --phase benchmark validate report

echo "==> [3/5] Regime-split analysis"
uv run --env-file "${ENV_FILE}" python -m src.backtest.sign_regime_analysis \
  --sign "${STRATEGY}" --timeframe "${TIMEFRAME}"

echo "==> [4/5] Score calibration"
uv run --env-file "${ENV_FILE}" python -m src.backtest.sign_score_calibration \
  --sign "${STRATEGY}" --timeframe "${TIMEFRAME}"

echo "==> [5/5] OOS backtest"
uv run --env-file "${ENV_FILE}" python -m src.backtest.sign_benchmark_multiyear \
  --sign "${STRATEGY}" --timeframe "${TIMEFRAME}" --phase backtest

echo "==> Rebenchmark complete for '${STRATEGY}'."
