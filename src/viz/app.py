"""Dash application: Chart, Backtest and Maintenance tabs.

Launch::

    uv run --env-file .env.dev python -m src.viz.app
    # open http://localhost:8050

The strategy dropdowns are populated from :mod:`src.strategy.registry`, so newly
registered strategies appear automatically.
"""

from __future__ import annotations

import hashlib
import os
import pickle
import time
from pathlib import Path
from typing import Any

import dash
import pandas as pd
from dash import ClientsideFunction, Input, Output, State, dcc, html
from dash.exceptions import PreventUpdate
from sqlalchemy import select

from src.backtest.cycle import CycleResult, run_cycle
from src.config import get_settings
from src.core.types import Bar, Timeframe
from src.data.cache import load_cache
from src.db import get_session
from src.execution.gmo_client import LEVERAGE_MIN_SIZE
from src.logging_setup import configure_logging
from src.models import OHLCV
from src.simulator.multi_simulator import MultiSimulator
from src.strategy.registry import all_strategies, get_strategy
from src.viz import tasks
from src.viz.charts import build_chart, window_yranges

_TIMEFRAMES = [tf.value for tf in Timeframe]

# --- Caching layer -----------------------------------------------------------
# The Backtest tab was re-reading all ~44k bars from the DB and re-running two
# ~5y simulations (~2.5 min) on every tab-open, toggle, restart and (server-side)
# drag. Two caches fix that:
#   1. _DATA_CACHE  — the loaded DataCache per (product, tf), in-memory. Removes
#      the repeated DB reads behind renders and zoom/pan autoscale.
#   2. on-disk pickle of the CycleResult per (strategy, tf, product, fingerprint)
#      + an in-memory memo. A restart reads the pickle instead of re-simulating;
#      the fingerprint (#bars + last timestamp) invalidates it when data changes,
#      and the "Run backtest" button forces a recompute.
#
# The fingerprint tracks *data*, not *code*: when CycleResult's schema changes
# (new fields), old pickles deserialize without them and crash on attribute
# access. _CACHE_VERSION is folded into the key so any schema change invalidates
# stale pickles — bump it whenever CycleResult's fields change.
_CACHE_VERSION = "v2-multi"
_DATA_CACHE: dict[tuple[str | None, str], Any] = {}
_CYCLE_MEMO: dict[tuple[str, str, str | None, str], Any] = {}
_CYCLE_DIR = Path(os.environ.get("VIZ_CACHE_DIR", ".viz_cache"))


def _load_cache_cached(tf: Timeframe, product: str | None) -> Any:
    """Return a memoized :class:`DataCache` for ``(product, tf)``.

    ``to_frame()`` returns a fresh DataFrame each call, so sharing the instance
    is safe for callers that build their own frame.
    """
    key = (product, tf.value)
    if key not in _DATA_CACHE:
        _DATA_CACHE[key] = load_cache(tf, product=product)
    return _DATA_CACHE[key]


def _data_fingerprint(df: pd.DataFrame) -> str:
    """Cheap content fingerprint (#rows + last timestamp) for cache validity."""
    if df.empty:
        return "empty"
    return f"{len(df)}_{df.index[-1].isoformat()}"


def _run_cycle_cached(
    strategy: str, tf: Timeframe, product: str | None, fingerprint: str, *, force: bool
) -> Any:
    """Return the cycle result from memo / disk, recomputing on miss or ``force``."""
    key = (strategy, tf.value, product, fingerprint)
    if not force and key in _CYCLE_MEMO:
        return _CYCLE_MEMO[key]

    digest = hashlib.sha1(
        "__".join((*map(str, key), _CACHE_VERSION)).encode()
    ).hexdigest()[:16]
    path = _CYCLE_DIR / f"{strategy}_{tf.value}_{product}_{digest}.pkl"
    result = None
    if not force and path.exists():
        try:
            with path.open("rb") as fh:
                loaded = pickle.load(fh)
            # Guard against schema drift even within a version: a result missing
            # current fields is recomputed rather than crashing a render.
            if isinstance(loaded, CycleResult) and hasattr(loaded, "multi"):
                result = loaded
        except Exception:  # noqa: BLE001 — any unpickling failure → recompute
            result = None
    if result is None:
        result = run_cycle(strategy, tf, product=product)
        _CYCLE_DIR.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            pickle.dump(result, fh)
    _CYCLE_MEMO[key] = result
    return result

# Hard cap on candles rendered in any chart. ~44k bars choke the browser; 2160
# bars (= 90 days on 1h) keeps the figure light and interactions snappy. The
# Chart tab shows the most recent window (or the tail of a chosen date range); the
# Backtest tab pages through fixed 2160-bar windows via the Period navigator.
_MAX_VIEW_BARS = 2160


