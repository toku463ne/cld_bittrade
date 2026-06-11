"""Verify the bitFlyer read-only key and print live account state.

Run (live, read-only — places no orders)::

    uv run --env-file .env.dev python -m src.execution.account

Requires ``USE_LIVE_API=true`` and ``BITFLYER_API_KEY`` / ``BITFLYER_API_SECRET``
set in ``.env.dev`` (never committed). It calls only GET endpoints; it confirms
the key is read-only, then prints balance / collateral / positions / open orders.
"""

from __future__ import annotations

from loguru import logger

from src.config import get_settings
from src.execution.bitflyer_client import account_client_from_settings
from src.logging_setup import configure_logging


def main() -> None:
    """Print a one-shot snapshot of the live account (read-only)."""
    configure_logging(get_settings().log_level)
    client = account_client_from_settings()

    perms = client.get_permissions()
    logger.info("permitted endpoints ({}): {}", len(perms), perms)
    if client.is_read_only():
        logger.info("✓ key is READ-ONLY (no order-placing permission) — as expected")
    else:
        logger.warning(
            "⚠ key has TRADE permissions — this module does NOT place orders, but "
            "use a read-only key for monitoring to remove the risk entirely."
        )

    for ccy in client.get_balance():
        if ccy.get("amount", 0):
            logger.info("balance {}: amount={} available={}",
                        ccy.get("currency_code"), ccy.get("amount"), ccy.get("available"))

    col = client.get_collateral()
    logger.info("collateral: JPY={} open_pnl={} require={} ratio={}",
                col.get("collateral"), col.get("open_position_pnl"),
                col.get("require_collateral"), col.get("keep_rate"))

    positions = client.get_positions()
    logger.info("open positions ({}):", len(positions))
    for p in positions:
        logger.info("  {} {} size={} @ {} pnl={} sfd={}",
                    p.get("product_code"), p.get("side"), p.get("size"),
                    p.get("price"), p.get("pnl"), p.get("sfd"))

    orders = client.get_active_orders()
    logger.info("active orders ({}):", len(orders))
    for o in orders:
        logger.info("  {} {} {} size={} @ {} state={}",
                    o.get("product_code"), o.get("side"), o.get("child_order_type"),
                    o.get("size"), o.get("price"), o.get("child_order_state"))


if __name__ == "__main__":
    main()
