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
from pathlib import Path
from typing import Any

import dash
import pandas as pd
from dash import ClientsideFunction, Input, Output, State, dcc, html
from dash.exceptions import PreventUpdate
from sqlalchemy import select

from src.backtest.cycle import run_cycle
from src.config import get_settings
from src.core.types import Timeframe
from src.data.cache import load_cache
from src.db import get_session
from src.logging_setup import configure_logging
from src.models import OHLCV
from src.strategy.registry import all_strategies
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

    digest = hashlib.sha1("__".join(map(str, key)).encode()).hexdigest()[:16]
    path = _CYCLE_DIR / f"{strategy}_{tf.value}_{product}_{digest}.pkl"
    if not force and path.exists():
        with path.open("rb") as fh:
            result = pickle.load(fh)
    else:
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
    from src.backtest.cycle import CycleResult

    assert isinstance(result, CycleResult)
    m_in, m_oos = result.in_sample, result.oos
    lines = [
        f"Strategy: {result.strategy}",
        f"SHIP: {result.ship}",
        f"Buy & Hold BTC/JPY: {result.benchmark_return:+.4f}",
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
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=debug)


if __name__ == "__main__":
    main()
