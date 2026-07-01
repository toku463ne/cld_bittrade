"""Regenerate the live shadow-fill ledger from the monitor state log.

The live monitor (``AUTO_BOOKS`` in dry-run, ``execute=false``) appends one JSON
record per book per bar to ``logs/*.jsonl``::

    {"ts", "strategy", "symbol", "bar_time", "close", "n_open", ...,
     "positions": [{"side", "entry", "stop", "target", "held"}, ...], "resting": [...]}

This reads those state records and reconstructs closed trades so the live sample can
accumulate against the lockbox expectation. It is **not** the lockbox test itself
(that is ``src/backtest/paper_forward.py``, which scores public backtest data).

Reconstruction rules (and their limits):

- Positions have no id, so each is keyed by ``(strategy, symbol, side, entry)``.
- A position **closes** on the first record where its key vanishes; its exit price is
  approximated by **that record's ``close``** (first bar after it left the book, per the
  two-bar fill rule). The log records *state*, not the exit fill, so exits on trailed
  stops are **conservative** (the true fill sat at the stop, usually better).
- Exit kind is a heuristic: ``stop`` if the exit crossed the last-seen stop
  (long: ``exit <= stop``; short: ``exit >= stop``), else ``signal``. Burst spread is
  charged only on ``stop`` exits under the realistic model.
- ``held`` is the log's in-position bar counter (0 on the entry bar).

Run::

    uv run python -m src.backtest.analysis.live_shadow_ledger            # print table
    uv run python -m src.backtest.analysis.live_shadow_ledger --glob 'logs/*.jsonl'
    uv run python -m src.backtest.analysis.live_shadow_ledger --write docs/strategy/live_shadow_ledger.md
"""

from __future__ import annotations

import argparse
import glob
import json

from src.simulator.simulator import DEFAULT_FEE_RATE

FEE = DEFAULT_FEE_RATE  # 2bp/side calm
SWAP = 0.0004  # 0.04%/day bitFlyer-realistic funding
BURST = 5.0  # stop-exit spread multiplier (bitFlyer-realistic)
BAR_HOURS = 1  # 1h bars


def _load_states(paths: list[str]) -> list[dict]:
    """Load position-state records (those carrying a ``positions`` list), ts-sorted."""
    rows: list[dict] = []
    for path in paths:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if "strategy" in rec and "positions" in rec:
                    rows.append(rec)
    rows.sort(key=lambda r: r["ts"])
    return rows


def reconstruct(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (closed_trades, open_positions) from ts-sorted state records."""
    open_pos: dict[tuple, dict] = {}
    closed: list[dict] = []
    # per-stream last record so we can detect vanished keys
    seen_keys: dict[tuple, set] = {}

    for rec in rows:
        stream = (rec["strategy"], rec["symbol"])
        cur_keys = set()
        for p in rec["positions"]:
            key = (rec["strategy"], rec["symbol"], p["side"], round(p["entry"], 6))
            cur_keys.add(key)
            if key not in open_pos:
                open_pos[key] = {
                    "book": rec["strategy"], "sym": rec["symbol"], "side": p["side"],
                    "entry": p["entry"], "entry_bar": rec["bar_time"],
                    "stop": p["stop"], "held": p["held"],
                }
            else:
                open_pos[key]["stop"] = p["stop"]
                open_pos[key]["held"] = p["held"]
        # any key we were tracking in this stream that's now gone -> closed here
        for key in list(seen_keys.get(stream, set()) - cur_keys):
            pos = open_pos.pop(key, None)
            if pos is None:
                continue
            pos["exit"] = rec["close"]
            side = pos["side"]
            stop = pos["stop"]
            is_stop = (pos["exit"] <= stop) if side > 0 else (pos["exit"] >= stop)
            pos["exit_kind"] = "stop" if is_stop else "signal"
            closed.append(pos)
        seen_keys[stream] = cur_keys

    return closed, list(open_pos.values())


def pnl(pos: dict, realistic: bool) -> float:
    side, entry, exitpx = pos["side"], pos["entry"], pos["exit"]
    gross = side * (exitpx - entry) / entry
    entry_c = FEE
    exit_c = FEE + (FEE * (BURST - 1) if (realistic and pos["exit_kind"] == "stop") else 0.0)
    swap_c = SWAP * pos["held"] * BAR_HOURS / 24.0 if realistic else 0.0
    return gross - entry_c - exit_c - swap_c


def render(closed: list[dict], open_pos: list[dict]) -> str:
    lines = ["| # | Book | Sym | Side | Entry→Exit | entry bar | held | Exit | Calm | Realistic |",
             "|---|------|-----|------|-----------|-----------|------|------|------|-----------|"]
    net_c = net_r = 0.0
    for i, p in enumerate(closed, 1):
        c, r = pnl(p, False), pnl(p, True)
        net_c += c
        net_r += r
        s = "L" if p["side"] > 0 else "S"
        lines.append(
            f"| {i} | {p['book']} | {p['sym']} | {s} | "
            f"{p['entry']:,.0f}→~{p['exit']:,.0f} | {p['entry_bar']} | {p['held']}b | "
            f"{p['exit_kind']} | {c*100:+.2f}% | {r*100:+.2f}% |"
        )
    lines.append("")
    lines.append(f"**Net (unit-weighted, {len(closed)} closed):** "
                 f"Calm **{net_c*100:+.2f}%** · Realistic **{net_r*100:+.2f}%**")
    if open_pos:
        lines += ["", "## Open (unrealized)", "",
                  "| Book | Sym | Side | Entry | Held | Unrealized (calm) |",
                  "|------|-----|------|-------|------|-------------------|"]
        for p in open_pos:
            s = "L" if p["side"] > 0 else "S"
            # no exit; leave unrealized blank (needs a live mark, not in state log alone)
            lines.append(f"| {p['book']} | {p['sym']} | {s} | {p['entry']:,.4f} "
                         f"| {p['held']}b | (mark to live) |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--glob", default="logs/*.jsonl", help="log file glob")
    ap.add_argument("--write", metavar="PATH", help="overwrite the table body of a ledger file")
    args = ap.parse_args()

    paths = sorted(glob.glob(args.glob))
    if not paths:
        raise SystemExit(f"no log files matched {args.glob!r}")
    closed, open_pos = reconstruct(_load_states(paths))
    table = render(closed, open_pos)
    print(table)
    if args.write:
        print(f"\n(reviewed table above; paste into {args.write} between the AUTO markers)")


if __name__ == "__main__":
    main()
