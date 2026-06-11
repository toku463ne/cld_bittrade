"""Backtest-history importer for the GMO Coin public klines API.

Bulk-imports historical ``BTC_JPY`` (GMO Coin leveraged) OHLCV bars from
https://api.coin.z.com/public into the ``ohlcv`` table, for **backtesting only**.
The live/dev path stays on the real bitFlyer feed (:mod:`src.data.feed`); this
module never touches the exchange's private/order API.

Why a separate path (not :mod:`src.data.history`)
-------------------------------------------------
The standard pipeline stores raw executions and re-aggregates contiguous ticks.
GMO serves *pre-aggregated* klines, so there are no executions to store — these
rows are written directly to ``ohlcv`` and are **not** backed by ``execution``
rows. Treat them as a second-class, backtest-only data source.

Venue caveat
------------
This is **GMO Coin BTC_JPY (leverage)**, a *different exchange* from the bot's
live venue (bitFlyer ``FX_BTC_JPY``). Prices correlate strongly but differ in
spread, funding and microstructure, so it is a proxy for strategy-level
backtesting, not a tick-faithful replica of bitFlyer. By default the bars are
stored under product ``GMO_BTC_JPY`` to keep provenance honest — run backtests
with ``--product GMO_BTC_JPY`` (or pass ``product=`` to ``load_cache``).

Verified behaviour (2026-06)
----------------------------
- ``klines?symbol=BTC_JPY&interval=<i>&date=YYYYMMDD`` returns one JST day, e.g.
  24 rows for ``1hour``. ``date`` is ``YYYYMMDD`` for *all* intervals.
- Response: ``{"status":0,"data":[{openTime,open,high,low,close,volume}]}`` with
  ``openTime`` an ms-epoch **string** (UTC) and OHLCV as string decimals.
- Data goes back to GMO's launch (≈2018-06). 1m/5m/15m/1h are native (no resample).
- The public API throttles bursts by returning HTTP 404 with ``ERR-5207``; this
  importer paces requests and retries those with backoff, so a *persistent* 404
  is treated as "no data for that day" (pre-inception or a genuine gap) and
  recorded in the coverage report rather than aborting.

Usage (backtest DB only)::

    uv run --env-file .env.bt python -m src.data.import_gmo \
        --from 2018-06-01 --to 2026-06-01 --timeframe all
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import requests
from loguru import logger
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.config import get_settings
from src.core.types import Bar, Timeframe
from src.db import get_session
from src.logging_setup import configure_logging
from src.models import OHLCV

KLINES_URL = "https://api.coin.z.com/public/v1/klines"
"""GMO Coin public klines endpoint."""

DEFAULT_SYMBOL = "BTC_JPY"
"""GMO leveraged BTC/JPY symbol (also the spot pair code)."""

DEFAULT_PRODUCT = "GMO_BTC_JPY"
"""Product code these bars are stored under (honest, venue-distinct provenance)."""

DEFAULT_START = date(2018, 6, 1)
"""Conservative earliest date; GMO klines reach back to its ≈2018 launch."""

# GMO interval string per project timeframe (all native, no resampling).
_GMO_INTERVAL: dict[Timeframe, str] = {
    Timeframe.M1: "1min",
    Timeframe.M5: "5min",
    Timeframe.M15: "15min",
    Timeframe.H1: "1hour",
}

_THROTTLE_CODE = "ERR-5207"
"""GMO error code returned (with HTTP 404) both for throttling and absent data."""

_MAX_RETRIES = 6
"""Backoff attempts on a throttled/absent-day response before giving up.

