// SPDX-License-Identifier: 0BSD
// stylelint for src/static/css (review C-8). The recommended set only: it
// catches mistakes (unknown properties, invalid values, duplicates), not style.
// stylelint-config-standard would also rename every BEM class
// (`block__element--modifier`) and split the one-line rules app.css is written
// in, which is a matter of taste this file has already settled.
"use strict";

module.exports = {
  extends: "stylelint-config-recommended",
  rules: {
    // Flags a base rule written after a more specific one in another context
    // (`.langswitch label` after `.header-tools .langswitch label`). The more
    // specific rule wins whatever the order, so it reports source order, not
    // a wrong cascade; every one of its 51 reports here was of that kind.
    "no-descending-specificity": null,
  },
};