def _window_slice(df: pd.DataFrame, period: int) -> tuple[pd.DataFrame, int, int]:
    """Slice ``df`` to one ``_MAX_VIEW_BARS`` window for Backtest Period paging.

    Args:
        df: Full time-indexed OHLCV frame.
        period: Offset back from the most recent window (0 = latest).

    Returns:
        ``(window_df, clamped_offset, n_windows)`` — newest window is offset 0.
    """
    n = len(df)
    if n == 0:
        return df, 0, 1
    n_windows = max(1, -(-n // _MAX_VIEW_BARS))  # ceil
    offset = max(0, min(period, n_windows - 1))
    end_i = n - offset * _MAX_VIEW_BARS
    start_i = max(0, end_i - _MAX_VIEW_BARS)
    return df.iloc[start_i:end_i], offset, n_windows


def _trades_in_window(trades: list[Any], lo: pd.Timestamp, hi: pd.Timestamp) -> list[Any]:
    """Keep trades whose entry falls within ``[lo, hi]`` (tz-robust)."""
    out = []
    for t in trades:
        et = pd.Timestamp(t.entry_time)
        if et.tzinfo is None and lo.tzinfo is not None:
            et = et.tz_localize(lo.tz)
        elif et.tzinfo is not None and lo.tzinfo is None:
            et = et.tz_localize(None)
        if lo <= et <= hi:
            out.append(t)
    return out


def _products() -> list[str]:
    """Distinct product codes in the OHLCV table (for the chart product picker)."""
    with get_session() as s:
        found = s.execute(select(OHLCV.product).distinct().order_by(OHLCV.product)).scalars().all()
    return sorted({get_settings().product_code, *found})


def _timeframe_dropdown(id_: str, value: str = "5m") -> dcc.Dropdown:
    return dcc.Dropdown(
        id=id_,
        options=[{"label": tf, "value": tf} for tf in _TIMEFRAMES],
        value=value if value in _TIMEFRAMES else "5m",
        clearable=False,
        style={"width": "120px"},
    )


def _product_dropdown(id_: str, value: str | None = None) -> dcc.Dropdown:
    prods = _products()
    default = value or get_settings().product_code
    return dcc.Dropdown(
        id=id_,
        options=[{"label": p, "value": p} for p in prods],
        value=default if default in prods else prods[0],
        clearable=False,
        style={"width": "170px"},
    )


def _strategy_dropdown(id_: str, value: str | None = None) -> dcc.Dropdown:
    names = all_strategies()
    default = value if value in names else (names[0] if names else None)
    return dcc.Dropdown(
        id=id_,
        options=[{"label": n, "value": n} for n in names],
        value=default,
        clearable=False,
        style={"width": "260px"},
    )


# --- Live trading tab --------------------------------------------------------
# Bars come straight from GMO (the same source the live bot uses via
# src.execution.live_bars.recent_bars), so this tab needs no DB and reflects
# exactly what btc-autotrader sees. A short TTL cache avoids re-pulling ~25 days
# of klines on every toggle; the Refresh button forces a refetch.
_LIVE_BARS_TTL = 90.0  # seconds
_LIVE_BARS: dict[str, tuple[float, list[Bar]]] = {}
_LIVE_DISPLAY_DAYS = 14
_LIVE_ACCT_TTL = 8.0  # seconds — real GMO account read (positions + orders)
_LIVE_ACCT: dict[str, tuple[float, str]] = {}
# Per-component signal colours (cycled if a book has more components than colours).
_COMPONENT_COLORS = ["#2ca02c", "#1f77b4", "#9467bd", "#ff7f0e"]


def _live_books() -> list[tuple[str, str, str, int | None]]:
    """Return ``(label, strategy, symbol, slots)`` for each deployed live book.

    Mirrors what ``btc-autotrader`` runs (the ``AUTO_BOOKS`` env var or its
    defaults), so the selector always matches the live books.
    """
    from src.execution.auto_trader import _books

    out: list[tuple[str, str, str, int | None]] = []
    for name, symbol, slots in _books():
        out.append((f"{symbol.replace('_', '/')} — {name}", name, symbol, slots))
    return out


def _live_book_dropdown(id_: str) -> dcc.Dropdown:
    """Book selector; value encodes ``strategy|symbol|slots`` for the callback."""
    books = _live_books()
    opts = [
        {"label": label, "value": f"{name}|{symbol}|{'' if slots is None else slots}"}
        for label, name, symbol, slots in books
    ]
    return dcc.Dropdown(
        id=id_, options=opts, value=opts[0]["value"] if opts else None,
        clearable=False, style={"width": "100%"},
    )


def _live_bars_cached(symbol: str, *, force: bool) -> list[Bar]:
    """Return recent CLOSED 1h bars for ``symbol`` from GMO (TTL-cached)."""
    from src.execution.live_bars import recent_bars

    now = time.monotonic()
    hit = _LIVE_BARS.get(symbol)
    if not force and hit is not None and (now - hit[0]) < _LIVE_BARS_TTL:
        return hit[1]
    bars = recent_bars(symbol, days=25)
    _LIVE_BARS[symbol] = (now, bars)
    return bars


def _bars_frame(bars: list[Bar]) -> pd.DataFrame:
    """Bars -> time-indexed OHLCV frame in the shape :func:`build_chart` expects."""
    cols = ["open", "high", "low", "close", "volume"]
    if not bars:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(
        {c: [getattr(b, c) for b in bars] for c in cols},
        index=pd.DatetimeIndex([b.timestamp for b in bars], name="timestamp"),
    )


def _live_tab() -> html.Div:
    _pre = {"background": "#f7f7f7", "padding": "10px", "fontSize": "12px",
            "whiteSpace": "pre-wrap", "overflowY": "auto"}
    return html.Div(
        [
            # Left control pane.
            html.Div(
                [
                    html.Label("Live book"),
                    _live_book_dropdown("live-book"),
                    dcc.Checklist(
                        id="live-toggles",
                        options=[{"label": "Bollinger", "value": "bb"},
                                 {"label": "RSI", "value": "rsi"}],
                        value=["rsi"], inline=True, style={"marginTop": "8px"},
                    ),
                    html.Button("Refresh", id="live-refresh", n_clicks=0,
                                style={"marginTop": "8px", "width": "100%"}),
                    html.Div(
                        f"Hourly bars pulled live from GMO (last {_LIVE_DISPLAY_DAYS} "
                        "days). Combo signals are coloured per component strategy.",
                        style={"fontSize": "11px", "color": "#888", "margin": "8px 0"},
                    ),
                    html.Pre(id="live-status", children="(loading…)",
                             style={**_pre, "maxHeight": "360px"}),
                    html.Pre(id="live-ohlc", children="hover a bar for OHLC",
                             style={**_pre, "background": "#eef"}),
                ],
                style={"flex": "0 0 300px", "display": "flex",
                       "flexDirection": "column", "gap": "6px"},
            ),
            # Right chart pane.
            dcc.Loading(
                dcc.Graph(id="live-graph", style={"height": "820px", "width": "100%"}),
                type="default", parent_style={"flex": "1", "minWidth": "0"},
            ),
        ],
        style={"display": "flex", "gap": "12px", "marginTop": "8px"},
    )


def _read_gmo_account(symbol: str) -> str:
    """Real GMO account readout (live positions + active orders) for ``symbol``.

    Read-only and best-effort: if live reads are not configured (``USE_LIVE_API`` /
    GMO keys) or the API errors, return a short note rather than raising — the tab
    must still render. This is the AUTHORITATIVE account view (vs the simulated
    desired book above it), so the panel shows what is actually on the exchange.
    """
    from src.execution.gmo_client import gmo_account_client_from_settings

    try:
        client = gmo_account_client_from_settings(get_settings())
    except Exception as exc:  # not live / keys missing — degrade gracefully
        return f"GMO account : live read off ({type(exc).__name__}) — need USE_LIVE_API + keys"
    try:
        positions = client.get_open_positions(symbol)
        orders = client.get_active_orders(symbol)
    except Exception as exc:  # GmoApiError or transport — never crash the tab
        # Surface GMO's reason: e.g. ERR-5012 = key not permitted / IP not whitelisted
        # for this account (the funded account uses the prod box's keys+IP, so run the
        # viz there with .env.prod to see real positions).
        return f"GMO account : read error — {exc}"

    lines = [
        "── GMO ACCOUNT (live, authoritative) ──",
        f"positions {len(positions)} · active orders {len(orders)}",
    ]
    for p in positions:
        pnl = p.get("lossGain")
        pnl_s = f"  pnl {float(pnl):,.0f}" if pnl is not None else ""
        lines.append(
            f"  POS {str(p.get('side','?')):<4} {p.get('size','?')} @ {p.get('price','?')}"
            f"{pnl_s}  id={p.get('positionId','?')}"
        )
    if not positions:
        lines.append("  (no open positions)")
    for o in orders:
        lines.append(
            f"  ORD {str(o.get('settleType','?')):<5} {str(o.get('side','?')):<4} "
            f"{str(o.get('executionType','?')):<6} {o.get('size','?')} @ {o.get('price','?')}"
            f"  id={o.get('orderId','?')}"
        )
    if not orders:
        lines.append("  (no active orders)")
    return "\n".join(lines)


def _gmo_account_cached(symbol: str, *, force: bool) -> str:
    """TTL-cached :func:`_read_gmo_account` so toggles don't re-hit GMO; Refresh forces."""
    now = time.monotonic()
    hit = _LIVE_ACCT.get(symbol)
    if not force and hit is not None and (now - hit[0]) < _LIVE_ACCT_TTL:
        return hit[1]
    block = _read_gmo_account(symbol)
    _LIVE_ACCT[symbol] = (now, block)
    return block


def _format_live_status(
    name: str, symbol: str, slots: int | None, bars: list[Bar], state: Any,
) -> str:
    """One-screen readout of the authoritative live book state (mirrors heartbeat)."""
    last = state.last_bar_time
    close = bars[-1].close if bars else float("nan")
    lines = [
        f"Book : {name}",
        f"Pair : {symbol}   slots: {slots if slots is not None else 'default'}",
        f"Last bar : {last}",
        f"Close    : {close:,.4f}".rstrip("0").rstrip("."),
        "",
        "── DESIRED book (simulated, not your account) ──",
        f"open {len(state.positions)} · pending {len(state.pending_entries)} · "
        f"resting {len(state.working_orders)}",
    ]
    for p in state.positions:
        stop = f"{p.current_stop:,.2f}" if p.current_stop is not None else "—"
        tgt = f"{p.target:,.2f}" if p.target is not None else "—"
        lines.append(
            f"  {p.side.name:<5} @ {p.entry_price:,.2f}  stop {stop}  tp {tgt}  "
            f"{p.bars_held}b"
        )
    if not state.positions:
        lines.append("  (flat)")
    return "\n".join(lines)


def _chart_tab() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Label("Timeframe"),
                    _timeframe_dropdown("chart-timeframe"),
                    html.Label("Product"),
                    _product_dropdown("chart-product"),
                    dcc.Checklist(
                        id="chart-toggles",
                        options=[
                            {"label": "Bollinger", "value": "bb"},
                            {"label": "RSI", "value": "rsi"},
                            {"label": "Zigzag", "value": "zigzag"},
                        ],
                        value=["bb", "rsi", "zigzag"],
                        inline=True,
                    ),
                    html.Label("Period"),
                    dcc.DatePickerRange(
                        id="chart-daterange",
                        display_format="YYYY-MM-DD",
                        clearable=True,
                    ),
                    html.Button("Reload", id="chart-reload", n_clicks=0),
                ],
                style={"display": "flex", "gap": "12px", "alignItems": "center"},
            ),
            html.Div(
                f"Up to {_MAX_VIEW_BARS:,} bars shown (most recent, or the tail of a "
                "chosen Period). Scroll/zoom to pan, double-click to reset.",
                style={"fontSize": "12px", "color": "#888", "margin": "4px 0"},
            ),
            # Explicit pixel height so the bare graph matches the Backtest tab's
            # graph (whose flex row gives it a definite height); without it a
            # block-level dcc.Graph collapses below the figure's declared height.
            dcc.Graph(id="chart-graph", style={"height": "820px"}),
        ]
    )


