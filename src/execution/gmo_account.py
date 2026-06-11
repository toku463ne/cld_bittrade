"""Verify the GMO read-only key and print live leverage-account state.

Run (live, read-only — places no orders)::

    uv run --env-file .env.dev python -m src.execution.gmo_account

Needs ``USE_LIVE_API=true`` and ``GMO_API_KEY`` / ``GMO_API_SECRET`` in ``.env.dev``
(never committed). Calls only GET endpoints: exchange status (public) + margin /
positions / active orders for the three leverage symbols.
"""

from __future__ import annotations

from loguru import logger

from src.config import get_settings
from src.execution.gmo_client import (
    LEVERAGE_MIN_SIZE,
    fetch_status,
    fetch_ticker,
    gmo_account_client_from_settings,
)
from src.logging_setup import configure_logging

SYMBOLS = ("BTC_JPY", "ETH_JPY", "XRP_JPY")


def main() -> None:
    """One-shot read-only snapshot of the GMO leverage account."""
    configure_logging(get_settings().log_level)
    logger.info("GMO exchange status: {}", fetch_status())
    for sym in SYMBOLS:
        t = fetch_ticker(sym)
        logger.info("ticker {}: last={} (min lot {})", sym, t.get("last"), LEVERAGE_MIN_SIZE.get(sym))

    client = gmo_account_client_from_settings()
    m = client.get_margin()
    logger.info("margin: available={} actualPnL={} margin={} ratio={}",
                m.get("availableAmount"), m.get("actualProfitLoss"),
                m.get("margin"), m.get("marginRatio"))

    for sym in SYMBOLS:
        positions = client.get_open_positions(sym)
        logger.info("{} open positions ({}):", sym, len(positions))
        for p in positions:
            logger.info("  id={} {} size={} @ {} pnl={} losscut={}",
                        p.get("positionId"), p.get("side"), p.get("size"),
                        p.get("price"), p.get("lossGain"), p.get("losscutPrice"))
        orders = client.get_active_orders(sym)
        for o in orders:
            logger.info("  order id={} {} {} size={} @ {} status={}",
                        o.get("orderId"), o.get("side"), o.get("orderType"),
                        o.get("size"), o.get("price"), o.get("status"))


if __name__ == "__main__":
    main()
