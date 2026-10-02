/* SPDX-License-Identifier: 0BSD */

/*
  Select a read-only field's whole value when it is clicked, so a share link
  copies in one gesture (backoffice/poll_preview.html, poll_sandbox.html).
  Markup contract: `[data-select-all]` on an <input>. Replaces an inline
  `onclick`, which the Content-Security-Policy refuses (apps/core/headers.py).
*/
(function () {
  "use strict";

  document.addEventListener("click", function (event) {
    var field = event.target.closest && event.target.closest("input[data-select-all]");
    if (field) field.select();
  });
})();
