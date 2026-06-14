#!/usr/bin/env python3
"""Scan heartbeat.jsonl for resting-limit episodes.

The live auto-trader writes a per-run *desired book* snapshot to
``logs/heartbeat.jsonl``. Resting limit orders (density-pullback's pullback
entries) appear in the ``resting`` field while they wait to fill, and silently
vanish once they fill or expire — they are **never** logged to ``orders.jsonl``
(that file only records real execute attempts). This script reconstructs each
resting-limit episode from the heartbeat stream so the live signal frequency can
be cross-checked against the backtest before funding.

An *episode* is a contiguous run of heartbeats (per strategy + symbol + side +
price) in which one resting order is present. For each episode it reports:

- when it was placed and at what limit price,
- how many distinct bars it stayed alive (≈ ``limit_window``),
- whether it **FILLED** (a position with matching side/entry appears as the
  order vanishes), **EXPIRED** (vanished with no matching fill), or is still
  **OPEN** (resting at the end of the file).

Usage::

    python scripts/scan_resting.py                  # logs/heartbeat.jsonl
    python scripts/scan_resting.py path/to/hb.jsonl
    python scripts/scan_resting.py --strategy combo_dp_ver
    python scripts/scan_resting.py --json           # machine-readable rows
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

# A limit fill executes at the limit price, so a filled order shows up as a
# position whose entry sits within this relative tolerance of the resting price.
_FILL_PRICE_TOL = 1e-3


@dataclass
class Episode:
    """One resting-limit order's life from placement to fill/expiry.

    Attributes:
        strategy: Book name (e.g. ``combo_dp_ver``).
        symbol: Trading pair (e.g. ``BTC_JPY``).
        side: ``LONG`` or ``SHORT``.
        price: Limit price the order rested at.
        placed_ts: Wall-clock timestamp of the first heartbeat showing it.
        placed_bar: Bar time of that first heartbeat.
        last_bar: Bar time of the last heartbeat showing it.
        close_at_place: Market close when the order was placed.
        close_at_end: Market close on the last bar it was alive.
        bars_alive: Count of distinct bar times the order was present.
        outcome: ``FILLED``, ``EXPIRED`` or ``OPEN``.
    """

    strategy: str
    symbol: str
    side: str
    price: float
    placed_ts: str
    placed_bar: str
    last_bar: str = ""
    close_at_place: float = 0.0
    close_at_end: float = 0.0
    outcome: str = "OPEN"
    _bars: set[str] = field(default_factory=set, repr=False)

    @property
    def bars_alive(self) -> int:
        """Number of distinct bar times the order was observed resting."""
        return len(self._bars)


def _key(strategy: str, symbol: str, order: dict) -> tuple[str, str, str, float]:
    """Build the episode identity for a resting order within a heartbeat."""
    return (strategy, symbol, str(order["side"]), float(order["price"]))


def _filled(side: str, price: float, positions: list[dict]) -> bool:
    """Return True if an open position matches a just-vanished resting order.

    A resting limit that fills becomes a held position at (about) the limit
    price on the next snapshot. Matching on side + entry price distinguishes a
    fill from a plain expiry/cancel.

    Args:
        side: Side of the vanished resting order.
        price: Limit price of the vanished resting order.
        positions: ``positions`` list from the heartbeat where it vanished.
    """
    for p in positions:
        if str(p.get("side")) != side:
            continue
        entry = p.get("entry")
        if entry and abs(float(entry) - price) / price <= _FILL_PRICE_TOL:
            return True
    return False


def scan(path: Path, strategy_filter: str | None = None) -> list[Episode]:
    """Parse a heartbeat file into closed and still-open resting episodes.

    Heartbeats from different books are interleaved in the file, so each
    (strategy, symbol) stream is tracked independently.

    Args:
        path: Path to a ``heartbeat.jsonl`` file.
        strategy_filter: If given, only episodes for this strategy are returned.

    Returns:
        Episodes in placement order (still-open ones included, marked ``OPEN``).
    """
    open_eps: dict[tuple[str, str, str, float], Episode] = {}
    done: list[Episode] = []
    # Last-seen positions per (strategy, symbol), used to classify a vanish.
    last_positions: dict[tuple[str, str], list[dict]] = defaultdict(list)

    with path.open() as fh:
        for lineno, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                hb = json.loads(raw)
            except json.JSONDecodeError as e:
                print(f"warn: skipping bad JSON at line {lineno}: {e}", file=sys.stderr)
                continue

            strat, symbol = hb["strategy"], hb["symbol"]
            if strategy_filter and strat != strategy_filter:
                continue

            sym_key = (strat, symbol)
            bar = str(hb.get("bar_time"))
            close = float(hb.get("close") or 0.0)
            resting = hb.get("resting") or []
            positions = hb.get("positions") or []

            present = {_key(strat, symbol, o): o for o in resting}

            # New or continuing orders.
            for k, order in present.items():
                ep = open_eps.get(k)
                if ep is None:
                    ep = Episode(
                        strategy=strat, symbol=symbol, side=str(order["side"]),
                        price=float(order["price"]), placed_ts=str(hb.get("ts")),
                        placed_bar=bar, close_at_place=close,
                    )
                    open_eps[k] = ep
                ep.last_bar = bar
                ep.close_at_end = close
                ep._bars.add(bar)

            # Orders for this (strategy, symbol) that vanished this heartbeat.
            vanished = [
                k for k in list(open_eps)
                if k[0] == strat and k[1] == symbol and k not in present
            ]
            for k in vanished:
                ep = open_eps.pop(k)
                ep.outcome = "FILLED" if _filled(ep.side, ep.price, positions) else "EXPIRED"
                done.append(ep)

            last_positions[sym_key] = positions

    # Whatever is still resting at EOF.
    done.extend(open_eps.values())
    done.sort(key=lambda e: e.placed_ts)
    return done


def _print_table(eps: list[Episode]) -> None:
    """Render episodes as a fixed-width table with a summary footer."""
    if not eps:
        print("No resting-limit episodes found.")
        return

    hdr = (
        f"{'strategy':<16} {'symbol':<8} {'side':<5} {'price':>14} "
        f"{'placed (bar)':<22} {'bars':>4} {'outcome':<8} {'drift%':>7}"
    )
    print(hdr)
    print("-" * len(hdr))
    for e in eps:
        drift = (e.close_at_end - e.close_at_place) / e.close_at_place * 100 if e.close_at_place else 0.0
        print(
            f"{e.strategy:<16} {e.symbol:<8} {e.side:<5} {e.price:>14,.2f} "
            f"{e.placed_bar:<22} {e.bars_alive:>4} {e.outcome:<8} {drift:>+7.2f}"
        )

    n = len(eps)
    filled = sum(e.outcome == "FILLED" for e in eps)
    expired = sum(e.outcome == "EXPIRED" for e in eps)
    open_now = sum(e.outcome == "OPEN" for e in eps)
    print("-" * len(hdr))
    print(
        f"{n} episode(s): {filled} filled, {expired} expired, {open_now} open"
        + (f"  (fill rate {filled / (filled + expired):.0%} of resolved)"
           if filled + expired else "")
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", default="logs/heartbeat.jsonl",
                    help="heartbeat jsonl (default: logs/heartbeat.jsonl)")
    ap.add_argument("--strategy", help="only this strategy/book name")
    ap.add_argument("--json", action="store_true", help="emit episodes as JSON lines")
    args = ap.parse_args(argv)

    path = Path(args.path)
    if not path.exists():
        print(f"error: {path} not found", file=sys.stderr)
        return 1

    eps = scan(path, args.strategy)
    if args.json:
        for e in eps:
            row = {k: v for k, v in asdict(e).items() if not k.startswith("_")}
            row["bars_alive"] = e.bars_alive
            print(json.dumps(row))
    else:
        _print_table(eps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
