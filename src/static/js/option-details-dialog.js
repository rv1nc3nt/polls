/* SPDX-License-Identifier: 0BSD */

/*
  "Lire la suite" popup for a proposition's own description (R-3.12, §3.1
  bis), progressive enhancement over publicsite/poll_detail.html's
  `[data-details-preview]` divs (same reasoning as static/js/tabs.js and
  static/js/option-editor.js: a script-only affordance is fine as long as
  nothing already on the page depends on it).

  Without this file every `.option-details` renders in full, exactly as
  before this feature existed — R-14.1 parity for a visitor or a crawler with
  JavaScript off, and for a browser old enough to lack `<dialog>.showModal`,
  checked below before anything is touched. With it, a description longer
  than `data-details-preview-length` plain-text characters is visually
  clipped and a button opens the same content — cloned, not moved, so the
  original stays exactly as a no-JS visitor would have seen it — in a native
  `<dialog>` titled with the option's own label (`data-details-title`).
*/
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    var probe = document.createElement("dialog");
    if (typeof probe.showModal !== "function" || typeof probe.close !== "function") {
      return;
    }

    var containers = document.querySelectorAll("[data-details-preview]");
    Array.prototype.forEach.call(containers, function (container) {
      var length = parseInt(container.getAttribute("data-details-preview-length") || "", 10);
      if (!length || (container.textContent || "").length <= length) {
        return;
      }

      var moreLabel = container.getAttribute("data-details-more-label") || "";
      var closeLabel = container.getAttribute("data-details-close-label") || "";
      var title = container.getAttribute("data-details-title") || "";

      var dialog = document.createElement("dialog");
      dialog.className = "details-dialog";

      var header = document.createElement("div");
      header.className = "details-dialog__header";
      var heading = document.createElement("h3");
      heading.textContent = title;
      var closeButton = document.createElement("button");
      closeButton.type = "button";
      closeButton.className = "details-dialog__close";
      closeButton.setAttribute("aria-label", closeLabel);
      closeButton.textContent = "×";
      closeButton.addEventListener("click", function () {
        dialog.close();
      });
      header.appendChild(heading);
      header.appendChild(closeButton);

      var body = document.createElement("div");
      body.className = "details-dialog__body option-details";
      body.innerHTML = container.innerHTML;

      dialog.appendChild(header);
      dialog.appendChild(body);
      // A click landing on the dialog element itself, not something inside
      // it, is a click on the `::backdrop` — the dialog fills no more space
      // than its content, so that is the only way one reaches it.
      dialog.addEventListener("click", function (event) {
        if (event.target === dialog) {
          dialog.close();
        }
      });
      document.body.appendChild(dialog);

      var button = document.createElement("button");
      button.type = "button";
      button.className = "option-details-more";
      button.textContent = moreLabel;
      button.addEventListener("click", function () {
        dialog.showModal();
      });

      container.classList.add("option-details--clipped");
      container.insertAdjacentElement("afterend", button);
    });
  });
})();
