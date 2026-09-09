/* SPDX-License-Identifier: 0BSD */

/*
  Theme selection — progressive enhancement over the CSS of app.css (§14, R-14.1).

  The stylesheet already swaps every colour token on `prefers-color-scheme` and
  on `[data-theme]`. This file only lets a visitor override the OS setting and
  remembers the choice. Three states: "light", "dark", or no stored value =
  follow the OS.

  Loaded synchronously from <head> so `data-theme` is set before first paint and
  the page never flashes the other theme. The control in the footer stays hidden
  until this runs: without JavaScript it would do nothing, and the OS setting
  already drives the page.
*/
(function () {
  "use strict";

  var KEY = "theme";
  var root = document.documentElement;

  function read() {
    try {
      return window.localStorage.getItem(KEY);
    } catch (e) {
      return null;
    }
  }

  function write(value) {
    try {
      if (value) {
        window.localStorage.setItem(KEY, value);
      } else {
        window.localStorage.removeItem(KEY);
      }
    } catch (e) {
      /* private-browsing storage denial: the choice simply will not persist */
    }
  }

  function apply(value) {
    if (value === "light" || value === "dark") {
      root.setAttribute("data-theme", value);
    } else {
      root.removeAttribute("data-theme");
    }
  }

  apply(read());

  document.addEventListener("DOMContentLoaded", function () {
    var control = document.querySelector("[data-theme-control]");
    if (!control) {
      return;
    }

    var buttons = Array.prototype.slice.call(control.querySelectorAll("button[value]"));
    if (!buttons.length) {
      return;
    }

    function sync() {
      var current = read() || "auto";
      buttons.forEach(function (button) {
        button.setAttribute("aria-pressed", button.value === current ? "true" : "false");
      });
    }

    control.addEventListener("click", function (event) {
      var button = event.target.closest("button[value]");
      if (!button) {
        return;
      }
      var choice = button.value === "auto" ? null : button.value;
      write(choice);
      apply(choice);
      sync();
    });

    sync();
    control.hidden = false;
  });
})();
