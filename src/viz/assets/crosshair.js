/* Crosshair axis tags for the Plotly charts.
 *
 * Plotly spikelines draw the crosshair LINES but carry no value labels. This
 * adds TradingView-style tags that follow the cursor: the date at the top of
 * the vertical line and the price at the right of the horizontal line, for the
 * price panel (the top cartesian subplot: xaxis / yaxis).
 *
 * Pure browser asset (Dash auto-serves files under viz/assets/). No server
 * round-trip — it reads the live axis objects and positions two absolutely-
 * placed tags. If tags are mispositioned or values look wrong, the likely cause
 * is the pixel->data conversion (ax.p2d) or the _offset/_length fields differing
 * in this Plotly version — adjust there.
 */
(function () {
  "use strict";

  function pad(n) { return (n < 10 ? "0" : "") + n; }

  function fmtDate(v) {
    var d = (typeof v === "number") ? new Date(v) : new Date(Date.parse(v));
    if (isNaN(d.getTime())) return String(v);
    return (
      d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
      " " + pad(d.getHours()) + ":" + pad(d.getMinutes())
    );
  }

  function fmtPrice(v) {
    var n = Number(v);
    if (isNaN(n)) return String(v);
    // Magnitude-aware: BTC (~1e7) as integer, XRP/ETH (~1e2) keep decimals.
    var d = Math.abs(n) >= 10000 ? 0 : Math.abs(n) >= 1 ? 2 : 4;
    return n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  }

  function makeTag(extra) {
    var t = document.createElement("div");
    t.style.cssText =
      "position:absolute;pointer-events:none;z-index:1000;background:#3a3a3a;" +
      "color:#fff;font:11px monospace;padding:1px 5px;border-radius:2px;" +
      "display:none;white-space:nowrap;" + (extra || "");
    return t;
  }

  function wire(gd) {
    if (gd.__xhairWired || !gd._fullLayout) return;
    gd.__xhairWired = true;
    gd.style.position = "relative";

    var xtag = makeTag("transform:translate(-50%,0);"); // centered above cursor
    var ytag = makeTag("transform:translate(0,-50%);"); // centered right of cursor
    gd.appendChild(xtag);
    gd.appendChild(ytag);

    function hide() { xtag.style.display = "none"; ytag.style.display = "none"; }
    gd.addEventListener("mouseleave", hide);

    // The price panel's ACTUAL rendered plot rectangle (the top subplot's drag
    // layer), in viewport coords. Interpolating the axis range against this rect —
    // measured in the SAME frame as the cursor (getBoundingClientRect / clientX,Y) —
    // avoids mixing viewport pixels with Plotly's internal SVG _offset/_length,
    // which diverge on a responsive (width:100%) chart and made the price tag read
    // ~1 unit low. Topmost drag layer = price panel (it sits above ATR/RSI).
    function priceRect() {
      var ds = gd.querySelectorAll(".nsewdrag");
      var best = null, bestTop = Infinity;
      for (var i = 0; i < ds.length; i++) {
        var r = ds[i].getBoundingClientRect();
        if (r.height > 0 && r.top < bestTop) { bestTop = r.top; best = r; }
      }
      return best;
    }

    gd.addEventListener("mousemove", function (e) {
      var fl = gd._fullLayout;
      var xa = fl && fl.xaxis;
      var ya = fl && fl.yaxis; // price panel (top subplot)
      var rect = priceRect();
      if (!xa || !ya || !ya.range || !rect) { hide(); return; }

      // Only show within the price panel's plotting rectangle (viewport coords).
      if (e.clientX < rect.left || e.clientX > rect.right ||
          e.clientY < rect.top || e.clientY > rect.bottom) { hide(); return; }

      // Linear interpolation across the rendered rect: top edge = range[1] (high).
      var fracX = (e.clientX - rect.left) / rect.width;
      var fracY = (e.clientY - rect.top) / rect.height;
      var yval = ya.range[1] + fracY * (ya.range[0] - ya.range[1]);
      // x is a date axis: convert its range to linear ms, then interpolate.
      var xr0, xr1;
      try { xr0 = xa.r2l(xa.range[0]); xr1 = xa.r2l(xa.range[1]); }
      catch (err) { xr0 = xr1 = null; }
      var xval = (xr0 != null && xr1 != null) ? (xr0 + fracX * (xr1 - xr0)) : null;

      var bb = gd.getBoundingClientRect();
      var px = e.clientX - bb.left, py = e.clientY - bb.top;

      // Date tag just below the price panel (stays in view), on the vertical line.
      if (xval != null) {
        xtag.textContent = fmtDate(xval);
        xtag.style.left = px + "px";
        xtag.style.top = (rect.bottom - bb.top + 1) + "px";
        xtag.style.display = "block";
      }

      // Price tag flush against the RIGHT edge, on the horizontal line.
      ytag.textContent = fmtPrice(yval);
      ytag.style.left = "auto";
      ytag.style.right = "3px";
      ytag.style.top = py + "px";
      ytag.style.display = "block";
    });
  }

  function scan() {
    document.querySelectorAll(".js-plotly-plot").forEach(wire);
  }

  // Dash renders graphs asynchronously and re-renders on tab switches, so keep
  // scanning for not-yet-wired graphs.
  document.addEventListener("DOMContentLoaded", scan);
  setInterval(scan, 1000);
})();
