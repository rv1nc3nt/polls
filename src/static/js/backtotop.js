/* SPDX-License-Identifier: 0BSD */

/*
  Back-to-top shortcut (poll_detail.html), progressive enhancement over the
  plain fixed link in the template. Without this file the link sits on screen
  throughout — harmless, and still the shortcut a keyboard or screen-reader
  visitor needs once the page runs long (tabs, calendar, participation, legal
  sections one after another). With it, the link hides until the visitor has
  scrolled past the first screen, so it doesn't sit over the title while the
  title is already visible (same "add, don't require" reasoning as
  static/js/theme.js's control and static/js/tabs.js's tablist).
*/
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    var link = document.querySelector("[data-backtotop]");
    if (!link) {
      return;
    }

    function sync() {
      link.classList.toggle("is-hidden", window.scrollY < window.innerHeight);
    }

    window.addEventListener("scroll", sync, { passive: true });
    sync();
  });
})();
