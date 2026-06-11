"""End-to-end setup health check — verify everything except live order placement.

Confirms the box is ready WITHOUT waiting for a strategy signal or funding: config,
DB + schema, GMO public + private reads, kline fetch, strategy compute, and log
writability. Exits non-zero if any check fails.

    uv run --env-file .env.prod python -m src.execution.selfcheck

The only thing it cannot verify is actually *sending* an order (needs an approved,
funded leverage account) — test that separately with one manual
`gmo_trade ... --execute` round-trip once funded.
"""

from __future__ import annotations

from collections.abc import Callable

from loguru import logger

from src.config import get_settings
from src.execution.auto_trader import _books
from src.execution.gmo_client import fetch_status, gmo_account_client_from_settings
from src.execution.live_bars import recent_bars
from src.execution.order_log import record
from src.logging_setup import configure_logging
from src.simulator import MultiSimulator
from src.strategy.registry import get_strategy


def _check(name: str, fn: Callable[[], str]) -> bool:
    """Run one check; print PASS/FAIL with a one-line detail."""
    try:
        detail = fn()
        logger.info("  PASS  {:22} {}", name, detail)
        return True
    except Exception as e:  # noqa: BLE001 — report, don't crash
        logger.error("  FAIL  {:22} {}", name, e)
        return False


def main() -> None:
    """Run all setup checks and summarise."""
    s = get_settings()
    configure_logging(s.log_level)
    logger.info("SELF-CHECK ({}): live_read={} allow_orders={}", s.env_name, s.use_live_api, s.allow_orders)
    results: list[bool] = []

    def config() -> str:
        miss = [k for k, v in {"GMO_API_KEY": s.gmo_api_key, "GMO_API_SECRET": s.gmo_api_secret}.items() if not v]
        if miss:
            raise RuntimeError(f"missing env: {miss}")
        return f"env={s.env_name}, GMO keys present, books={[b[1] for b in _books()]}"

    def database() -> str:
        from sqlalchemy import create_engine, inspect, text
        eng = create_engine(s.database_url)
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        tables = set(inspect(eng).get_table_names())
        if "alembic_version" not in tables:
            raise RuntimeError("schema not applied (run alembic upgrade head)")
        return f"connected; {len(tables)} tables (migrations applied)"

    def gmo_public() -> str:
        st = fetch_status()
        if st != "OPEN":
            raise RuntimeError(f"exchange status={st}")
        return "GMO public reachable, exchange OPEN"

    def gmo_private() -> str:
        if not s.use_live_api:
            return "skipped (USE_LIVE_API=false)"
        m = gmo_account_client_from_settings().get_margin()
        return f"private auth OK; available={m.get('availableAmount')} JPY"

    def bars_and_strategy() -> str:
        out = []
        for name, symbol, slots in _books():
            bars = recent_bars(symbol)
            strat = get_strategy(name)
            if slots is not None:
                strat.max_slots = slots
            state = MultiSimulator(strat, size=0.001).live_state(bars)
            out.append(f"{name}/{symbol}: {len(bars)} bars, desired={len(state.positions)}open")
        return " | ".join(out)

    def logs_writable() -> str:
        record("SELFCHECK", "selfcheck probe (ignore)", execute=False)
        from src.execution.order_log import log_path
        return f"order log writable at {log_path()}"

    for name, fn in (
        ("config", config),
        ("database+schema", database),
        ("gmo public", gmo_public),
        ("gmo private read", gmo_private),
        ("bars + strategy", bars_and_strategy),
        ("logs writable", logs_writable),
    ):
        results.append(_check(name, fn))

    ok = all(results)
    logger.info("=== {} ({}/{} checks passed) ===",
                "ALL GOOD" if ok else "PROBLEMS", sum(results), len(results))
    if ok:
        logger.info("Setup verified. The only untested path is sending a real order — "
                    "do one `gmo_trade ... --execute` round-trip once the account is funded.")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