def _backtest_tab() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Label("Timeframe"),
                    _timeframe_dropdown("bt-timeframe", value="1h"),
                    html.Label("Product"),
                    _product_dropdown("bt-product", value="GMO_BTC_JPY"),
                    html.Label("Strategy"),
                    _strategy_dropdown("bt-strategy", value="density_breakout"),
                    dcc.Checklist(
                        id="bt-toggles",
                        options=[
                            {"label": "Bollinger", "value": "bb"},
                            {"label": "RSI", "value": "rsi"},
                            {"label": "Zigzag", "value": "zigzag"},
                        ],
                        value=["bb", "rsi"],
                        inline=True,
                    ),
                    html.Button("Run backtest", id="bt-run", n_clicks=0),
                ],
                style={"display": "flex", "gap": "12px", "alignItems": "center"},
            ),
            # Period navigator: page through fixed _MAX_VIEW_BARS windows of the
            # full series. The cycle/metrics are full-history; this only moves the
            # plotted window (and the trades shown).
            html.Div(
                [
                    html.Label("Period"),
                    html.Button("◀ Prev", id="bt-prev", n_clicks=0),
                    html.Span(
                        id="bt-period-label",
                        children="latest",
                        style={"minWidth": "320px", "textAlign": "center",
                               "fontSize": "13px", "color": "#444"},
                    ),
                    html.Button("Next ▶", id="bt-next", n_clicks=0),
                    dcc.Store(id="bt-period", data=0),
                ],
                style={"display": "flex", "gap": "12px", "alignItems": "center",
                       "margin": "6px 0"},
            ),
            html.Div(
                [
                    # The backtest runs two full simulations (~45s on 5y 1h data),
                    # so wrap the graph in a spinner — otherwise the chart looks
                    # dead-empty mid-run rather than loading.
                    dcc.Loading(
                        dcc.Graph(
                            id="bt-graph",
                            style={"height": "820px", "width": "100%"},
                        ),
                        type="default",
                        # NB: `style` styles the spinner; `parent_style` styles the
                        # wrapper that is the actual flex child — so the graph keeps
                        # its 3:1 width against the metrics panel.
                        parent_style={"flex": "3", "minWidth": "0"},
                    ),
                    html.Div(
                        [
                            html.Pre(
                                id="bt-ohlc",
                                children="hover a bar for OHLC",
                                style={
                                    "background": "#eef",
                                    "padding": "8px",
                                    "marginBottom": "8px",
                                    "fontSize": "12px",
                                },
                            ),
                            html.Pre(
                                id="bt-metrics",
                                style={
                                    "background": "#f7f7f7",
                                    "padding": "12px",
                                    "overflowY": "auto",
                                    "maxHeight": "740px",
                                },
                            ),
                        ],
                        style={"flex": "1"},
                    ),
                ],
                style={"display": "flex", "gap": "12px"},
            ),
        ]
    )


