#!/usr/bin/env bash
# Full rebenchmark pipeline for one strategy/sign (see CLAUDE.md § Benchmark Pipeline).
#
# Steps:
#   1. Delete old SignBenchmarkRun rows from the DB for the strategy.
#   2. sign_benchmark_multiyear --phase benchmark validate report
#   3. sign_regime_analysis
#   4. sign_score_calibration
#   5. sign_benchmark_multiyear --phase backtest   (OOS)
#   6. cycle  (portfolio metrics: Sharpe vs buy-and-hold, ship gate)
#
# Always runs against the backtest DB (.env.bt). Never .env.dev.
#
# Usage: scripts/rebenchmark_sign.sh <strategy_name> [timeframe] [product]
#   product is optional; default = the configured product (FX_BTC_JPY).
#   e.g. scripts/rebenchmark_sign.sh zigzag_bounce 1h GMO_BTC_JPY

set -euo pipefail

STRATEGY="${1:-}"
TIMEFRAME="${2:-5m}"
PRODUCT="${3:-}"
ENV_FILE=".env.bt"

if [[ -z "${STRATEGY}" ]]; then
  echo "Usage: scripts/rebenchmark_sign.sh <strategy_name> [timeframe] [product]" >&2
  exit 1
fi

# Build the optional --product flag (empty = configured product). Product codes
# have no spaces, so the unquoted expansion below is safe.
PRODARG=""
if [[ -n "${PRODUCT}" ]]; then
  PRODARG="--product ${PRODUCT}"
fi

echo "==> Rebenchmark '${STRATEGY}' (timeframe=${TIMEFRAME}, product=${PRODUCT:-configured}) against ${ENV_FILE}"

echo "==> [1/6] Deleting old SignBenchmarkRun rows for '${STRATEGY}'"
uv run --env-file "${ENV_FILE}" python -c "
from src.db import get_session
from src.models import SignBenchmarkRun
from sqlalchemy import delete
with get_session() as s:
    s.execute(delete(SignBenchmarkRun).where(SignBenchmarkRun.sign_type == '${STRATEGY}'))
print('deleted old runs for ${STRATEGY}')
"

echo "==> [2/6] Multi-month benchmark / validate / report"
uv run --env-file "${ENV_FILE}" python -m src.backtest.sign_benchmark_multiyear \
  --sign "${STRATEGY}" --timeframe "${TIMEFRAME}" --phase benchmark validate report ${PRODARG}

echo "==> [3/6] Regime-split analysis"
uv run --env-file "${ENV_FILE}" python -m src.backtest.sign_regime_analysis \
  --sign "${STRATEGY}" --timeframe "${TIMEFRAME}" ${PRODARG}

echo "==> [4/6] Score calibration"
uv run --env-file "${ENV_FILE}" python -m src.backtest.sign_score_calibration \
  --sign "${STRATEGY}" --timeframe "${TIMEFRAME}" ${PRODARG}

echo "==> [5/6] OOS backtest"
uv run --env-file "${ENV_FILE}" python -m src.backtest.sign_benchmark_multiyear \
  --sign "${STRATEGY}" --timeframe "${TIMEFRAME}" --phase backtest ${PRODARG}

echo "==> [6/6] Portfolio cycle (Sharpe vs buy-and-hold, ship gate)"
uv run --env-file "${ENV_FILE}" python -m src.backtest.cycle \
  --strategy "${STRATEGY}" --timeframe "${TIMEFRAME}" ${PRODARG}

echo "==> Rebenchmark complete for '${STRATEGY}'."
