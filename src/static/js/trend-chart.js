/* SPDX-License-Identifier: 0BSD */

/*
  Hover and keyboard readout for the trend curves (R-11.5 bis,
  backoffice/poll_trend.html). Progressive enhancement: without this file the
  chart is a static picture and every figure it carries is in the table below
  it, so nothing is reachable only through here (R-14.1).

  Markup contract: a `[data-trend-chart]` container, focusable, with
  `data-xs` — the comma-separated x position of each point in the SVG's
  viewBox units — holding one <svg>, a `[data-trend-cursor]` line inside it,
  and a `[data-trend-tip]` element whose `[data-col]` children are the
  server-rendered readouts, one per point, in the same order. This script only
  shows and hides what the server wrote; it builds no text of its own.
*/
(function () {
  "use strict";

  function wire(chart) {
    var xs = (chart.getAttribute("data-xs") || "").split(",").map(Number);
    var svg = chart.querySelector("svg");
    var cursor = chart.querySelector("[data-trend-cursor]");
    var tip = chart.querySelector("[data-trend-tip]");
    if (!xs.length || !svg || !cursor || !tip) return;
    var cols = Array.prototype.slice.call(tip.querySelectorAll("[data-col]"));
    var viewWidth = svg.viewBox.baseVal.width;
    var current = -1;

    function show(k) {
      k = Math.max(0, Math.min(xs.length - 1, k));
      current = k;
      cursor.setAttribute("x1", xs[k]);
      cursor.setAttribute("x2", xs[k]);
      cursor.setAttribute("visibility", "visible");
      cols.forEach(function (col, i) { col.hidden = i !== k; });
      tip.hidden = false;
      var scale = svg.getBoundingClientRect().width / viewWidth;
      var left = xs[k] * scale + 14;
      // scrollWidth: on a phone the drawing scrolls inside the container.
      if (left + tip.offsetWidth > chart.scrollWidth) left = xs[k] * scale - tip.offsetWidth - 14;
      tip.style.left = Math.max(0, left) + "px";
    }

    function hide() {
      current = -1;
      cursor.setAttribute("visibility", "hidden");
      tip.hidden = true;
    }

    function nearest(clientX) {
      var box = svg.getBoundingClientRect();
      var x = (clientX - box.left) * viewWidth / box.width;
      var best = 0;
      xs.forEach(function (value, i) {
        if (Math.abs(value - x) < Math.abs(xs[best] - x)) best = i;
      });
      return best;
    }

    chart.addEventListener("pointermove", function (event) { show(nearest(event.clientX)); });
    chart.addEventListener("pointerleave", function () {
      if (document.activeElement !== chart) hide();
    });
    chart.addEventListener("focus", function () { show(current < 0 ? xs.length - 1 : current); });
    chart.addEventListener("blur", hide);
    chart.addEventListener("keydown", function (event) {
      var moves = { ArrowLeft: current - 1, ArrowRight: current + 1, Home: 0, End: xs.length - 1 };
      if (Object.prototype.hasOwnProperty.call(moves, event.key)) {
        event.preventDefault();
        show(moves[event.key]);
      } else if (event.key === "Escape") {
        hide();
      }
    });
  }

  Array.prototype.forEach.call(document.querySelectorAll("[data-trend-chart]"), wire);
})();
