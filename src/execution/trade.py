"""Manual trade CLI — verify the order plumbing before automating.

Minimum-lot (0.001 BTC) only, and **dry-run by default**: nothing is sent unless
you pass ``--execute``. Live sending additionally needs ``USE_LIVE_API=true`` AND
``ALLOW_ORDERS=true`` in ``.env.dev`` (three deliberate gates).

Examples (read/preview need no order gates; --execute needs all three)::

    uv run --env-file .env.dev python -m src.execution.trade markets
    uv run --env-file .env.dev python -m src.execution.trade status
    uv run --env-file .env.dev python -m src.execution.trade buy  --type market           # dry-run
    uv run --env-file .env.dev python -m src.execution.trade buy  --type limit --price 9000000 --execute
    uv run --env-file .env.dev python -m src.execution.trade close   --execute
    uv run --env-file .env.dev python -m src.execution.trade cancel-all --execute
"""

from __future__ import annotations

import argparse

from loguru import logger

from src.config import get_settings
from src.execution.bitflyer_client import (
    BitflyerClient,
    account_client_from_settings,
    fetch_markets,
    trading_client_from_settings,
)
from src.logging_setup import configure_logging
from src.portfolio.position import MIN_LOT


def _shortable(m: dict[str, object]) -> bool:
    pc = str(m.get("product_code", ""))
    mt = str(m.get("market_type", ""))
    return pc.startswith("FX_") or mt.upper() in {"FX", "CFD"}


def _cmd_markets(_args: argparse.Namespace) -> None:
    """List products and flag which are shortable (needed for the strategies)."""
    for m in fetch_markets():
        flag = "SHORTABLE" if _shortable(m) else "spot/long-only"
        logger.info("  {:18} type={:6} {}", m.get("product_code"), m.get("market_type", "-"), flag)


def _cmd_status(args: argparse.Namespace) -> None:
    """Read-only snapshot: positions + active orders for the product."""
    c = account_client_from_settings()
    pc = args.product or c.product_code
    logger.info("read-only={}", c.is_read_only())
    for p in c.get_positions(pc):
        logger.info("position: {} {} size={} @ {} pnl={}",
                    p.get("product_code"), p.get("side"), p.get("size"), p.get("price"), p.get("pnl"))
    for o in c.get_active_orders(pc):
        logger.info("order: {} {} {} size={} @ {} id={}",
                    o.get("side"), o.get("child_order_type"), o.get("size"), o.get("price"),
                    o.get("child_order_state"), o.get("child_order_acceptance_id"))


def _trading_or_preview(execute: bool) -> BitflyerClient:
    """Trading client when --execute, else read-only (for the dry-run preview)."""
    return trading_client_from_settings() if execute else account_client_from_settings()


def _order(args: argparse.Namespace, side: str) -> None:
    """Place (or preview) one minimum-lot order."""
    pc = args.product or get_settings().product_code
    desc = f"{side} {MIN_LOT} {pc} {args.type.upper()}" + (f" @ {args.price}" if args.type == "limit" else "")
    if not args.execute:
        logger.info("DRY-RUN (no order sent): would place {}. Re-run with --execute to send.", desc)
        return
    c = trading_client_from_settings()
    res = c.send_child_order(
        side, size=MIN_LOT, order_type=args.type, price=args.price, product_code=pc
    )
    logger.info("SENT {}: {}", desc, res)


def _cmd_close(args: argparse.Namespace) -> None:
    """Flatten open position(s) for the product with an opposite market order."""
    pc = args.product or get_settings().product_code
    positions = account_client_from_settings().get_positions(pc)
    if not positions:
        logger.info("no open positions for {}", pc)
        return
    for p in positions:
        size = min(float(p.get("size", 0.0)), MIN_LOT)
        opp = "SELL" if str(p.get("side")).upper() == "BUY" else "BUY"
        if not args.execute:
            logger.info("DRY-RUN: would close {} {} via {} {} MARKET. --execute to send.",
                        p.get("side"), p.get("size"), opp, size)
            continue
        res = trading_client_from_settings().send_child_order(
            opp, size=size, order_type="MARKET", product_code=pc
        )
        logger.info("CLOSE sent ({} {} {}): {}", opp, size, pc, res)


def _cmd_cancel_all(args: argparse.Namespace) -> None:
    """Cancel all resting orders for the product."""
    pc = args.product or get_settings().product_code
    if not args.execute:
        logger.info("DRY-RUN: would cancel ALL active orders for {}. --execute to send.", pc)
        return
    trading_client_from_settings().cancel_all_orders(pc)
    logger.info("cancelled all active orders for {}", pc)


def main() -> None:
    """CLI entrypoint."""
    configure_logging(get_settings().log_level)
    ap = argparse.ArgumentParser(description="Manual bitFlyer trade tools (min-lot, dry-run default).")
    ap.add_argument("--product", default=None, help="Product code (default: configured).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("markets", help="List products + shortable flag.").set_defaults(fn=_cmd_markets)
    sub.add_parser("status", help="Show positions + active orders.").set_defaults(fn=_cmd_status)
    for name, side in (("buy", "BUY"), ("sell", "SELL")):
        p = sub.add_parser(name, help=f"Place a 0.001 {side} order.")
        p.add_argument("--type", choices=["market", "limit"], default="market")
        p.add_argument("--price", type=float, default=None, help="Limit price (LIMIT only).")
        p.add_argument("--execute", action="store_true", help="Actually send (else dry-run).")
        p.set_defaults(fn=lambda a, s=side: _order(a, s))
    pc = sub.add_parser("close", help="Flatten open position(s) (opposite market order).")
    pc.add_argument("--execute", action="store_true")
    pc.set_defaults(fn=_cmd_close)
    pca = sub.add_parser("cancel-all", help="Cancel all resting orders.")
    pca.add_argument("--execute", action="store_true")
    pca.set_defaults(fn=_cmd_cancel_all)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