def _maintenance_tab() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Label("Timeframe"),
                    _timeframe_dropdown("maint-timeframe"),
                    html.Label("Strategy"),
                    _strategy_dropdown("maint-strategy"),
                    html.Button("Download OHLCV", id="maint-download", n_clicks=0),
                    html.Button("Run benchmark cycle", id="maint-benchmark", n_clicks=0),
                ],
                style={"display": "flex", "gap": "12px", "alignItems": "center"},
            ),
            html.P(id="maint-status", style={"fontStyle": "italic"}),
            dcc.Interval(id="maint-poll", interval=1500, n_intervals=0),
            html.Pre(
                id="maint-log",
                style={
                    "background": "#1e1e1e",
                    "color": "#d4d4d4",
                    "padding": "12px",
                    "height": "560px",
                    "overflowY": "auto",
                },
            ),
        ]
    )


def _slice_window(
    df: pd.DataFrame,
    start_date: str | None,
    end_date: str | None,
    *,
    default_bars: int,
) -> pd.DataFrame:
    """Restrict a chart frame to a date range, or the most recent N bars.

    Args:
        df: Full time-indexed OHLCV frame.
        start_date: Inclusive start date (``YYYY-MM-DD``) or ``None``.
        end_date: Inclusive end date or ``None``.
        default_bars: Bars to keep when no date range is chosen (recency window).

    Returns:
        The sliced frame.
    """
    if df.empty:
        return df
    if not start_date and not end_date:
        return df.tail(default_bars)
    idx = df.index
    naive = (
        idx.tz_localize(None)
        if isinstance(idx, pd.DatetimeIndex) and idx.tz is not None
        else pd.DatetimeIndex(idx)
    )
    start_ts = pd.to_datetime(start_date) if start_date else None
    end_ts = pd.to_datetime(end_date) + pd.Timedelta(days=1) if end_date else None
    if start_ts is not None and end_ts is not None:
        mask = (naive >= start_ts) & (naive < end_ts)
    elif start_ts is not None:
        mask = naive >= start_ts
    else:
        assert end_ts is not None  # guaranteed: not both None (checked above)
        mask = naive < end_ts
    return df[mask]


