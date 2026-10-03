// SPDX-License-Identifier: 0BSD
// ESLint for src/static/js (review C-8). The scripts are served as written,
// each a plain <script src> wrapped in its own IIFE: no modules, no build step,
// no framework, so the recommended rules over browser globals are the whole of
// it. `npm run lint:js`; CI's "frontend" job runs it.
"use strict";

const js = require("@eslint/js");
const globals = require("globals");

module.exports = [
  js.configs.recommended,
  {
    files: ["src/static/js/**/*.js"],
    languageOptions: {
      ecmaVersion: 2020,
      sourceType: "script",
      globals: globals.browser,
    },
    rules: {
      // Every script opts in with its own "use strict" inside its IIFE.
      strict: ["error", "function"],
      "no-implicit-globals": "error",
      eqeqeq: ["error", "always"],
    },
  },
  {
    files: ["eslint.config.js", "stylelint.config.js"],
    languageOptions: { sourceType: "commonjs", globals: globals.node },
  },
];
