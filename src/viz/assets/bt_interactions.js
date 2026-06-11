/* Clientside interactions for the Backtest tab.
 *
 * The backtest chart holds ~44k candles. Doing zoom-autoscale, TP/SL hover lines
 * and the OHLC readout server-side meant round-tripping the whole figure (several
 * MB) on every drag/hover — multi-second lag. These run entirely in the browser
 * against the figure data that is already there, so nothing crosses the wire.
 *
 * The server callback remains the single owner that *builds* the figure; these
 * only patch its layout (keeping figure.data by reference so Plotly.react does a
 * cheap relayout, not a full redraw).
 */
window.dash_clientside = window.dash_clientside || {};

/* Parse a Plotly datetime to a tz-agnostic epoch (ms), interpreting every value
 * as if UTC so a tz-aware data x ("...+09:00") and a tz-naive relayout x
 * ("2026-06-02 05:00:00") compare on the same basis (mirrors _naive_iso). */
function _btNaiveMs(s) {
    if (s == null) return NaN;
    s = String(s).replace("T", " ");
    s = s.replace(/(\+|-)\d{2}:?\d{2}$/, "").replace(/Z$/, "").trim();
    return Date.parse(s.replace(" ", "T") + "Z");
}

/* Decode a Plotly array that may be base64 typed-array encoded ({dtype, bdata}).
 * Plotly/Dash serialise numeric trace arrays (candlestick OHLC, line y, …) this
 * way for compactness, so figure.data[*].open is an OBJECT, not a JS array, and
 * indexing it returns undefined. Return a real indexable array. */
function _btArr(a) {
    if (a == null || Array.isArray(a)) return a;
    if (a._inputArray) return a._inputArray;        // Plotly keeps a decoded copy
    if (a.bdata !== undefined && a.dtype) {
        const bin = atob(a.bdata), n = bin.length;
        const buf = new Uint8Array(n);
        for (let i = 0; i < n; i++) buf[i] = bin.charCodeAt(i);
        const TA = { f8: Float64Array, f4: Float32Array, i4: Int32Array,
                     i2: Int16Array, i1: Int8Array, u1: Uint8Array,
                     u2: Uint16Array, u4: Uint32Array }[a.dtype] || Float64Array;
        return new TA(buf.buffer);
    }
    return a;
}

/* Magnitude-aware price formatter: BTC (~1e7) as a thousands-separated integer,
 * XRP/ETH (~1e2) keeping decimals so a 181.462 price isn't rounded to "181". */
function _btFmtNum(v) {
    v = Number(v);
    if (isNaN(v)) return String(v);
    const d = Math.abs(v) >= 10000 ? 0 : Math.abs(v) >= 1 ? 3 : 5;
    return v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
}

