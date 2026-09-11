/* SPDX-License-Identifier: 0BSD */

/*
  Generic ARIA tabs (§6.5.2), progressive enhancement over a stack of
  sections. Without this file `[data-tabs-panel]` elements just render in
  document order — the tablist stays `hidden`, since a button with nothing
  wired to it would do nothing but confuse a visitor (same reasoning as
  static/js/theme.js's control and static/js/option-editor.js's add button).

  Markup contract: a `[data-tabs]` container holds one `[data-tabs-list]` of
  plain `[data-tabs-tab]` buttons — same count, same order as its direct
  `[data-tabs-panel]` children, matched by position. This script adds every
  ARIA role and relationship itself, so a template author writes neither.

  On activation, the first panel containing a `.error` becomes the initial
  tab instead of the first one: a config save posts back to this same page
  (poll_config.html, poll_create.html), and a validation error must surface on
  the tab it failed on rather than hide behind whichever one opens by default
  (R-14.1). Every other tab whose panel also holds a `.error` is labelled too
  (`.tabs__tab-flag`, text from the container's `data-tabs-error-label`): a
  poll created with most of the form left blank fails several tabs at once,
  and only ever opening the first left the rest of the errors hidden with
  nothing on screen pointing at them.
*/
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    var containers = document.querySelectorAll("[data-tabs]");
    Array.prototype.forEach.call(containers, function (container) {
      var list = container.querySelector("[data-tabs-list]");
      var tabs = list ? Array.prototype.slice.call(list.querySelectorAll("[data-tabs-tab]")) : [];
      var panels = Array.prototype.slice.call(container.querySelectorAll("[data-tabs-panel]"));
      if (!list || tabs.length < 2 || tabs.length !== panels.length) {
        return;
      }

      list.setAttribute("role", "tablist");

      tabs.forEach(function (tab, index) {
        var panel = panels[index];
        var tabId = "tabs-tab-" + panel.id;
        tab.id = tabId;
        tab.setAttribute("role", "tab");
        tab.setAttribute("aria-controls", panel.id);
        panel.setAttribute("role", "tabpanel");
        panel.setAttribute("aria-labelledby", tabId);
        panel.setAttribute("tabindex", "0");
      });

      function activate(index, moveFocus) {
        tabs.forEach(function (tab, i) {
          var selected = i === index;
          tab.setAttribute("aria-selected", selected ? "true" : "false");
          tab.tabIndex = selected ? 0 : -1;
          tab.classList.toggle("is-selected", selected);
          panels[i].hidden = !selected;
        });
        if (moveFocus) {
          tabs[index].focus();
        }
      }

      // A `required` field inside a tab that is not the open one is,
      // per the HTML spec, barred from constraint validation while its
      // panel is `[hidden]`: the browser cannot focus it to report the
      // problem, so a submit that fails only on a field in a background
      // tab is silently refused — no page reload, nothing rendered, the
      // POST never leaves the browser (screen 2's opens_at/closes_at/
      // paper_entry_deadline, all required, sit on the "Calendrier" tab,
      // which is never the one that opens first). Capturing `invalid`
      // ahead of the browser's own handling and revealing that field's
      // tab first is what lets native validation actually show something.
      container.addEventListener(
        "invalid",
        function (event) {
          var panel = event.target.closest("[data-tabs-panel]");
          var index = panel ? panels.indexOf(panel) : -1;
          if (index !== -1 && panels[index].hidden) {
            activate(index, false);
          }
        },
        true
      );

      list.addEventListener("click", function (event) {
        var tab = event.target.closest("[data-tabs-tab]");
        var index = tab ? tabs.indexOf(tab) : -1;
        if (index !== -1) {
          activate(index, false);
        }
      });

      // Roving tabindex, left/right/Home/End — the standard tablist keyboard
      // pattern (RGAA 12.7 / R-14.1): only the selected tab sits in the Tab
      // order, and the arrow keys move both focus and the open panel.
      list.addEventListener("keydown", function (event) {
        var current = tabs.indexOf(document.activeElement);
        if (current === -1) {
          return;
        }
        var next = null;
        if (event.key === "ArrowRight") {
          next = (current + 1) % tabs.length;
        } else if (event.key === "ArrowLeft") {
          next = (current - 1 + tabs.length) % tabs.length;
        } else if (event.key === "Home") {
          next = 0;
        } else if (event.key === "End") {
          next = tabs.length - 1;
        } else {
          return;
        }
        event.preventDefault();
        activate(next, true);
      });

      // Translated in the template, not here (same reasoning as
      // option-editor.js's data-label-remove): interface text stays out of
      // this file so it is not a second place a translator has to find.
      var errorLabel = container.getAttribute("data-tabs-error-label") || "";

      var initial = 0;
      var foundInitial = false;
      panels.forEach(function (panel, index) {
        if (!panel.querySelector(".error")) {
          return;
        }
        if (errorLabel) {
          var note = document.createElement("span");
          note.className = "tabs__tab-flag";
          note.textContent = errorLabel;
          tabs[index].appendChild(document.createTextNode(" "));
          tabs[index].appendChild(note);
        }
        if (!foundInitial) {
          initial = index;
          foundInitial = true;
        }
      });

      activate(initial, false);
      list.hidden = false;
    });
  });
})();
