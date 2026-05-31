"""Dash application: Chart, Backtest and Maintenance tabs.

Launch::

    uv run --env-file .env.dev python -m src.viz.app
    # open http://localhost:8050

The strategy dropdowns are populated from :mod:`src.strategy.registry`, so newly
registered strategies appear automatically.
"""

from __future__ import annotations

import os
from typing import Any

import dash
import pandas as pd
from dash import Input, Output, State, dcc, html
from dash.exceptions import PreventUpdate

from src.backtest.cycle import run_cycle
from src.config import get_settings
from src.core.types import Timeframe
from src.data.cache import load_cache
from src.logging_setup import configure_logging
from src.strategy.registry import all_strategies
from src.viz import tasks
from src.viz.charts import build_chart, window_yranges

_TIMEFRAMES = [tf.value for tf in Timeframe]


def _timeframe_dropdown(id_: str) -> dcc.Dropdown:
    return dcc.Dropdown(
        id=id_,
        options=[{"label": tf, "value": tf} for tf in _TIMEFRAMES],
        value="5m",
        clearable=False,
        style={"width": "120px"},
    )


def _strategy_dropdown(id_: str) -> dcc.Dropdown:
    names = all_strategies()
    return dcc.Dropdown(
        id=id_,
        options=[{"label": n, "value": n} for n in names],
        value=names[0] if names else None,
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
                "No date range = most recent 600 bars.",
                style={"fontSize": "12px", "color": "#888", "margin": "4px 0"},
            ),
            dcc.Graph(id="chart-graph"),
        ]
    )