window.dash_clientside.bt = {
    /* Rescale each panel's y-axis to the visible x-window on zoom/pan. */
    autoscale: function (relayout, figure) {
        const no = window.dash_clientside.no_update;
        if (!relayout || !figure || !figure.data) return no;
        const keys = Object.keys(relayout);

        // Double-click reset (xaxis*.autorange) -> re-enable y autorange.
        if (keys.some((k) => k.indexOf("xaxis") === 0 && k.endsWith(".autorange"))) {
            const layout = Object.assign({}, figure.layout);
            ["yaxis", "yaxis2", "yaxis3"].forEach((ax) => {
                if (layout[ax]) {
                    const a = Object.assign({}, layout[ax]);
                    delete a.range;
                    a.autorange = true;
                    layout[ax] = a;
                }
            });
            return Object.assign({}, figure, { layout: layout });
        }

        // A genuine x zoom/pan: xaxis*.range[0/1].
        let x0 = null, x1 = null;
        for (const k of keys) {
            if (k.indexOf("xaxis") !== -1 && k.endsWith(".range[0]")) x0 = relayout[k];
            if (k.indexOf("xaxis") !== -1 && k.endsWith(".range[1]")) x1 = relayout[k];
        }
        let t0 = _btNaiveMs(x0), t1 = _btNaiveMs(x1);
        if (isNaN(t0) || isNaN(t1)) return no; // mount placeholder / not a zoom
        if (t1 < t0) { const tmp = t0; t0 = t1; t1 = tmp; }

        // Visible min/max per y-axis, scanning the traces already in the browser
        // (candles use low/high; lines/markers use y) — this naturally includes
        // EMA/BB/ATR/RSI because they are their own traces on those axes.
        const axOf = { y: "yaxis", y2: "yaxis2", y3: "yaxis3" };
        const acc = {};
        for (const tr of figure.data) {
            const ax = axOf[tr.yaxis || "y"];
            if (!ax || !tr.x) continue;
            const isCandle = tr.type === "candlestick";
            const loArr = _btArr(isCandle ? tr.low : tr.y);
            const hiArr = _btArr(isCandle ? tr.high : tr.y);
            if (!loArr || !hiArr) continue;
            let lo = acc[ax] ? acc[ax][0] : Infinity;
            let hi = acc[ax] ? acc[ax][1] : -Infinity;
            const xs = _btArr(tr.x);
            for (let i = 0; i < xs.length; i++) {
                const tx = _btNaiveMs(xs[i]);
                if (tx < t0 || tx > t1) continue;
                const l = loArr[i], h = hiArr[i];
                if (l != null && !isNaN(l) && l < lo) lo = l;
                if (h != null && !isNaN(h) && h > hi) hi = h;
            }
            if (lo !== Infinity) acc[ax] = [lo, hi];
        }

        const layout = Object.assign({}, figure.layout);
        let changed = false;
        for (const ax in acc) {
            let lo = acc[ax][0], hi = acc[ax][1];
            if (hi < lo) continue;
            const pad = (hi - lo) * 0.06 || Math.abs(hi) * 0.001 || 1;
            let rng;
            if (ax === "yaxis3") rng = [Math.max(0, lo - 5), Math.min(100, hi + 5)];
            else if (ax === "yaxis2") rng = [Math.max(0, lo - pad), hi + pad];
            else rng = [lo - pad, hi + pad];
            const a = Object.assign({}, layout[ax] || {});
            a.range = rng;
            a.autorange = false;
            layout[ax] = a;
            changed = true;
        }
        if (!changed) return no;
        return Object.assign({}, figure, { layout: layout });
    },

    /* Draw dashed TP/SL segments (+ outstanding-peak connector) for a hovered
     * entry marker. Entry markers carry customdata
     * [tp, sl, entry_x, exit_x, exit_price, ref_x?, ref_price?]. */
    tpsl: function (hoverData, figure) {
        const no = window.dash_clientside.no_update;
        if (!hoverData || !figure) return no;
        const pts = hoverData.points || [];
        const cd = pts.length ? pts[0].customdata : null;
        if (!cd || cd.length < 4) return no;
        const tp = cd[0], sl = cd[1], entry_x = cd[2], exit_x = cd[3];
        const exit_price = cd.length > 4 ? cd[4] : null;
        const ref_x = cd.length > 5 ? cd[5] : null;
        const ref_price = cd.length > 6 ? cd[6] : null;

        const layout = Object.assign({}, figure.layout);
        const anns0 = layout.annotations || [];
        const prior = anns0.filter((a) => a.name === "tpsl_exit");
        if (prior.length && prior[0].x === exit_x) return no; // already drawn

        const fmt = (v) => Math.round(v).toLocaleString();
        let shapes = (layout.shapes || []).filter(
            (s) => String(s.name || "").indexOf("tpsl_") !== 0
        );
        [
            [tp, "#2ca02c", "tpsl_tp", "TP"],
            [sl, "#d62728", "tpsl_sl", "SL"],
        ].forEach((row) => {
            const level = row[0];
            if (level == null) return;
            shapes.push({
                type: "line", xref: "x", x0: entry_x, x1: exit_x,
                yref: "y", y0: level, y1: level,
                line: { color: row[1], width: 1.4, dash: "dash" }, name: row[2],
                label: { text: row[3] + " " + fmt(level), textposition: "start",
                         font: { color: row[1], size: 11 } },
            });
        });
        if (!shapes.length) return no;
        if (ref_x != null && ref_price != null) {
            shapes.push({
                type: "line", xref: "x", x0: ref_x, x1: entry_x,
                yref: "y", y0: ref_price, y1: ref_price,
                line: { color: "#8c564b", width: 1, dash: "dot" }, name: "tpsl_ref",
            });
        }
        layout.shapes = shapes;

        let anns = anns0.filter((a) => String(a.name || "").indexOf("tpsl_") !== 0);
        if (exit_price != null) {
            anns.push({
                name: "tpsl_exit", xref: "x", yref: "y", x: exit_x, y: exit_price,
                text: "exit", showarrow: true, arrowhead: 2, ax: 0, ay: -28,
                font: { size: 11, color: "#333" }, bgcolor: "#ffffffcc",
            });
        }
        if (ref_x != null && ref_price != null) {
            anns.push({
                name: "tpsl_ref", xref: "x", yref: "y", x: ref_x, y: ref_price,
                text: "outstanding peak", showarrow: true, arrowhead: 2, ax: 0, ay: -24,
                font: { size: 10, color: "#8c564b" }, bgcolor: "#ffffffcc",
            });
        }
        layout.annotations = anns;
        return Object.assign({}, figure, { layout: layout });
    },

    /* OHLC readout for the hovered bar — read straight from the candlestick
     * trace in the browser (price-panel traces share the bar index). Markers
     * carry customdata, so skip those. */
    ohlc: function (hoverData, figure) {
        const no = window.dash_clientside.no_update;
        const pts = (hoverData && hoverData.points) || [];
        if (!pts.length || !figure || !figure.data) return no;
        const p = pts[0];
        if (p.customdata) return no; // a trade marker, not a bar
        const candle = figure.data.find((t) => t.type === "candlestick");
        if (!candle || !candle.open) return no;
        // OHLC arrays may be base64 typed-arrays — decode to real arrays first.
        const xs = _btArr(candle.x);
        const op = _btArr(candle.open), hi = _btArr(candle.high),
              lo = _btArr(candle.low), cl = _btArr(candle.close);
        // Candlestick hover emits pointIndex but NOT pointNumber, so fall back:
        // pointNumber -> pointIndex -> match the hovered x against the bar axis.
        let i = p.pointNumber;
        if (i == null) i = p.pointIndex;
        if (i == null && p.x != null && xs && xs.indexOf) i = xs.indexOf(p.x);
        if (i == null || i < 0) return no;
        const o = op[i], h = hi[i], l = lo[i], c = cl[i];
        if (o == null) return no;
        const ts = String(xs[i]).replace("T", "  ").replace(/(\+|-)\d{2}:?\d{2}$/, "");
        return ts + "\nO " + _btFmtNum(o) + "   H " + _btFmtNum(h) +
               "\nL " + _btFmtNum(l) + "   C " + _btFmtNum(c);
    },
};
