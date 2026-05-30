"""CLI to register a manually executed position.

Usage::

    uv run --env-file .env.dev python -m src.portfolio.register \
        --side long --price 5000000 --strategy ema_atr_breakout

The human executes the trade on bitFlyer manually (minimum 0.001 BTC) and logs
it here. This program never places orders.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from src.config import get_settings
from src.core.types import Side
from src.logging_setup import configure_logging
from src.portfolio.position import MIN_LOT, open_position


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Register a manually executed position.")
    parser.add_argument("--side", choices=[s.value for s in Side], required=True)
    parser.add_argument("--price", type=float, required=True, help="Entry fill price.")
    parser.add_argument("--size", type=float, default=MIN_LOT, help="Size in BTC.")
    parser.add_argument("--strategy", default=None, help="Originating strategy name.")
    parser.add_argument("--note", default=None, help="Free-text note.")
    parser.add_argument(
        "--time",
        default=None,
        help="Entry time ISO 8601 (UTC). Defaults to now.",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)

    entry_time = (
        datetime.fromisoformat(args.time).astimezone(timezone.utc)
        if args.time
        else datetime.now(tz=timezone.utc)
    )
    pos_id = open_position(
        product=settings.product_code,
        side=Side(args.side),
        entry_price=args.price,
        entry_time=entry_time,
        size=args.size,
        strategy=args.strategy,
        note=args.note,
    )
    print(f"Registered position #{pos_id}")


if __name__ == "__main__":
    main()