def _autoscale_figure(
    relayout: dict[str, Any] | None,
    figure: dict[str, Any] | None,
    timeframe: str,
    *,
    product: str | None = None,
    show_bb: bool,
    show_rsi: bool,
) -> dict[str, Any]:
    """Rescale a 3-panel figure's y-axes to the visible x-window on zoom/pan.

    Shared by the Chart and Backtest tabs. A narrow time slice would otherwise be
    flattened against the full-history price range (Plotly does not auto-rescale
    y on x-zoom).

    Args:
        relayout: The graph's ``relayoutData``.
        figure: The current figure dict.
        timeframe: Timeframe whose OHLCV to reload for the window extents.
        show_bb: Whether Bollinger Bands are plotted (affects the price range).
        show_rsi: Whether the RSI panel is present.

    Returns:
        The updated figure dict.

    Raises:
        PreventUpdate: If the event is not an x-zoom/pan/reset.
    """
    if not relayout or not figure:
        raise PreventUpdate
    layout = figure["layout"]

    # Reset (double-click / autoscale on any panel): re-enable auto-range.
    if relayout.get("autosize") or any(
        k.startswith("xaxis") and k.endswith(".autorange") for k in relayout
    ):
        for ax in ("yaxis", "yaxis2", "yaxis3"):
            if ax in layout:
                layout[ax].pop("range", None)
                layout[ax]["autorange"] = True
        return figure

    # A zoom/pan on any (shared) x-axis: xaxis / xaxis2 / xaxis3 .range[...].
    x0 = next((v for k, v in relayout.items() if k.endswith(".range[0]") and "xaxis" in k), None)
    x1 = next((v for k, v in relayout.items() if k.endswith(".range[1]") and "xaxis" in k), None)
    if x0 is None or x1 is None:
        raise PreventUpdate  # not an x-zoom/pan event

    df = _load_cache_cached(Timeframe(timeframe), product).to_frame()
    try:
        ranges = window_yranges(df, str(x0), str(x1), show_bb=show_bb, show_rsi=show_rsi)
    except (ValueError, TypeError):
        raise PreventUpdate  # non-datetime range (e.g. an empty figure's -1..6)
    if not ranges:
        raise PreventUpdate
    for ax, rng in ranges.items():
        layout.setdefault(ax, {})
        layout[ax]["range"] = rng
        layout[ax]["autorange"] = False
    return figure


