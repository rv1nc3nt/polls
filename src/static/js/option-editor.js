/* SPDX-License-Identifier: 0BSD */

/*
  Configuration editor — add and remove a proposition (§6.5.2, R-3.1).

  Progressive enhancement over the Django formset in poll_config.html. Without
  this file the editor still works: it renders `extra` blank rows to fill in,
  and each row's DELETE checkbox drops that row on save. This script layers an
  « Ajouter une proposition » button and a per-row « Retirer » button on top,
  and keeps the formset management form (TOTAL_FORMS) and the row indices in
  step so the POST still parses.

  A row that is already stored — its hidden `pk` is set — is never torn out of
  the DOM: removing it ticks its DELETE box, which the server honours on save
  and which stays undoable until then. A row with no `pk` (a blank `extra` row,
  or one this script added) is removed outright and the rows after it are
  renumbered.

  R-3.1's floor of two propositions is the server's to enforce — the formset
  raises. Here it only disables the « Retirer » buttons once two live rows are
  left, so the ordinary case never reaches that error.
*/
(function () {
  "use strict";

  // The `opt-<index>-` segment of a formset field name / id, `__prefix__` in
  // the <template> pattern.
  var INDEX_RE = /(opt-)(\d+|__prefix__)(-)/;
  var PLACEHOLDER = /__prefix__/g;

  document.addEventListener("DOMContentLoaded", function () {
    var editor = document.querySelector("[data-option-editor]");
    if (!editor) {
      return;
    }

    var rowsBox = editor.querySelector("[data-option-rows]");
    var template = editor.querySelector("[data-option-template]");
    var addWrap = editor.querySelector("[data-option-add]");
    var addButton = editor.querySelector("[data-option-add-button]");
    var totalField = document.getElementById("id_opt-TOTAL_FORMS");
    if (!rowsBox || !template || !addWrap || !addButton || !totalField) {
      return;
    }

    function rows() {
      return Array.prototype.slice.call(rowsBox.querySelectorAll("[data-option-row]"));
    }

    function isStored(row) {
      var pk = row.querySelector('[name$="-pk"]');
      return !!(pk && pk.value);
    }

    function isRemoved(row) {
      return row.classList.contains("option-row--removed");
    }

    // Rewrite one row's field indices to `index`: input/select/textarea `name`
    // and `id`, label `for`, `aria-describedby`, and the visible legend number.
    function renumber(row, index) {
      var nodes = row.querySelectorAll("input, select, textarea, label");
      Array.prototype.forEach.call(nodes, function (node) {
        ["name", "id", "for", "aria-describedby"].forEach(function (attr) {
          var value = node.getAttribute(attr);
          if (value) {
            node.setAttribute(attr, value.replace(INDEX_RE, "$1" + index + "$3"));
          }
        });
      });
      var number = row.querySelector("[data-option-number]");
      if (number) {
        number.textContent = String(index + 1);
      }
    }

    // Re-index every row from its DOM position and bring the management form
    // and the « Retirer » buttons back in line.
    function sync() {
      var all = rows();
      all.forEach(renumber);
      totalField.value = String(all.length);

      var live = all.filter(function (row) {
        return !isRemoved(row);
      }).length;
      all.forEach(function (row) {
        var button = row.querySelector("[data-option-remove]");
        if (button) {
          button.disabled = !isRemoved(row) && live <= 2;
        }
      });
    }

    // Reveal the per-row button; fold the raw DELETE checkbox away — it is now
    // driven by that button but must stay in the DOM to POST.
    function wireRow(row) {
      var removeWrap = row.querySelector("[data-option-remove-wrap]");
      var deleteRow = row.querySelector("[data-option-delete]");
      if (removeWrap) {
        removeWrap.hidden = false;
      }
      if (deleteRow) {
        deleteRow.hidden = true;
      }
    }

    rowsBox.addEventListener("click", function (event) {
      var button = event.target.closest("[data-option-remove]");
      if (!button) {
        return;
      }
      var row = button.closest("[data-option-row]");
      if (!row) {
        return;
      }

      if (isStored(row)) {
        var removed = !isRemoved(row);
        var box = row.querySelector('[name$="-DELETE"]');
        row.classList.toggle("option-row--removed", removed);
        if (box) {
          box.checked = removed;
        }
        button.textContent = button.getAttribute(
          removed ? "data-label-undo" : "data-label-remove"
        );
      } else {
        row.parentNode.removeChild(row);
        // The row that had focus is gone; land somewhere sensible.
        addButton.focus();
      }
      sync();
    });

    addButton.addEventListener("click", function () {
      var holder = document.createElement("div");
      holder.innerHTML = template.innerHTML.replace(PLACEHOLDER, String(rows().length));
      var row = holder.querySelector("[data-option-row]");
      if (!row) {
        return;
      }
      rowsBox.appendChild(row);
      wireRow(row);
      sync();
      var first = row.querySelector("input, select, textarea");
      if (first) {
        first.focus();
      }
    });

    rows().forEach(wireRow);
    addWrap.hidden = false;
    sync();
  });
})();
