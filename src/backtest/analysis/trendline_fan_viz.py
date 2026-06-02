"""Eyeball the anchored-trendline fan on a candlestick chart (static HTML).

Companion to :mod:`trendline_fan_probe` — draws the EXACT lines that probe scores
(via :func:`trendline_fan_probe.fan_lines`) so the fan can be inspected visually
before any verdict is trusted. Renders one window of GMO_BTC_JPY 5m as an
interactive Plotly HTML (zoom/pan) written to ``/tmp/fanviz/index.html``.

Each fan line:
- solid segment  A -> B   (the two anchor peaks; A = outstanding/extreme)
- dotted segment B -> live end (the forward projection traded against)
- ``x`` marker at the first touch; hollow ``circle`` at the half-span touch
- red = short (descending high-line), green = long (ascending low-line)
- untouched lines are faint; touched lines are bold

Window via env: ``FAN_BARS`` (default 900), ``FAN_OFFSET`` bars back from the end
(default 0). Run:
  uv run --env-file .env.bt python -m src.backtest.analysis.trendline_fan_viz
then serve: ``python -m http.server 8052 -d /tmp/fanviz`` and open :8052.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import plotly.graph_objects as go

from src.core.types import Timeframe
from src.data.cache import load_cache
from src.backtest.analysis.trendline_fan_probe import Line, confirmed_peaks, fan_lines

OUT = Path("/tmp/fanviz/index.html")


def _seg(
    fig: go.Figure, x0: Any, y0: float, x1: Any, y1: float,
    color: str, dash: str, width: float,
) -> None:
    fig.add_trace(go.Scatter(
        x=[x0, x1], y=[y0, y1], mode="lines",
        line=dict(color=color, dash=dash, width=width),
        hoverinfo="skip", showlegend=False,
    ))


def main() -> None:
    bars = int(os.getenv("FAN_BARS", "900"))
    offset = int(os.getenv("FAN_OFFSET", "0"))
    df = load_cache(Timeframe.M5, product="GMO_BTC_JPY").to_frame()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    closes = df["close"].tolist()
    n = len(df)

    cpeaks = confirmed_peaks(highs, lows)
    lines = fan_lines(highs, lows, closes, cpeaks)

    idx = df.index
    if os.getenv("FAN_START"):  # pin to a date, e.g. FAN_START=2021-05-20
        import pandas as pd
        ts = pd.Timestamp(os.environ["FAN_START"], tz=getattr(idx, "tz", None))
        start = int(idx.searchsorted(ts))
        end = min(n, start + bars)
    elif os.getenv("FAN_AUTO"):
        # Center on the window with the most touched lines (densest fan).
        import bisect as _bi
        touches = sorted(ln.first_touch for ln in lines if ln.first_touch >= 0)
        best_cnt, best_start = 0, 0
        for s in range(0, max(1, n - bars), bars // 4 or 1):
            cnt = _bi.bisect_right(touches, s + bars) - _bi.bisect_left(touches, s)
            if cnt > best_cnt:
                best_cnt, best_start = cnt, s
        end = min(n, best_start + bars)
        start = best_start
    else:
        end = n - offset
        start = max(0, end - bars)

    fig = go.Figure(go.Candlestick(
        x=idx[start:end],
        open=df["open"][start:end], high=df["high"][start:end],
        low=df["low"][start:end], close=df["close"][start:end],
        name="GMO_BTC_JPY 5m", increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
    ))

    def visible(ln: Line) -> bool:
        return ln.a_idx < end and (ln.b_idx + ln.proj_hi) >= start

    shown = [ln for ln in lines if visible(ln)]
    touched = [ln for ln in shown if ln.first_touch >= 0]
    untouched = [ln for ln in shown if ln.first_touch < 0]

    for ln in untouched:
        c = "rgba(239,83,80,0.18)" if ln.is_high else "rgba(38,166,154,0.18)"
        end_t = ln.b_idx + ln.proj_hi
        _seg(fig, idx[ln.a_idx], ln.a_price, idx[ln.b_idx], ln.b_price, c, "solid", 1)
        _seg(fig, idx[ln.b_idx], ln.b_price, idx[end_t],
             ln.b_price + ln.slope * ln.proj_hi, c, "dot", 1)

    for ln in touched:
        c = "#d32f2f" if ln.is_high else "#2e7d32"
        end_t = ln.b_idx + ln.proj_hi
        _seg(fig, idx[ln.a_idx], ln.a_price, idx[ln.b_idx], ln.b_price, c, "solid", 1.8)
        _seg(fig, idx[ln.b_idx], ln.b_price, idx[end_t],
             ln.b_price + ln.slope * ln.proj_hi, c, "dot", 1.8)
        ft = ln.first_touch
        fig.add_trace(go.Scatter(
            x=[idx[ft]], y=[ln.b_price + ln.slope * (ft - ln.b_idx)],
            mode="markers", marker=dict(symbol="x", size=10, color=c),
            name="first touch", showlegend=False,
            hovertext=f"{'SHORT' if ln.is_high else 'LONG'} first-touch "
                      f"proj={ft - ln.b_idx} span={ln.b_idx - ln.a_idx}",
            hoverinfo="text",
        ))
        if ln.half_touch >= 0:
            ht = ln.half_touch
            fig.add_trace(go.Scatter(
                x=[idx[ht]], y=[ln.b_price + ln.slope * (ht - ln.b_idx)],
                mode="markers",
                marker=dict(symbol="circle-open", size=13, color=c, line=dict(width=2)),
                name="half touch", showlegend=False,
                hovertext=f"half-span touch proj={ht - ln.b_idx}", hoverinfo="text",
            ))

    fig.update_layout(
        title=f"Anchored-trendline fan — GMO 5m  bars[{start}:{end}]  "
              f"{idx[start]:%Y-%m-%d} → {idx[end-1]:%Y-%m-%d}  | "
              f"{len(shown)} lines ({len(touched)} touched), x=first ○=half-wait",
        xaxis_rangeslider_visible=False, height=760, template="plotly_white",
        margin=dict(l=40, r=20, t=60, b=30),
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(OUT), include_plotlyjs=True)
    print(f"wrote {OUT}  ({len(shown)} lines, {len(touched)} touched) "
          f"window {idx[start]} → {idx[end-1]}")


if __name__ == "__main__":
    main()
