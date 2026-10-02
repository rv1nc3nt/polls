<!-- SPDX-License-Identifier: 0BSD -->

# Changelog

One section per release, newest first, headed by the version exactly as
`pyproject.toml` and the tag spell it (PEP 440: `1.0.0b17`, tagged
`v1.0.0b17`). A release's section is written in the commit that bumps the
version and is tagged, not before, so the two cannot drift apart. The GitHub
release carries the same text in full, with the verifier binaries.

Each section says what changed for those who run an instance, and whether the
release can be deployed while a poll is open.

## 1.0.0b17 — 2026-10-01

- **Trend:** while a Schulze poll is open, each duel's margin carries a 95 %
  confidence interval (Wilson), with an « incertain » badge where it includes
  zero. It is not a forecast, and the screen and the manuals say so. The
  intervals disappear once the poll is closed.
- Fixed: the chart tooltip on a phone, duel-row alignment, and band contrast
  in dark mode.
- No database migration: deployable while a poll is open.

## 1.0.0b16 — 2026-10-01

- **Trend:** points fall when the number of ballots reaches each multiple of
  ten, and show once 5 more ballots are cast. They used to fall every ten
  *arrivals*, a modification included.
- Fixed: one elector modifying repeatedly could make up a whole gap between
  two points and so be singled out. Each gap now holds distinct electors.
- No database migration.

## 1.0.0b15 — 2026-10-01

- **Trend:** a point now shows once 5 more ballots have come in after it,
  instead of 10. R-11.5 bis states the lower floor.
- No database migration.

## 1.0.0b14 — 2026-10-01

Use this release instead of 1.0.0b13 for the trend screen.

- **Trend:** a point every 10 ballots cast or modified, shown once 10 more
  have come in.
- Fixed two ways 1.0.0b13 could reveal a single ballot: points recomputed from
  modified ballots, and the gap between the last point and the published
  result.
- Fixed: `polls_trend_polls` in an INI inventory was split into single
  characters and the service refused to start.
- No database migration.

## 1.0.0b13 — 2026-10-01

- **New:** the espace mairie's *Tendance* screen, under Résultats, for the
  poll administrator and the auditor. It is never published. Days are whole,
  never the current one, and grouped until each holds ten ballots (R-11.5 bis).
- **Operators:** off by default. List the polls that should have it in
  `polls_trend_polls` (`DJANGO_TREND_POLLS`), an interim setting (decision log
  #39).
- No database migration.

## 1.0.0b12 — 2026-09-24

- Every page ends with a footer naming the 0BSD licence and linking to the
  source code.
- **Operators:** set `polls_source_code_url` (`DJANGO_SOURCE_CODE_URL`) if you
  run a modified version.

## 1.0.0b11 — 2026-09-24

- **Verifier:** reads the publication document (JSON) and checks every value
  the site publishes. It recomputes plurality and approval as well as Schulze.
  The document now carries `"format_version": "1"`
  (`docs/publication-format.md`).
- Fixed, from the code review (`docs/review-notes.md`): one vote per elector
  without relying on SQLite's `IMMEDIATE` mode; the rate limiter keys on the
  address the proxy saw; a ballot's handle no longer outlives its
  modification; images are deleted only once a change commits; the audit
  log's "up to" date includes the whole day; crashed jobs exit 2; audit
  reasons are checked; the verifier no longer crashes on non-ASCII input.
- **Operators:** if TLS is terminated by another proxy in front of nginx, set
  `polls_trusted_proxy_hops: 2`.

## 1.0.0b10 — 2026-09-24

- A sandbox poll's published result is reachable through its test link, for
  rehearsing the whole process, verifier included (R-3.7, INV-8).

## 1.0.0b9 — 2026-09-24

- The poll administrator sees each elector's participation on the poll's roll
  screen: whether they voted, never how or when (R-7.5, R-13.4 bis).

## 1.0.0b8 — 2026-09-24

- Every definitive poll action goes through a confirmation page first (R-2.4).
- A poll may be closed early, by hand, with a reason shown publicly (R-3.4).
- A write needs an open poll as well as the clock inside its window, and a
  scheduled transition that has not happened is flagged (decision log #33).
- Uncountersigned paper entries are published as their own figure; a
  corrected paper ballot is countersigned again (R-8.7, R-8.7 bis).
- An elector listed twice on the roll is flagged before a second vote (R-8.3).
- Electors awaiting confirmation are listed, and their link can be resent
  (R-5.5).
- Developer documentation: architecture, review guide, review notes, glossary.

## 1.0.0b7 — 2026-09-20

- Fixed: a declared first name absent from the roll no longer matches (R-5.3).
- Fewer queries on the registration queue and the dashboard; shared upload,
  branding and refusal-logging code.

## 1.0.0b6 — 2026-09-20

- Fixed: a personal key nested in an audit payload slipped past the check
  (§10); two distinct homonyms could be merged at import (R-4.6); a physical
  tie-break could be rewritten after publication (§8.3).

## 1.0.0b5 — 2026-09-20

- The espace mairie's language and theme controls match the public site's.

## 1.0.0b4 — 2026-09-20

- Fixed: 1.0.0b3's nginx location had an unquoted regex that failed
  `nginx -t`, leaving the previous configuration running.

## 1.0.0b3 — 2026-09-20

- The manual is exempt from the write rate limit: a page full of screenshots
  could come back with images missing.

## 1.0.0b2 — 2026-09-20

- The espace mairie's help pages are capped to the reading width.

## 1.0.0b1 — 2026-09-20

First beta of the 1.0 line: the back office (§6.5) is built out.

- Releases follow PEP 440 (`bN`, `rcN`).
- Known gaps, in the decision log: direct poll duplication (#10) and the
  signed-paper-form receipt layout (#17).

## 0.3.0 — 2026-09-20

- Propositions can be reordered on screen 2 (§3.1).
- The manual is served by the site, in French and English: the voter guides
  publicly, the espace mairie guide behind sign-in.

## 0.2.4 — 2026-09-20

- Fixed: the details popup's padding, and an embedded video's width inside it.

## 0.2.3 — 2026-09-20

- Typeface changed to Source Serif 4.
- Fixed: English pages could show 12-hour times.

## 0.2.2 — 2026-09-20

- Fixed: a YouTube link alone on its line failed to embed when submitted with
  CRLF line endings, fixed for saved content too.

## 0.2.1 — 2026-09-20

- A « Lire la suite » popup for long proposition descriptions (R-3.12).

## 0.2.0 — 2026-09-19

- A poll-level image library and Markdown descriptions, with alt text and size
  suffixes (R-3.12).
- Announcing a poll is mandatory, with a shareable preview of a draft
  (R-3.10, R-3.10 bis).
- Fixed: the deploy's own health check ran before its pending handlers had
  run (§15).

## 0.1.1 — 2026-09-18

- The public poll list can be filtered by status, every public page has a
  breadcrumb, and the commune can upload a logo for the dark theme.

## 0.1.0 — 2026-09-18

First release.
