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
    show_zigzag: bool = False,
    trades: list[Trade] | None = None,
    height: int = 820,
) -> go.Figure:
    """Build the shared three-panel chart figure.

    Args:
        df: Time-indexed OHLCV DataFrame.
        show_bb: Overlay Bollinger Bands on the price panel.
        show_rsi: Include the RSI panel.
        show_zigzag: Overlay the zigzag (connected confirmed peaks + early peaks).
        trades: Optional trades to mark on the price panel (Backtest tab).
        height: Figure height in pixels (the price panel scales with it).

    Returns:
        A Plotly :class:`~plotly.graph_objects.Figure`.
    """
    rows = 3 if show_rsi else 2
    # Give the price panel the lion's share of the (now-tall) figure.
    row_heights = [0.74, 0.13, 0.13] if show_rsi else [0.82, 0.18]
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

    if show_zigzag:
        _add_zigzag(fig, df)

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
        height=height,
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.02),
        margin=dict(l=40, r=20, t=40, b=30),
        template="plotly_white",
        hovermode="x",
    )
    # Vertical datetime crosshair spanning all panels on hover.
    fig.update_xaxes(
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
        spikedash="dot",
        spikecolor="#666",
    )
    return fig


def _add_zigzag(fig: go.Figure, df: pd.DataFrame, size: int = 10, middle_size: int = 3) -> None:
    """Overlay the zigzag as a clean alternating high/low line + early markers.

    ``detect_peaks`` can emit consecutive same-direction peaks (and mixes early
    with confirmed). Drawing those directly breaks the zigzag (an up-leg can end
    below the prior low). We collapse each run of same-direction peaks to its
    extreme (highest high / lowest low), yielding a strictly alternating line
    where every up-leg rises above the previous low and every down-leg falls
    below the previous high.
    """
    from src.indicators.zigzag import Peak, detect_peaks

    peaks = detect_peaks(df["high"].tolist(), df["low"].tolist(), size, middle_size)
    if not peaks:
        return

    line: list[Peak] = []
    for p in peaks:
        if line and line[-1].is_high == p.is_high:
            more_extreme = p.price > line[-1].price if p.is_high else p.price < line[-1].price
            if more_extreme:
                line[-1] = p  # keep the run's extreme turning point
        else:
            line.append(p)

    if len(line) >= 2:
        # Line only — no markers (filled dots clashed with the TP exit marker).
        fig.add_trace(
            go.Scatter(
                x=[df.index[p.bar_index] for p in line],
                y=[p.price for p in line],
                mode="lines",
                name=f"Zigzag({size})",
                line=dict(color="#111", width=1),
            ),
            row=1, col=1,
        )
    early = [p for p in line if not p.is_confirmed]
    if early:
        # 'x' marker — distinct from the open-circle SL/stop exit marker.
        fig.add_trace(
            go.Scatter(
                x=[df.index[p.bar_index] for p in early],
                y=[p.price for p in early],
                mode="markers",
                name="Zigzag early",
                marker=dict(symbol="x-thin", color="#888", size=7,
                            line=dict(width=1, color="#888")),
            ),
            row=1, col=1,
        )


def _pos_extreme(series: pd.Series, fn: str) -> float | None:
    """Min/max of a series ignoring the 0.0 warmup sentinel."""
    vals = series[series > 0.0]
    if vals.empty:
        return None
    return float(vals.min() if fn == "min" else vals.max())