GMO returns the same HTTP 404 + ``ERR-5207`` for *throttling* and for *absent
data*, so generous retries are essential: too few and a throttle blip is
misrecorded as an empty day, punching a false gap into the history. Real
pre-inception days (before GMO's ≈2018 launch) still 404 after all retries and
are correctly logged as empty."""

_DEFAULT_PAUSE_S = 2.5
"""Delay between successive day requests. Empirically ~2.5 s avoids the burst
throttle that makes even valid dates 404; the public limit is ≈1 req/s but
bursts trip an aggressive cooldown."""

_BACKOFF_CAP_S = 60.0
"""Maximum single backoff sleep while waiting out a throttle cooldown."""

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; btc-scalping-bot/backtest)"}


@dataclass(slots=True)
class DayCoverage:
    """Per-day coverage diagnostics for the validate-and-report policy.

    Attributes:
        day: The source day (``YYYYMMDD``).
        n_bars: Bars obtained for the timeframe (0 if the day had no data).
        expected: Bars a fully-populated 24 h day would yield.
        present: Whether the API returned any data for the day.
        ok: Whether ``coverage`` met the configured minimum.
    """

    day: str
    n_bars: int
    expected: int
    present: bool
    ok: bool

    @property
    def coverage(self) -> float:
        """Fraction of the day's expected bars that were present (0..1)."""
        return self.n_bars / self.expected if self.expected else 0.0


@dataclass(slots=True)
class ImportReport:
    """Aggregate result of an import run for one timeframe.

    Attributes:
        timeframe: Target timeframe imported.
        product: Product code the bars were stored under.
        days_requested: Calendar days in the requested range.
        days_with_data: Days that returned at least one bar.
        bars_upserted: Total bars upserted into ``ohlcv``.
        empty_days: Days that returned no data (pre-inception or gaps).
        low_coverage: Days present but below the coverage threshold.
        coverages: Per-day coverage records.
    """

    timeframe: Timeframe
    product: str
    days_requested: int = 0
    days_with_data: int = 0
    bars_upserted: int = 0
    empty_days: list[str] = field(default_factory=list)
    low_coverage: list[DayCoverage] = field(default_factory=list)
    coverages: list[DayCoverage] = field(default_factory=list)


def _fetch_klines(
    session: requests.Session, symbol: str, interval: str, day: date
) -> list[dict[str, str]] | None:
    """Fetch one day's raw kline records, retrying throttled responses.

    Args:
        session: Reusable HTTP session.
        symbol: GMO symbol (e.g. ``BTC_JPY``).
        interval: GMO interval string (e.g. ``1hour``).
        day: The day to fetch.

    Returns:
        The list of raw kline dicts, or ``None`` if the day has no data after
        exhausting retries (treated as pre-inception / gap, not a hard error).

    Raises:
        requests.RequestException: On a persistent transport-level error.
        ValueError: If the API returns an unexpected error status.
    """
    params = {"symbol": symbol, "interval": interval, "date": day.strftime("%Y%m%d")}
    backoff = 3.0
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = session.get(KLINES_URL, params=params, headers=_HEADERS, timeout=30)
        except requests.RequestException as exc:
            logger.warning("GMO GET {} failed (attempt {}): {}", day, attempt, exc)
            time.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_CAP_S)
            continue

        if resp.status_code == 404:
            # 404 + ERR-5207 means either throttling or no data; back off and
            # retry. If it persists across all attempts we treat it as no data.
            body = resp.text
            if _THROTTLE_CODE in body and attempt < _MAX_RETRIES:
                logger.debug("Throttled on {} (attempt {}); backing off.", day, attempt)
                time.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_CAP_S)
                continue
            return None

        resp.raise_for_status()
        payload = resp.json()
        status = payload.get("status")
        if status != 0:
            # Non-zero status with a 200 is unexpected; surface it.
            raise ValueError(f"GMO API status {status} for {day}: {payload}")
        return payload.get("data") or []

    return None


def _to_bars(records: list[dict[str, str]]) -> list[Bar]:
    """Convert raw GMO kline dicts to ascending :class:`Bar` objects.

    Args:
        records: Raw kline dicts (string fields, ``openTime`` ms-epoch UTC).

    Returns:
        Bars in ascending time order.
    """
    bars = [
        Bar(
            timestamp=datetime.fromtimestamp(int(r["openTime"]) / 1000, tz=timezone.utc),
            open=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            volume=float(r["volume"]),
        )
        for r in records
    ]
    bars.sort(key=lambda b: b.timestamp)
    return bars


def _day_bar_count(product: str, timeframe: Timeframe, day: date) -> int:
    """Return how many bars already exist for ``day`` (UTC) — for resume/skip."""
    from sqlalchemy import func, select

    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    with get_session() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(OHLCV)
                .where(
                    OHLCV.product == product,
                    OHLCV.timeframe == timeframe.value,
                    OHLCV.timestamp >= start,
                    OHLCV.timestamp < end,
                )
            )
            or 0
        )


def _upsert_bars(bars: list[Bar], timeframe: Timeframe, product: str) -> int:
    """Idempotently upsert bars on the (product, timeframe, timestamp) key.

    Args:
        bars: Bars to persist.
        timeframe: Their timeframe.
        product: Product code to store under.

    Returns:
        The number of bar rows submitted for upsert.
    """
    if not bars:
        return 0
    rows = [
        {
            "product": product,
            "timeframe": timeframe.value,
            "timestamp": b.timestamp,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
        }
        for b in bars
    ]
    with get_session() as session:
        stmt = pg_insert(OHLCV).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_ohlcv_bar",
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
            },
        )
        session.execute(stmt)
    return len(rows)


