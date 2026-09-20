# Vendored fonts

Latin-subset `woff2` files for the two families `app.css` loads via
`@font-face`: **Source Serif 4** (weights 400, 500, 600, 700, plus 400
italic) and **IBM Plex Mono** (weights 500, 600). Fetched from
`fonts.googleapis.com`/`fonts.gstatic.com` and committed here rather than
linked live, so no visitor's browser ever makes a request to Google merely to
render a page (§14's self-hosting posture — a live Google Fonts `<link>`
would leak every visitor's IP to a third party on every page load, the same
category of problem the spec rules out for images and embeds). Only the
`latin` unicode range is kept: French needs nothing from `latin-ext`,
`cyrillic`, `vietnamese` or the others Google also serves per weight, and
dropping them is most of the size difference between these seven files
(~105 KiB total) and the full family exports.

Both families are licensed under the [SIL Open Font License 1.1](https://openfontlicense.org/),
which permits exactly this: bundling, self-hosting and redistribution
alongside software under a different licence, including the project's 0BSD.

To refresh a weight (a new variant is added to `app.css`, or Google revises a
glyph): fetch `https://fonts.googleapis.com/css2?family=<Family>:wght@<weight>`
with a browser `User-Agent` header (a plain `curl` without one gets old
`.ttf`/`.eot` links), take the `@font-face` block whose `unicode-range` starts
`U+0000-00FF` (the `latin` one), and download its `src` URL here.

Source Serif 4 is Google-hosted only as a variable font, which matters for
this fetch: ask for more than one weight in the same request (`wght@400;700`,
or the `opsz,wght@8..60,400;8..60,700` form Google's own picker suggests) and
it collapses every weight into one ~120 KiB variable blob reused verbatim
across the `@font-face` blocks — technically correct (the browser interpolates
the right weight out of it) but four times heavier than shipping four static
weights, and a silent surprise if you're not comparing file sizes. Asking for
exactly one weight per request — `ital,wght@0,<weight>` for upright,
`ital,wght@1,<weight>` for italic — gets back the same static per-weight
instance Libre Franklin used to ship, ~20 KiB each. One request, one weight,
every time.
