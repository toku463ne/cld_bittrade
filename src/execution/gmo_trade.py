"""Manual GMO trade CLI — verify the order plumbing before automating.

Minimum-lot (per-symbol) only, and **dry-run by default**: nothing is sent unless
``--execute``. Live sending also needs ``USE_LIVE_API=true`` AND ``ALLOW_ORDERS=true``
in ``.env.dev`` (three deliberate gates). Leverage is bidirectional — ``long`` opens
a BUY position, ``short`` opens a SELL position; ``close`` settles open 建玉 by id.

Examples::

    uv run --env-file .env.dev python -m src.execution.gmo_trade status  --symbol BTC_JPY
    uv run --env-file .env.dev python -m src.execution.gmo_trade long    --symbol XRP_JPY            # dry-run
    uv run --env-file .env.dev python -m src.execution.gmo_trade short   --symbol XRP_JPY --execute  # opens SELL
    uv run --env-file .env.dev python -m src.execution.gmo_trade close   --symbol XRP_JPY --execute
    uv run --env-file .env.dev python -m src.execution.gmo_trade cancel-all --symbol XRP_JPY --execute
"""

from __future__ import annotations

import argparse

from loguru import logger

from src.config import get_settings
from src.execution.gmo_client import (
    LEVERAGE_MIN_SIZE,
    GmoClient,
    gmo_account_client_from_settings,
    gmo_trading_client_from_settings,
)
from src.logging_setup import configure_logging


def _cmd_status(args: argparse.Namespace) -> None:
    """Read-only snapshot: margin + open positions + active orders."""
    c = gmo_account_client_from_settings()
    m = c.get_margin()
    logger.info("margin: available={} actualPnL={}", m.get("availableAmount"), m.get("actualProfitLoss"))
    for p in c.get_open_positions(args.symbol):
        logger.info("position id={} {} size={} @ {} pnl={}",
                    p.get("positionId"), p.get("side"), p.get("size"), p.get("price"), p.get("lossGain"))
    for o in c.get_active_orders(args.symbol):
        logger.info("order id={} {} {} size={} @ {} status={}",
                    o.get("orderId"), o.get("side"), o.get("orderType"),
                    o.get("size"), o.get("price"), o.get("status"))


def _open(args: argparse.Namespace, side: str) -> None:
    """Open (or preview) a minimum-lot position."""
    sym = args.symbol
    lot = LEVERAGE_MIN_SIZE.get(sym)
    if lot is None:
        logger.error("{} is not a permitted leverage symbol {}", sym, list(LEVERAGE_MIN_SIZE))
        return
    et = args.type.upper()
    desc = f"{side} {lot} {sym} {et}" + (f" @ {args.price}" if args.type == "limit" else "")
    if not args.execute:
        logger.info("DRY-RUN (no order sent): would OPEN {}. Re-run with --execute to send.", desc)
        return
    c: GmoClient = gmo_trading_client_from_settings()
    oid = c.send_order(sym, side, execution_type=args.type, price=args.price)
    logger.info("OPENED {} -> orderId={}", desc, oid)


def _cmd_close(args: argparse.Namespace) -> None:
    """Settle open position(s) for the symbol with an opposite market order."""
    sym = args.symbol
    positions = gmo_account_client_from_settings().get_open_positions(sym)
    if not positions:
        logger.info("no open positions for {}", sym)
        return
    for p in positions:
        pos_side = str(p.get("side")).upper()
        close_side = "SELL" if pos_side == "BUY" else "BUY"
        size = float(p.get("size", 0.0))
        pid = int(p.get("positionId", 0))
        if not args.execute:
            logger.info("DRY-RUN: would CLOSE pos {} ({} {}) via {} MARKET. --execute to send.",
                        pid, pos_side, size, close_side)
            continue
        oid = gmo_trading_client_from_settings().close_position(sym, pid, close_side, size)
        logger.info("CLOSED pos {} via {} {} -> orderId={}", pid, close_side, size, oid)


def _cmd_cancel_all(args: argparse.Namespace) -> None:
    """Cancel all active orders for the symbol."""
    if not args.execute:
        logger.info("DRY-RUN: would cancel ALL active orders for {}. --execute to send.", args.symbol)
        return
    gmo_trading_client_from_settings().cancel_bulk(args.symbol)
    logger.info("cancelled all active orders for {}", args.symbol)


def main() -> None:
    """CLI entrypoint."""
    configure_logging(get_settings().log_level)
    ap = argparse.ArgumentParser(description="Manual GMO leverage trade tools (min-lot, dry-run default).")
    ap.add_argument("--symbol", default="BTC_JPY", choices=list(LEVERAGE_MIN_SIZE))
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Margin + positions + active orders.").set_defaults(fn=_cmd_status)
    for name, side in (("long", "BUY"), ("short", "SELL")):
        p = sub.add_parser(name, help=f"Open a min-lot {side} position.")
        p.add_argument("--type", choices=["market", "limit"], default="market")
        p.add_argument("--price", type=float, default=None, help="Limit price (LIMIT only).")
        p.add_argument("--execute", action="store_true", help="Actually send (else dry-run).")
        p.set_defaults(fn=lambda a, s=side: _open(a, s))
    pc = sub.add_parser("close", help="Settle open position(s) (opposite market order).")
    pc.add_argument("--execute", action="store_true")
    pc.set_defaults(fn=_cmd_close)
    pca = sub.add_parser("cancel-all", help="Cancel all active orders.")
    pca.add_argument("--execute", action="store_true")
    pca.set_defaults(fn=_cmd_cancel_all)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
