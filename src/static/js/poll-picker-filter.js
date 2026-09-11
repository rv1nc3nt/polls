/* SPDX-License-Identifier: 0BSD */

/*
  Type-to-filter over the poll picker (§6.5.10, role_admin.html).

  Progressive enhancement: without this file the picker is still usable —
  role_admin.html groups it into an <optgroup> per état (views._polls_for_
  picker) — but a commune with more than a season's worth of polls needed a
  way to jump straight to one by name, same reasoning as tabs.js and
  option-editor.js's controls staying `hidden` until something is wired to
  make them work.

  Markup contract: a `[data-poll-picker]` container holds one
  `[data-poll-filter]` search input (inside a `[data-poll-filter-wrap]` this
  script reveals) and one `[data-poll-select]` <select>, whose <option>s may
  carry `data-poll-search` with the text to match against (falling back to
  the option's own text). Matching options are left alone; the rest get
  `hidden`, which every evergreen browser also honours on a closed <select>'s
  option list. An <optgroup> left with nothing visible in it is hidden too,
  so a filter that clears out a whole état doesn't leave its label dangling
  above an empty group.
*/
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    var pickers = document.querySelectorAll("[data-poll-picker]");
    Array.prototype.forEach.call(pickers, function (picker) {
      var input = picker.querySelector("[data-poll-filter]");
      var wrap = picker.querySelector("[data-poll-filter-wrap]");
      var select = picker.querySelector("[data-poll-select]");
      if (!input || !select) {
        return;
      }
      if (wrap) {
        wrap.hidden = false;
      }

      input.addEventListener("input", function () {
        var query = input.value.trim().toLowerCase();
        Array.prototype.forEach.call(select.options, function (option) {
          if (!option.value) {
            return; // the "— choisir —" placeholder always stays.
          }
          var haystack = (option.getAttribute("data-poll-search") || option.textContent).toLowerCase();
          option.hidden = query !== "" && haystack.indexOf(query) === -1;
        });
        Array.prototype.forEach.call(select.querySelectorAll("optgroup"), function (group) {
          var visible = Array.prototype.some.call(group.querySelectorAll("option"), function (option) {
            return !option.hidden;
          });
          group.hidden = !visible;
        });
      });
    });
  });
})();
