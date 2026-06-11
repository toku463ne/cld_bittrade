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

    gd.addEventListener("mousemove", function (e) {
      var fl = gd._fullLayout;
      var xa = fl && fl.xaxis;
      var ya = fl && fl.yaxis; // price panel (top subplot)
      if (!xa || !ya || xa._offset == null || ya._offset == null) { hide(); return; }

      var bb = gd.getBoundingClientRect();
      var px = e.clientX - bb.left;
      var py = e.clientY - bb.top;
      var xLo = xa._offset, xHi = xa._offset + xa._length;
      var yLo = ya._offset, yHi = ya._offset + ya._length;

      // Only show within the price panel's plotting rectangle.
      if (px < xLo || px > xHi || py < yLo || py > yHi) { hide(); return; }

      var xval, yval;
      try { xval = xa.p2d(px); yval = ya.p2d(py); }
      catch (err) { hide(); return; }

      // Date tag just below the price panel (stays in view), on the vertical line.
      xtag.textContent = fmtDate(xval);
      xtag.style.left = px + "px";
      xtag.style.top = (yHi + 1) + "px";
      xtag.style.display = "block";

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