def import_range(
    start: date,
    end: date,
    timeframe: Timeframe,
    *,
    symbol: str = DEFAULT_SYMBOL,
    product: str = DEFAULT_PRODUCT,
    min_coverage: float = 0.8,
    pause: float = _DEFAULT_PAUSE_S,
    skip_existing: bool = True,
) -> ImportReport:
    """Import GMO klines for ``[start, end]`` into ``ohlcv`` (backtest only).

    Iterates day by day (paced to respect the public rate limit). Per the
    validate-and-report policy, days that are missing or below ``min_coverage``
    are recorded in the returned report rather than aborting the run.

    Args:
        start: Inclusive first day.
        end: Inclusive last day.
        timeframe: Target timeframe.
        symbol: GMO symbol.
        product: Product code to store under.
        min_coverage: Coverage fraction below which a present day is flagged.
        pause: Seconds to wait between day requests.
        skip_existing: Skip the HTTP call for days already sufficiently stored
            (makes long imports cheaply resumable).

    Returns:
        An :class:`ImportReport` summarising the run.
    """
    interval = _GMO_INTERVAL[timeframe]
    expected_per_day = 86_400 // timeframe.seconds
    threshold = min_coverage * expected_per_day
    report = ImportReport(timeframe=timeframe, product=product)
    report.days_requested = (end - start).days + 1

    logger.info(
        "GMO import {} {} [{} .. {}] -> product {} (expect {} bars/day).",
        symbol,
        interval,
        start,
        end,
        product,
        expected_per_day,
    )

    with requests.Session() as session:
        day = start
        while day <= end:
            if skip_existing and _day_bar_count(product, timeframe, day) >= threshold:
                logger.debug("Skip {} (already stored).", day)
                day += timedelta(days=1)
                continue

            records = _fetch_klines(session, symbol, interval, day)
            if records is None:
                report.empty_days.append(day.strftime("%Y%m%d"))
                report.coverages.append(
                    DayCoverage(day.strftime("%Y%m%d"), 0, expected_per_day, False, False)
                )
                logger.warning("No data for {} {}.", day, interval)
            else:
                bars = _to_bars(records)
                cov = DayCoverage(
                    day=day.strftime("%Y%m%d"),
                    n_bars=len(bars),
                    expected=expected_per_day,
                    present=True,
                    ok=len(bars) >= threshold,
                )
                report.coverages.append(cov)
                report.days_with_data += 1
                report.bars_upserted += _upsert_bars(bars, timeframe, product)
                if not cov.ok:
                    report.low_coverage.append(cov)
                    logger.warning(
                        "Low coverage {} {}: {}/{} bars ({:.0%}).",
                        cov.day,
                        timeframe.value,
                        cov.n_bars,
                        cov.expected,
                        cov.coverage,
                    )
            time.sleep(pause)
            day += timedelta(days=1)

    _log_report(report)
    return report


def _log_report(report: ImportReport) -> None:
    """Emit the import summary for a timeframe run."""
    logger.info(
        "GMO import done: {} {} -> {} bars over {} day(s) with data "
        "(requested {} day(s)).",
        report.product,
        report.timeframe.value,
        report.bars_upserted,
        report.days_with_data,
        report.days_requested,
    )
    if report.empty_days:
        logger.info(
            "{} day(s) returned no data (pre-inception or gap): {}{}",
            len(report.empty_days),
            ", ".join(report.empty_days[:10]),
            " ..." if len(report.empty_days) > 10 else "",
        )
    if report.low_coverage:
        logger.warning(
            "{} present day(s) below coverage threshold: {}{}",
            len(report.low_coverage),
            ", ".join(f"{c.day}({c.coverage:.0%})" for c in report.low_coverage[:10]),
            " ..." if len(report.low_coverage) > 10 else "",
        )


def _parse_day(value: str) -> date:
    """Parse a ``YYYY-MM-DD`` CLI date."""
    return datetime.strptime(value, "%Y-%m-%d").date()


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Import historical GMO Coin BTC_JPY OHLCV klines "
        "(backtest only; stored under GMO_BTC_JPY by default)."
    )
    parser.add_argument(
        "--from",
        dest="start",
        type=_parse_day,
        default=DEFAULT_START,
        help=f"Start YYYY-MM-DD (default {DEFAULT_START}).",
    )
    parser.add_argument(
        "--to",
        dest="end",
        type=_parse_day,
        default=date.today(),
        help="End YYYY-MM-DD inclusive (default today).",
    )
    parser.add_argument(
        "--timeframe",
        choices=[*(tf.value for tf in Timeframe), "all"],
        default="1h",
        help="Target timeframe, or 'all' for 1m/5m/15m/1h.",
    )
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL, help="GMO symbol.")
    parser.add_argument(
        "--product", default=DEFAULT_PRODUCT, help="Product code to store under."
    )
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=0.8,
        help="Flag present days below this fraction of expected bars (default 0.8).",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=_DEFAULT_PAUSE_S,
        help="Seconds between day requests (rate-limit pacing).",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Re-fetch days even if already stored (default: skip to resume).",
    )
    args = parser.parse_args()

    if args.end < args.start:
        parser.error("--to must not be before --from")

    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.is_backtest:
        logger.warning(
            "Importing GMO bars into a non-backtest env ({}). This data is "
            "backtest-only; prefer --env-file .env.bt.",
            settings.env_name,
        )

    timeframes = (
        list(Timeframe) if args.timeframe == "all" else [Timeframe(args.timeframe)]
    )
    for tf in timeframes:
        import_range(
            args.start,
            args.end,
            tf,
            symbol=args.symbol,
            product=args.product,
            min_coverage=args.min_coverage,
            pause=args.pause,
            skip_existing=not args.no_skip_existing,
        )


if __name__ == "__main__":
    main()
