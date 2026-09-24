<!-- SPDX-License-Identifier: 0BSD -->

# Inventory of `docs/` (2026-09-24, at `3665500`)

Working record for the documentation reorganisation. Audience: **user** (elector,
the public), **operator** (espace mairie staff; instance administrator), **developer**,
**reviewer**. "Linked from" counts references by path, whether a Markdown link or a
path in prose or a code comment; code references are listed because the brief forbids
editing source files, which pins those paths.

## Pinned paths

Before any per-file detail: two kinds of path cannot move in this task.

- **`docs/manuel/**` is a runtime input.** `src/apps/core/manual.py:42` reads
  `BASE_DIR / "docs" / "manuel"`, the file stems are hard-coded in
  `src/apps/publicsite/views.py` (`_PUBLIC_DOCS`) and
  `src/apps/backoffice/views.py` (`_BACKOFFICE_DOCS`), the FAQ is split by its
  heading letters (`section="B"`, `"C"`), and screenshots are served from
  `captures/img/`. The Ansible deploy ships the tree in the source archive. Moving
  or renaming anything here breaks the served manual and needs a source change.
- **Paths cited in source comments.** `canonical-serialisation.md` (8 code/test/Rust
  references), `specification-decision-log.md` (~25, including migrations),
  `architecture.md` (`src/apps/backoffice/views.py:10`). Moving them leaves those
  comments pointing at nothing, and the brief forbids editing them.

## Developer and reviewer documents (top level of `docs/`)

| Path | Summary | Audience | Status | Linked from |
|---|---|---|---|---|
| `architecture.md` | Code map: components, app import graph (verified against the code — exact match), key flows with diagrams, external interfaces, back-office screen map. | reviewer, developer | current, two stale statements (issues D1, D2) | `review-guide.md`; code: `backoffice/views.py:10` |
| `canonical-serialisation.md` | Byte-exact contract for the closure hash shared by Python, the CSV and the Rust verifier; worked vector; tie-break formula. | developer, reviewer, verifier authors | current — verified against `core/canonical.py`, `tally/tiebreak.py`, both vectors reproduce | CLAUDE.md, `architecture.md`, `glossary.md`, `review-guide.md`, `manuel/verifier{,-en}.md`, `specification-decision-log.md`; code: `core/canonical.py`, `test_verifier_agreement.py`, `verifier/{core,cli}` (5) |
| `glossary.md` | Domain terms: code identifier, French interface term, meaning. Overlaps the spec's §2 word list but is much fuller. | developer, reviewer | current, one stale row (D3) | **nothing — orphan** |
| `review-guide.md` | Reading order, critical paths, privacy-sensitive areas, invariant→enforcement→test table (all 16 test files verified to exist), fragile spots, check commands. | reviewer | current, two stale figures (D4) | **nothing — orphan** |
| `review-notes.md` | Findings of the September 2026 documentation pass: M1 (resolved), M2–M4 medium, L1–L11 low, docstrings corrected, open questions. | reviewer, maintainer | dated snapshot; M2, M3, M4 re-checked and **still open** in the code | `review-guide.md` |
| `roadmap.md` | One deferred change (a separate state for the paper-keying stretch) with its full blast radius. | maintainer | current (`windows._require_open`, `online_voting_closed`, migration 0014 all exist) | **nothing — orphan** |
| `specification-decision-log.md` | 36 numbered departures from the spec with their resolution; kept after settlement on purpose. | developer, reviewer, requirements owner | current as a whole; entries out of numeric order; several superseded entries without forward pointers (D5–D8) | CLAUDE.md, README.md, README-en.md, `ansible/README.md`, `architecture.md`, `glossary.md`, `review-notes.md`, `spec-plateforme-vote.md`; ~25 code comments, migrations, tests |

## User and operator manual (`docs/manuel/`, pinned)

| Path | Summary | Audience | Status | Linked from |
|---|---|---|---|---|
| `manuel/README.md` | Manual index by role; what the application serves and where; screenshot pipeline summary. | operator, developer | current, but breaks the CLAUDE.md self-sufficiency rule (D9) | README.md, README-en.md; code: `publicsite/views.py:38`, `backoffice/views.py:2175`, `core/manual.py:14` |
| `manuel/guide-administrateur.md` | Installing, deploying, scheduling, backup/restore, monitoring, upgrading, technical GDPR duties. French only by design. | operator (IT) | current | README.md, README-en.md, `ansible/README.md`, `manuel/README.md`, CLAUDE.md; code comment `backoffice/views.py:2117`; not served |
| `manuel/guide-espace-mairie.md` / `-en.md` | Espace mairie guide: roles, poll lifecycle, roll import, registrations, paper ballots, closure, audit. | operator (mairie) | current (FR/EN heading parity 46/46) | READMEs, `manuel/README.md`; served at `/mairie/aide/` |
| `manuel/guide-electeur.md` / `-en.md` | Voter's guide: register, confirm, vote, modify, verify, paper. | user | current (12/12) | READMEs, `manuel/README.md`, `methodes-de-depouillement*`, `verifier*`; served at `/aide/` |
| `manuel/faq.md` / `-en.md` | FAQ in three parts: instance admin (A, not served), espace mairie (B), elector (C). | all | one stale answer in both languages (D10) | READMEs, `manuel/README.md`; served (B, C) |
| `manuel/methodes-de-depouillement.md` / `-en.md` | Schulze, plurality, approval and tie-break explained, then shown in the source code. | user, anyone | current (15/15) | READMEs, guides, `verifier*`; served |
| `manuel/verifier.md` / `-en.md` | Step-by-step use of the independent verifier. | user, anyone | overstates what the verifier checks (D11 — review note M2) | READMEs, guides, `methodes*`; code: `verifier/gui/src/main.rs`; served |
| `manuel/captures/README.md` | How to regenerate the screenshots; inventory of the 33 captures. | developer | current, one stale inventory row (D12) | README.md, README-en.md, `manuel/README.md` |
| `manuel/captures/*.html` (33) | Real screen markup rendered from a demo database; source of the PNGs. | developer | current | `captures/README.md` (inventory) |
| `manuel/captures/img/*.png` (33) | Screenshots shown by the manual and the READMEs. | all | current — every one referenced, no orphan | guides, READMEs; served |
| `manuel/captures/outils/demo_seed.py`, `render_captures.py` | Throwaway scripts that seed the demo database and render the captures. **Source code: out of scope.** | developer | `render_captures.py` docstring names a wrong path (C2) | `captures/README.md`, `manuel/README.md`, `pyproject.toml:43` |

## Baseline link check

Relative Markdown links and `<img src>` across all 26 tracked `.md` files: **135
checked, 0 broken**. The checker skips inline code and follows `apps.core.manual`'s
serve-time rule: an `-en` page's bare `verifier.md#…` target resolves to
`verifier-en.md#…`, which is why four EN→"FR filename" links with English anchors are
correct and not broken.
