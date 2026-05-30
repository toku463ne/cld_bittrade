"""Plotly figure builders shared by the Chart and Backtest tabs.

Builds the three-panel layout described in CLAUDE.md:

1. Price panel  — candlestick + EMA(9)/EMA(21) + optional Bollinger Bands.
2. ATR panel    — ATR(14) + 20-bar average + shaded volatility-filter region.
3. RSI panel    — RSI(14) + 30/70 reference lines (optional).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.core.types import Trade
from src.indicators import atr, atr_average, bollinger_bands, ema, rsi


def build_chart(
    df: pd.DataFrame,
    *,
    show_bb: bool = True,
    show_rsi: bool = True,
    trades: list[Trade] | None = None,
) -> go.Figure:
    """Build the shared three-panel chart figure.

    Args:
        df: Time-indexed OHLCV DataFrame.
        show_bb: Overlay Bollinger Bands on the price panel.
        show_rsi: Include the RSI panel.
        trades: Optional trades to mark on the price panel (Backtest tab).

    Returns:
        A Plotly :class:`~plotly.graph_objects.Figure`.
    """
    rows = 3 if show_rsi else 2
    row_heights = [0.6, 0.2, 0.2] if show_rsi else [0.7, 0.3]
    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=row_heights,
        subplot_titles=(["Price", "ATR"] + (["RSI"] if show_rsi else [])),
    )

    if df.empty:
        fig.add_annotation(text="No data — run src.data.collect", showarrow=False)
        return fig

    close = df["close"]

    # --- Price panel ---
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="FX_BTC_JPY",
        ),
        row=1,
        col=1,
    )
    for period, color in ((9, "#1f77b4"), (21, "#ff7f0e")):
        e = ema(close, period).replace(0.0, pd.NA)
        fig.add_trace(
            go.Scatter(x=df.index, y=e, name=f"EMA({period})", line=dict(color=color, width=1)),
            row=1,
            col=1,
        )
    if show_bb:
        bb = bollinger_bands(close).replace(0.0, pd.NA)
        fig.add_trace(
            go.Scatter(x=df.index, y=bb["bb_upper"], name="BB upper",
                       line=dict(color="rgba(150,150,150,0.4)", width=1)),
            row=1, col=1,
        )
        fig.add_trace(
            go.Scatter(x=df.index, y=bb["bb_lower"], name="BB lower", fill="tonexty",
                       fillcolor="rgba(150,150,150,0.12)",
                       line=dict(color="rgba(150,150,150,0.4)", width=1)),
            row=1, col=1,
        )

    if trades:
        _add_trade_markers(fig, trades)

    # --- ATR panel ---
    atr_s = atr(df).replace(0.0, pd.NA)
    atr_avg = atr_average(atr(df)).replace(0.0, pd.NA)
    fig.add_trace(go.Scatter(x=df.index, y=atr_s, name="ATR(14)", line=dict(color="#2ca02c")), row=2, col=1)
    fig.add_trace(
        go.Scatter(x=df.index, y=atr_avg, name="ATR 20-avg", line=dict(color="#d62728", dash="dash")),
        row=2, col=1,
    )

    # --- RSI panel ---
    if show_rsi:
        r = rsi(close).replace(0.0, pd.NA)
        fig.add_trace(go.Scatter(x=df.index, y=r, name="RSI(14)", line=dict(color="#9467bd")), row=3, col=1)
        fig.add_hline(y=70, line=dict(color="grey", dash="dot"), row=3, col=1)
        fig.add_hline(y=30, line=dict(color="grey", dash="dot"), row=3, col=1)

    fig.update_layout(
        height=820,
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.04),
        margin=dict(l=40, r=20, t=40, b=30),
        template="plotly_white",
    )
    return fig


def _add_trade_markers(fig: go.Figure, trades: list[Trade]) -> None:
    """Add entry/exit markers to the price panel (Backtest tab)."""
    from src.core.types import ExitReason, Side

    for t in trades:
        entry_color = "green" if t.side is Side.LONG else "red"
        symbol = "triangle-up" if t.side is Side.LONG else "triangle-down"
        fig.add_trace(
            go.Scatter(
                x=[t.entry_time], y=[t.entry_price], mode="markers",
                marker=dict(symbol=symbol, color=entry_color, size=11),
                name="entry", showlegend=False,
                hovertext=f"{t.side.value} entry {t.entry_price:.0f}",
            ),
            row=1, col=1,
        )
        filled = t.exit_reason is ExitReason.TAKE_PROFIT
        fig.add_trace(
            go.Scatter(
                x=[t.exit_time], y=[t.exit_price], mode="markers",
                marker=dict(
                    symbol="circle" if filled else "circle-open",
                    color=entry_color, size=9,
                ),
                name="exit", showlegend=False,
                hovertext=(
                    f"exit {t.exit_price:.0f} | PnL {t.pnl:.1f} | "
                    f"{t.bars_held} bars | {t.exit_reason.value}"
                ),
            ),
            row=1, col=1,
        )