def _backtest_tab() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Label("Timeframe"),
                    _timeframe_dropdown("bt-timeframe"),
                    html.Label("Strategy"),
                    _strategy_dropdown("bt-strategy"),
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
            dcc.Store(id="bt-ohlc-store"),
            html.Div(
                [
                    dcc.Graph(id="bt-graph", style={"flex": "3"}),
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


def _ohlc_store(df: pd.DataFrame) -> dict[str, list[float]]:
    """Build a {ISO timestamp: [O,H,L,C]} lookup for the OHLC hover pane.

    Keyed by the bar timestamp's ISO form. Plotly emits hover ``x`` in the same
    (tz-aware) form as the axis, and the callback re-parses through pandas, so
    keys match regardless of formatting.
    """
    out: dict[str, list[float]] = {}
    for ts, o, h, low, c in zip(
        df.index, df["open"], df["high"], df["low"], df["close"], strict=False
    ):
        out[pd.Timestamp(ts).isoformat()] = [float(o), float(h), float(low), float(c)]
    return out


def _draw_tpsl_lines(figure: dict[str, Any] | None, hoverdata: dict[str, Any] | None) -> dict[str, Any]:
    """Draw horizontal TP/SL lines for a hovered entry marker.

    Entry markers carry ``customdata = [tp_price, sl_price]`` (exactly length 2).
    Replaces any prior TP/SL shapes with dashed lines at those levels on the
    price panel; other shapes (e.g. the candle's OHLC customdata is length 4, and
    RSI 30/70 reference lines) are left alone.

    Raises:
        PreventUpdate: If not hovering an entry marker, or the lines are already
            drawn at these levels (avoids redundant redraws while hovering).
    """
    if not figure or not hoverdata:
        raise PreventUpdate
    points = hoverdata.get("points") or []
    cd = points[0].get("customdata") if points else None
    # Entry markers carry [tp, sl, entry_iso, exit_iso, exit_price]; nothing else
    # carries customdata, so anything shorter is not an entry.
    if not cd or len(cd) < 4:
        raise PreventUpdate
    tp, sl, entry_x, exit_x = cd[0], cd[1], cd[2], cd[3]
    exit_price = cd[4] if len(cd) > 4 else None
    ref_x = cd[5] if len(cd) > 5 else None
    ref_price = cd[6] if len(cd) > 6 else None

    layout = figure["layout"]
    # Skip redundant redraws while hovering the same entry (keyed on exit point).
    prior = [a for a in layout.get("annotations", []) if a.get("name") == "tpsl_exit"]
    if prior and prior[0].get("x") == exit_x:
        raise PreventUpdate

    # TP/SL as dashed segments over the trade's lifetime (entry -> exit), so it's
    # clear the trade ended before price may later have crossed a level.
    shapes = [
        s for s in layout.get("shapes", []) if not str(s.get("name", "")).startswith("tpsl_")
    ]
    for level, color, tag, lbl in (
        (tp, "#2ca02c", "tpsl_tp", "TP"),
        (sl, "#d62728", "tpsl_sl", "SL"),
    ):
        if level is None:
            continue
        shapes.append(
            {
                "type": "line",
                "xref": "x", "x0": entry_x, "x1": exit_x,
                "yref": "y", "y0": level, "y1": level,
                "line": {"color": color, "width": 1.4, "dash": "dash"},
                "name": tag,
                "label": {"text": f"{lbl} {level:,.0f}", "textposition": "start",
                          "font": {"color": color, "size": 11}},
            }
        )
    if not shapes:
        raise PreventUpdate

    # Dotted connector from the entry to the "outstanding" peak it bounced off.
    if ref_x is not None and ref_price is not None:
        shapes.append(
            {
                "type": "line",
                "xref": "x", "x0": ref_x, "x1": entry_x,
                "yref": "y", "y0": ref_price, "y1": ref_price,
                "line": {"color": "#8c564b", "width": 1, "dash": "dot"},
                "name": "tpsl_ref",
            }
        )
    layout["shapes"] = shapes

    # Mark the exit and the outstanding peak so they're findable.
    anns = [a for a in layout.get("annotations", []) if not str(a.get("name", "")).startswith("tpsl_")]
    if exit_price is not None:
        anns.append(
            {
                "name": "tpsl_exit", "xref": "x", "yref": "y",
                "x": exit_x, "y": exit_price, "text": "exit", "showarrow": True,
                "arrowhead": 2, "ax": 0, "ay": -28,
                "font": {"size": 11, "color": "#333"}, "bgcolor": "#ffffffcc",
            }
        )
    if ref_x is not None and ref_price is not None:
        anns.append(
            {
                "name": "tpsl_ref", "xref": "x", "yref": "y",
                "x": ref_x, "y": ref_price, "text": "outstanding peak",
                "showarrow": True, "arrowhead": 2, "ax": 0, "ay": -24,
                "font": {"size": 10, "color": "#8c564b"}, "bgcolor": "#ffffffcc",
            }
        )
    layout["annotations"] = anns
    return figure


def _is_zoom_relayout(relayout: dict[str, Any] | None) -> bool:
    """Whether ``relayout`` represents a genuine x-zoom with a real datetime range.

    Distinguishes a real user zoom/pan from a graph-mount event (``autosize`` or
    the empty figure's numeric ``-1..6`` range), so the latter triggers a render
    rather than a no-op autoscale.
    """
    if not isinstance(relayout, dict):
        return False
    for key, val in relayout.items():
        if "xaxis" in key and key.endswith(".range[0]"):
            try:
                import pandas as pd

                ts = pd.to_datetime(val)
            except (ValueError, TypeError):
                return False
            # Numeric placeholders (e.g. -1) parse to ~1970; require a real date.
            return bool(getattr(ts, "year", 0) > 2000)
    return False


def _autoscale_figure(
    relayout: dict[str, Any] | None,
    figure: dict[str, Any] | None,
    timeframe: str,
    *,
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

    df = load_cache(Timeframe(timeframe)).to_frame()
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
        State("chart-toggles", "value"),
    )
    def _update_chart(_clicks, start_date, end_date, timeframe, toggles):  # type: ignore[no-untyped-def]
        tf = Timeframe(timeframe)
        toggles = toggles or []
        df = load_cache(tf).to_frame()
        df = _slice_window(df, start_date, end_date, default_bars=600)
        return build_chart(
            df,
            show_bb="bb" in toggles,
            show_rsi="rsi" in toggles,
            show_zigzag="zigzag" in toggles,
            height=820,
        )

    @app.callback(
        Output("chart-graph", "figure", allow_duplicate=True),
        Input("chart-graph", "relayoutData"),
        State("chart-graph", "figure"),
        State("chart-timeframe", "value"),
        State("chart-toggles", "value"),
        prevent_initial_call=True,
    )
    def _autoscale_chart_y(relayout, figure, timeframe, toggles):  # type: ignore[no-untyped-def]
        return _autoscale_figure(
            relayout,
            figure,
            timeframe,
            show_bb="bb" in (toggles or []),
            show_rsi="rsi" in (toggles or []),
        )

    @app.callback(
        Output("bt-graph", "figure"),
        Output("bt-metrics", "children"),
        Output("bt-ohlc-store", "data"),
        Input("tabs", "value"),
        Input("bt-run", "n_clicks"),
        Input("bt-timeframe", "value"),
        Input("bt-strategy", "value"),
        Input("bt-toggles", "value"),
        Input("bt-graph", "relayoutData"),
        Input("bt-graph", "hoverData"),
        State("bt-graph", "figure"),
    )
    def _backtest_tab_cb(active_tab, _clicks, timeframe, strategy, toggles, relayout, hoverdata, figure):  # type: ignore[no-untyped-def]
        # Single owner of bt-graph so a graph-mount relayout can't race the render
        # through a duplicate output. RENDER unless this is unambiguously a
        # zoom or an entry-marker hover; that keeps rendering deterministic
        # regardless of which trigger Dash attributes when the tab mounts.
        if active_tab != "backtest":
            raise PreventUpdate
        toggles = toggles or []
        show_bb, show_rsi, show_zigzag = "bb" in toggles, "rsi" in toggles, "zigzag" in toggles

        trig = {t["prop_id"] for t in (dash.ctx.triggered or [])}
        if trig == {"bt-graph.hoverData"}:
            # Hovering an entry marker -> draw its TP/SL lines (keep metrics/store).
            return _draw_tpsl_lines(figure, hoverdata), dash.no_update, dash.no_update
        if trig == {"bt-graph.relayoutData"} and _is_zoom_relayout(relayout):
            return (
                _autoscale_figure(relayout, figure, timeframe, show_bb=show_bb, show_rsi=show_rsi),
                dash.no_update,
                dash.no_update,
            )

        # Tab opened / timeframe / strategy / toggles / Run button / mount -> render.
        tf = Timeframe(timeframe)
        cache = load_cache(tf)
        df = cache.to_frame()
        if df.empty or not strategy:
            return build_chart(df), "No data for this timeframe. Collect/backtest first.", {}
        # run_cycle already simulates in-sample + OOS; reuse its trades for the
        # chart instead of a third full simulation.
        result = run_cycle(strategy, tf)
        fig = build_chart(
            df,
            show_bb=show_bb,
            show_rsi=show_rsi,
            show_zigzag=show_zigzag,
            trades=result.trades,
        )
        return fig, _format_metrics(result), _ohlc_store(df)

    @app.callback(
        Output("bt-ohlc", "children"),
        Input("bt-graph", "hoverData"),
        State("bt-ohlc-store", "data"),
        prevent_initial_call=True,
    )
    def _ohlc_readout(hoverdata, store):  # type: ignore[no-untyped-def]
        # Look up the bar's OHLC by the hovered timestamp, regardless of which
        # trace is closest (EMA, candle, ...) — they share the same x.
        points = (hoverdata or {}).get("points") or []
        if not points or not store:
            raise PreventUpdate
        try:
            key = pd.to_datetime(points[0].get("x")).isoformat()
        except (ValueError, TypeError):
            raise PreventUpdate
        ohlc = store.get(key)
        if not ohlc:
            raise PreventUpdate
        o, h, low, c = ohlc
        return (
            f"{key.replace('T', '  ')}\n"
            f"O {o:,.0f}   H {h:,.0f}\n"
            f"L {low:,.0f}   C {c:,.0f}"
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
    app = create_app()
    app.run(host="0.0.0.0", port=8050, debug=debug)


if __name__ == "__main__":
    main()