def window_yranges(
    df: pd.DataFrame,
    x0: str,
    x1: str,
    *,
    show_bb: bool = True,
    show_rsi: bool = True,
) -> dict[str, list[float]]:
    """Compute per-panel y-axis ranges for the visible x-window.

    Used to auto-rescale the y-axes when the user zooms/pans the shared x-axis,
    so a narrow time window isn't squashed against the full-history price range.

    Args:
        df: The full time-indexed OHLCV frame currently plotted.
        x0: Visible window start (Plotly ``xaxis.range[0]``, wall-clock string).
        x1: Visible window end (Plotly ``xaxis.range[1]``).
        show_bb: Whether Bollinger Bands are shown (included in the price range).
        show_rsi: Whether the RSI panel is present.

    Returns:
        Mapping of subplot y-axis name (``yaxis`` price / ``yaxis2`` ATR /
        ``yaxis3`` RSI) to a ``[min, max]`` range. Empty if no bars are visible.
    """
    if df.empty:
        return {}
    start, end = pd.to_datetime(x0), pd.to_datetime(x1)
    idx = df.index
    if isinstance(idx, pd.DatetimeIndex) and idx.tz is not None:
        naive: pd.DatetimeIndex = idx.tz_localize(None)
    else:
        naive = pd.DatetimeIndex(idx)
    mask = (naive >= start) & (naive <= end)
    win = df[mask]
    if win.empty:
        return {}
    close = df["close"]

    # --- Price panel: candle extremes (+ Bollinger envelope if shown) ---
    lo = float(win["low"].min())
    hi = float(win["high"].max())
    if show_bb:
        bb = bollinger_bands(close)[mask]
        bl = _pos_extreme(bb["bb_lower"], "min")
        bu = _pos_extreme(bb["bb_upper"], "max")
        if bl is not None:
            lo = min(lo, bl)
        if bu is not None:
            hi = max(hi, bu)
    pad = (hi - lo) * 0.06 or hi * 0.001
    ranges: dict[str, list[float]] = {"yaxis": [lo - pad, hi + pad]}

    # --- ATR panel ---
    atr_s = atr(df)
    avg = atr_average(atr_s)
    mins = [v for v in (_pos_extreme(atr_s[mask], "min"), _pos_extreme(avg[mask], "min")) if v is not None]
    maxs = [v for v in (_pos_extreme(atr_s[mask], "max"), _pos_extreme(avg[mask], "max")) if v is not None]
    amin = min(mins) if mins else 0.0
    amax = max(maxs) if maxs else 1.0
    apad = (amax - amin) * 0.08 or amax * 0.05
    ranges["yaxis2"] = [max(0.0, amin - apad), amax + apad]

    # --- RSI panel (fixed-ish band, padded to the visible swing) ---
    if show_rsi:
        r = rsi(close)[mask]
        rmin = _pos_extreme(r, "min")
        rmax = _pos_extreme(r, "max")
        if rmin is not None and rmax is not None:
            ranges["yaxis3"] = [max(0.0, rmin - 5.0), min(100.0, rmax + 5.0)]
        else:
            ranges["yaxis3"] = [0.0, 100.0]
    return ranges


def _add_trade_markers(fig: go.Figure, trades: list[Trade]) -> None:
    """Add entry/exit markers to the price panel.

    Markers are grouped into a few legend-visible traces (long/short entries,
    TP/stop exits) rather than one trace per point, so they are easy to see and
    toggle. Each point keeps a per-trade hover tooltip.
    """
    from src.core.types import ExitReason, Side

    def _entry_group(side: Side, name: str, color: str, symbol: str) -> None:
        pts = [t for t in trades if t.side is side]
        if not pts:
            return
        fig.add_trace(
            go.Scatter(
                x=[t.entry_time for t in pts],
                y=[t.entry_price for t in pts],
                mode="markers",
                marker=dict(symbol=symbol, color=color, size=13,
                            line=dict(width=1.2, color="black")),
                name=name,
                hovertext=[f"{side.value} entry @ {t.entry_price:,.0f}" for t in pts],
                hoverinfo="text",
            ),
            row=1, col=1,
        )

    def _exit_group(name: str, symbol: str, keep: object) -> None:
        pts = [t for t in trades if (t.exit_reason is ExitReason.TAKE_PROFIT) is keep]
        if not pts:
            return
        fig.add_trace(
            go.Scatter(
                x=[t.exit_time for t in pts],
                y=[t.exit_price for t in pts],
                mode="markers",
                marker=dict(symbol=symbol, color="#222", size=9,
                            line=dict(width=1.2, color="#222")),
                name=name,
                hovertext=[
                    f"exit @ {t.exit_price:,.0f} | PnL {t.pnl:+,.1f} JPY | "
                    f"{t.bars_held} bars | {t.exit_reason.value}"
                    for t in pts
                ],
                hoverinfo="text",
            ),
            row=1, col=1,
        )

    _entry_group(Side.LONG, "Long entry ▲", "#2ca02c", "triangle-up")
    _entry_group(Side.SHORT, "Short entry ▼", "#d62728", "triangle-down")
    _exit_group("Exit — TP", "circle", True)
    _exit_group("Exit — SL/stop", "circle-open", False)