def create_app() -> dash.Dash:
    """Build and return the Dash app (callbacks registered)."""
    app = dash.Dash(__name__, title="BTC/JPY Scalping Bot")
    app.layout = html.Div(
        [
            html.H2("BTC/JPY Scalping Bot"),
            dcc.Tabs(
                id="tabs",
                value="chart",
                children=[
                    dcc.Tab(label="Chart", value="chart", children=_chart_tab()),
                    dcc.Tab(label="Backtest", value="backtest", children=_backtest_tab()),
                    dcc.Tab(label="Live trading", value="live", children=_live_tab()),
                    dcc.Tab(label="Maintenance", value="maintenance", children=_maintenance_tab()),
                ],
            ),
        ],
        style={"fontFamily": "sans-serif", "margin": "16px"},
    )
    _register_callbacks(app)
    return app


def _register_callbacks(app: dash.Dash) -> None:
    @app.callback(
        Output("chart-graph", "figure"),
        Input("chart-reload", "n_clicks"),
        Input("chart-daterange", "start_date"),
        Input("chart-daterange", "end_date"),
        State("chart-timeframe", "value"),
        State("chart-product", "value"),
        State("chart-toggles", "value"),
    )
    def _update_chart(_clicks, start_date, end_date, timeframe, product, toggles):  # type: ignore[no-untyped-def]
        tf = Timeframe(timeframe)
        toggles = toggles or []
        show_bb, show_rsi, show_zz = "bb" in toggles, "rsi" in toggles, "zigzag" in toggles
        df = _load_cache_cached(tf, product).to_frame()
        # Cap to the most recent _MAX_VIEW_BARS (or the tail of a chosen range) so
        # the browser never renders the full multi-year series.
        df = _slice_window(df, start_date, end_date, default_bars=_MAX_VIEW_BARS)
        if len(df) > _MAX_VIEW_BARS:
            df = df.tail(_MAX_VIEW_BARS)
        return build_chart(df, show_bb=show_bb, show_rsi=show_rsi, show_zigzag=show_zz, height=820)

    @app.callback(
        Output("chart-graph", "figure", allow_duplicate=True),
        Input("chart-graph", "relayoutData"),
        State("chart-graph", "figure"),
        State("chart-timeframe", "value"),
        State("chart-product", "value"),
        State("chart-toggles", "value"),
        prevent_initial_call=True,
    )
    def _autoscale_chart_y(relayout, figure, timeframe, product, toggles):  # type: ignore[no-untyped-def]
        return _autoscale_figure(
            relayout,
            figure,
            timeframe,
            product=product,
            show_bb="bb" in (toggles or []),
            show_rsi="rsi" in (toggles or []),
        )

    @app.callback(
        Output("bt-period", "data"),
        Input("bt-prev", "n_clicks"),
        Input("bt-next", "n_clicks"),
        Input("bt-timeframe", "value"),
        Input("bt-product", "value"),
        State("bt-period", "data"),
        prevent_initial_call=True,
    )
    def _bt_period_nav(_prev, _next, timeframe, product, period):  # type: ignore[no-untyped-def]
        # Prev = older window, Next = newer; changing timeframe/product resets to
        # the most recent window (the window count depends on the data length).
        trig = dash.ctx.triggered_id
        if trig in ("bt-timeframe", "bt-product"):
            return 0
        df = _load_cache_cached(Timeframe(timeframe), product).to_frame()
        n_windows = max(1, -(-len(df) // _MAX_VIEW_BARS))
        cur = period or 0
        if trig == "bt-prev":
            cur += 1
        elif trig == "bt-next":
            cur -= 1
        return max(0, min(cur, n_windows - 1))

    @app.callback(
        Output("bt-graph", "figure"),
        Output("bt-metrics", "children"),
        Output("bt-period-label", "children"),
        Input("tabs", "value"),
        Input("bt-run", "n_clicks"),
        Input("bt-timeframe", "value"),
        Input("bt-product", "value"),
        Input("bt-strategy", "value"),
        Input("bt-toggles", "value"),
        Input("bt-period", "data"),
    )
    def _backtest_tab_cb(active_tab, _clicks, timeframe, product, strategy, toggles, period):  # type: ignore[no-untyped-def]
        # RENDER-ONLY: the single owner that *builds* the figure. Zoom/pan,
        # TP/SL-hover and the OHLC readout are handled clientside (see
        # assets/bt_interactions.js) so they never round-trip the figure.
        if active_tab != "backtest":
            raise PreventUpdate
        toggles = toggles or []
        show_bb, show_rsi, show_zigzag = "bb" in toggles, "rsi" in toggles, "zigzag" in toggles
        trig = {t["prop_id"] for t in (dash.ctx.triggered or [])}

        tf = Timeframe(timeframe)
        df = _load_cache_cached(tf, product).to_frame()
        if df.empty or not strategy:
            return build_chart(df), "No data for this timeframe/product. Collect/backtest first.", "—"
        # run_cycle already simulates in-sample + OOS over the FULL series; reuse
        # its trades for the chart instead of a third full simulation. Served from
        # disk/memo cache (keyed by a data fingerprint so it survives restarts but
        # invalidates on new data); the "Run backtest" button forces a recompute.
        force = "bt-run.n_clicks" in trig
        result = _run_cycle_cached(strategy, tf, product, _data_fingerprint(df), force=force)
        # Only the current Period window (and its trades) is plotted — keeps the
        # figure light; the metrics panel stays full-history.
        win, offset, n_windows = _window_slice(df, period or 0)
        lo, hi = win.index[0], win.index[-1]
        wtrades = _trades_in_window(result.trades, lo, hi)
        fig = build_chart(
            win,
            show_bb=show_bb,
            show_rsi=show_rsi,
            show_zigzag=show_zigzag,
            trades=wtrades,
        )
        label = (
            f"window {n_windows - offset}/{n_windows}  ·  "
            f"{lo:%Y-%m-%d} → {hi:%Y-%m-%d}  ·  {len(wtrades)} trades"
        )
        return fig, _format_metrics(result), label

    # --- Clientside interactions (no figure round-trip) ----------------------
    app.clientside_callback(  # type: ignore[no-untyped-call]
        ClientsideFunction(namespace="bt", function_name="autoscale"),
        Output("bt-graph", "figure", allow_duplicate=True),
        Input("bt-graph", "relayoutData"),
        State("bt-graph", "figure"),
        prevent_initial_call=True,
    )
    app.clientside_callback(  # type: ignore[no-untyped-call]
        ClientsideFunction(namespace="bt", function_name="tpsl"),
        Output("bt-graph", "figure", allow_duplicate=True),
        Input("bt-graph", "hoverData"),
        State("bt-graph", "figure"),
        prevent_initial_call=True,
    )
    app.clientside_callback(  # type: ignore[no-untyped-call]
        ClientsideFunction(namespace="bt", function_name="ohlc"),
        Output("bt-ohlc", "children"),
        Input("bt-graph", "hoverData"),
        State("bt-graph", "figure"),
        prevent_initial_call=True,
    )

    # --- Live trading tab ----------------------------------------------------
    @app.callback(
        Output("live-graph", "figure"),
        Output("live-status", "children"),
        Input("tabs", "value"),
        Input("live-refresh", "n_clicks"),
        Input("live-book", "value"),
        Input("live-toggles", "value"),
    )
    def _live_tab_cb(active_tab, _clicks, book_val, toggles):  # type: ignore[no-untyped-def]
        if active_tab != "live" or not book_val:
            raise PreventUpdate
        toggles = toggles or []
        show_bb, show_rsi = "bb" in toggles, "rsi" in toggles
        name, symbol, slots_s = book_val.split("|")
        slots = int(slots_s) if slots_s else None

        trig = {t["prop_id"] for t in (dash.ctx.triggered or [])}
        force = "live-refresh.n_clicks" in trig
        bars = _live_bars_cached(symbol, force=force)
        df = _bars_frame(bars)
        if df.empty:
            return build_chart(df), f"No bars fetched for {symbol}. Check GMO connectivity."

        size = LEVERAGE_MIN_SIZE.get(symbol, 0.001)
        cutoff = df.index[-1] - pd.Timedelta(days=_LIVE_DISPLAY_DAYS)
        win = df[df.index >= cutoff]
        lo, hi = win.index[0], win.index[-1]

        # Per-component standalone simulations -> one coloured overlay each. The
        # combo's components peak below its 12-slot budget with zero historical
        # contention, so standalone ≈ the shared book (whose authoritative state is
        # shown in the status panel via live_state()).
        book_strat = get_strategy(name)
        if slots is not None:
            book_strat.max_slots = slots
        groups: list[tuple[str, str, list[Any]]] = []
        for i, comp in enumerate(book_strat.components):
            comp.reset()
            trades = MultiSimulator(comp, size=size).run(bars).trades
            wtrades = _trades_in_window(trades, lo, hi)
            groups.append((comp.name, _COMPONENT_COLORS[i % len(_COMPONENT_COLORS)], wtrades))

        fig = build_chart(win, show_bb=show_bb, show_rsi=show_rsi, trade_groups=groups)

        book_strat.reset()
        state = MultiSimulator(book_strat, size=size).live_state(bars)
        status = _format_live_status(name, symbol, slots, bars, state)
        status += "\n\n" + _gmo_account_cached(symbol, force=force)
        return fig, status

    # Reuse the Backtest tab's clientside interactions verbatim (figure stays in
    # the browser; same UX — zoom-autoscale, TP/SL hover, OHLC readout).
    app.clientside_callback(  # type: ignore[no-untyped-call]
        ClientsideFunction(namespace="bt", function_name="autoscale"),
        Output("live-graph", "figure", allow_duplicate=True),
        Input("live-graph", "relayoutData"),
        State("live-graph", "figure"),
        prevent_initial_call=True,
    )
    app.clientside_callback(  # type: ignore[no-untyped-call]
        ClientsideFunction(namespace="bt", function_name="tpsl"),
        Output("live-graph", "figure", allow_duplicate=True),
        Input("live-graph", "hoverData"),
        State("live-graph", "figure"),
        prevent_initial_call=True,
    )
    app.clientside_callback(  # type: ignore[no-untyped-call]
        ClientsideFunction(namespace="bt", function_name="ohlc"),
        Output("live-ohlc", "children"),
        Input("live-graph", "hoverData"),
        State("live-graph", "figure"),
        prevent_initial_call=True,
    )

    @app.callback(
        Output("maint-status", "children"),
        Input("maint-download", "n_clicks"),
        Input("maint-benchmark", "n_clicks"),
        State("maint-timeframe", "value"),
        State("maint-strategy", "value"),
        prevent_initial_call=True,
    )
    def _maintenance(_dl: int, _bm: int, timeframe: str, strategy: str):  # type: ignore[no-untyped-def]
        triggered = dash.ctx.triggered_id
        tf = Timeframe(timeframe)
        if triggered == "maint-download":
            from src.data.collect import collect

            def _download() -> None:
                collect(tf)

            started = tasks.run_async(f"collect {tf.value}", _download)
        elif triggered == "maint-benchmark":

            def _benchmark() -> None:
                run_cycle(strategy, tf)

            started = tasks.run_async(f"cycle {strategy}", _benchmark)
        else:
            started = False
        return "Task started." if started else "A task is already running — wait."

    @app.callback(
        Output("maint-log", "children"),
        Input("maint-poll", "n_intervals"),
    )
    def _poll_log(_n: int):  # type: ignore[no-untyped-def]
        return tasks.get_log_text()


def _format_metrics(result: object) -> str:
    assert isinstance(result, CycleResult)
    m_in, m_oos = result.in_sample, result.oos
    lines = [
        f"Strategy: {result.strategy}",
        f"SHIP: {result.ship}",
        f"Buy & Hold BTC/JPY: {result.benchmark_return:+.4f}",
    ]
    if result.multi:
        lines += [
            "",
            "MULTI-POSITION — judged by annualised EQUITY Sharpe (per-trade below"
            " is diagnostic):",
            f"  Equity Sharpe  IS {result.equity_sharpe_in:>+7.3f}   "
            f"OOS {result.equity_sharpe_oos:>+7.3f}   (B&H IS {result.bench_sharpe:+.3f})",
        ]
    lines += [
        "",
        "                 in-sample      OOS",
        f"Sharpe         {m_in.sharpe:>10.3f} {m_oos.sharpe:>10.3f}",
        f"Sortino        {m_in.sortino:>10.3f} {m_oos.sortino:>10.3f}",
        f"Win rate       {m_in.win_rate:>10.3f} {m_oos.win_rate:>10.3f}",
        f"Max DD         {m_in.max_dd:>10.4f} {m_oos.max_dd:>10.4f}",
        f"Total return   {m_in.total_return:>10.4f} {m_oos.total_return:>10.4f}",
        f"Fees (JPY)     {m_in.total_cost:>10.1f} {m_oos.total_cost:>10.1f}",
        f"# trades       {m_in.n_trades:>10d} {m_oos.n_trades:>10d}",
        "",
        "All return/Sharpe figures are NET of trading fees.",
        "Buy & Hold benchmark is gross (no trading cost).",
        "OVERFIT if OOS Sharpe < 0 or OOS DD > 2x IS DD.",
    ]
    return "\n".join(lines)


def main() -> None:
    """Launch the development server.

    Set ``VIZ_DEBUG=true`` to enable Dash dev tools: the server auto-restarts on
    code edits and the browser hot-reloads, so UI changes apply without a manual
    restart + hard refresh.
    """
    configure_logging(get_settings().log_level)
    debug = os.getenv("VIZ_DEBUG", "false").strip().lower() in {"1", "true", "yes", "on"}
    port = int(os.getenv("VIZ_PORT", "8050"))
    # Bind 0.0.0.0 by default (direct access); the systemd unit sets
    # VIZ_HOST=127.0.0.1 so only the nginx reverse proxy can reach it.
    host = os.getenv("VIZ_HOST", "0.0.0.0")
    app = create_app()
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
