"""Dash application: Chart, Backtest and Maintenance tabs.

Launch::

    uv run --env-file .env.dev python -m src.viz.app
    # open http://localhost:8050

The strategy dropdowns are populated from :mod:`src.strategy.registry`, so newly
registered strategies appear automatically.
"""

from __future__ import annotations

import dash
from dash import Input, Output, State, dcc, html

from src.backtest.cycle import run_cycle
from src.config import get_settings
from src.core.types import Timeframe
from src.data.cache import load_cache
from src.logging_setup import configure_logging
from src.simulator import Simulator
from src.strategy.registry import all_strategies, get_strategy
from src.viz import tasks
from src.viz.charts import build_chart

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
                    html.Label("Strategy"),
                    _strategy_dropdown("chart-strategy"),
                    dcc.Checklist(
                        id="chart-toggles",
                        options=[
                            {"label": "Bollinger", "value": "bb"},
                            {"label": "RSI", "value": "rsi"},
                        ],
                        value=["bb", "rsi"],
                        inline=True,
                    ),
                    html.Button("Reload", id="chart-reload", n_clicks=0),
                ],
                style={"display": "flex", "gap": "12px", "alignItems": "center"},
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
                    html.Button("Run backtest", id="bt-run", n_clicks=0),
                ],
                style={"display": "flex", "gap": "12px", "alignItems": "center"},
            ),
            html.Div(
                [
                    dcc.Graph(id="bt-graph", style={"flex": "3"}),
                    html.Pre(
                        id="bt-metrics",
                        style={
                            "flex": "1",
                            "background": "#f7f7f7",
                            "padding": "12px",
                            "overflowY": "auto",
                            "maxHeight": "820px",
                        },
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


def create_app() -> dash.Dash:
    """Build and return the Dash app (callbacks registered)."""
    app = dash.Dash(__name__, title="BTC/JPY Scalping Bot")
    app.layout = html.Div(
        [
            html.H2("BTC/JPY Scalping Bot"),
            dcc.Tabs(
                [
                    dcc.Tab(label="Chart", children=_chart_tab()),
                    dcc.Tab(label="Backtest", children=_backtest_tab()),
                    dcc.Tab(label="Maintenance", children=_maintenance_tab()),
                ]
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
        State("chart-timeframe", "value"),
        State("chart-toggles", "value"),
    )
    def _update_chart(_clicks: int, timeframe: str, toggles: list[str]):  # type: ignore[no-untyped-def]
        cache = load_cache(Timeframe(timeframe))
        return build_chart(
            cache.to_frame(),
            show_bb="bb" in (toggles or []),
            show_rsi="rsi" in (toggles or []),
        )

    @app.callback(
        Output("bt-graph", "figure"),
        Output("bt-metrics", "children"),
        Input("bt-run", "n_clicks"),
        State("bt-timeframe", "value"),
        State("bt-strategy", "value"),
    )
    def _run_backtest(_clicks: int, timeframe: str, strategy: str):  # type: ignore[no-untyped-def]
        tf = Timeframe(timeframe)
        cache = load_cache(tf)
        df = cache.to_frame()
        if df.empty or not strategy:
            return build_chart(df), "No data. Run OHLCV download first."
        sim = Simulator(get_strategy(strategy)).run(cache.bars)
        result = run_cycle(strategy, tf)
        fig = build_chart(df, trades=sim.trades)
        return fig, _format_metrics(result)

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
        f"# trades       {m_in.n_trades:>10d} {m_oos.n_trades:>10d}",
        "",
        "OVERFIT if OOS Sharpe < 0 or OOS DD > 2x IS DD.",
    ]
    return "\n".join(lines)


def main() -> None:
    """Launch the development server."""
    configure_logging(get_settings().log_level)
    app = create_app()
    app.run(host="0.0.0.0", port=8050, debug=False)


if __name__ == "__main__":
    main()
