<!-- SPDX-License-Identifier: 0BSD -->

# Review guide

How to review this codebase efficiently. Read `docs/architecture.md` first
for the map; this page says where to spend attention. Findings from the
documentation pass are in `docs/review-notes.md`.

## Where to start reading

Read in this order. Each item is short, and the later ones assume the
earlier.

1. **`CLAUDE.md`, "Properties that must not be broken".** The non-negotiable
   properties in half a page.
2. **`spec-plateforme-vote.md` §5 (invariants INV-1 to INV-11) and §7 (the
   token scheme).** Everything else serves these.
3. **`src/apps/core/crypto.py`, `types.py`, `canonical.py`.** The token
   scheme, the distinct hash types, and the bytes the closure hash covers.
   Together with `docs/canonical-serialisation.md`.
4. **`src/apps/elections/models.py` → `transitions.py` → `windows.py`.** The
   poll, its state machine, and the clock-based window that actually gates
   writes.
5. **`src/apps/registrations/models.py` and `services.py`.** Matching,
   routing and token issue.
6. **`src/apps/ballots/models.py` and `services.py`.** Cast, modify, and the
   paper path.
7. **`src/apps/elections/closure.py`, `src/apps/tally/`.** What is frozen,
   hashed, tallied and published.
8. **`src/apps/elections/migrations/0002_invariant_triggers.py`** and the
   later migrations that redefine triggers (0005–0014). The database-level
   enforcement.
9. **`src/apps/backoffice/access.py`**, then any screen in `views.py` via the
   screen map in `architecture.md`.
10. **`verifier/core/src/`.** About 700 lines; compare against step 3.

Module docstrings are written to be read on their own. Most start by saying
which section of the specification they implement.

## Critical paths

| Path | Entry point | Why it is critical |
|---|---|---|
| Online vote | `ballots/views.py: access` → `registrations.services.arrive` → `ballots.services.cast_online` | Anonymity (INV-1), one vote per elector (INV-5), token never persisted. |
| Modification | `ballots/views.py: modify` → `ballots.services.modify` | Runs from a session holding only `ballot_hash`; must never see the token or a registration. |
| Paper entry | `backoffice/views.py: paper_entry` → `ballots.services.enter_paper` | The one screen showing a voter beside ballot content; refuses an elector who voted online (R-9.3). |
| Closure | `transitions.close_poll` → `closure.compute_closure` | The hash and counts that everything published depends on. |
| Publication | `transitions.publish_poll`; `closure.published_csv`, `closure.publication` | Must equal the live set exactly, or the verifier disagrees. |
| Retention | `elections/retention.py` | The only deletion of identity data; must not touch ballots or the audit log. |
| Access control | `backoffice/access.py` | A missing gate is silent; see the test below. |

## Security- and privacy-sensitive areas

* **The voter–ballot boundary (INV-1).** `Ballot` has no reference to a
  voter; `registrations` never imports `ballots`; `ballots` calls
  `registrations.services` with ids and strings only. Watch for any new
  query, view, template context, log line or audit event that holds a
  registration and a ballot at the same time. Online casts deliberately write
  **no** audit event (timing side channel; `ballots/services.py` header).
* **The token.** `core/types.Token` hides its value in `repr`, `str` and
  format strings. Only `voter_hash`/`ballot_hash` are stored. Ballot-route
  responses carry `Referrer-Policy: no-referrer` and `Cache-Control: no-store`
  (`core/tokensession.protect`). nginx does not log `/<lang>/bulletin/` and
  `core/logging.py` redacts it from Django's logs. Any new route under that
  prefix inherits these obligations.
* **The session.** It may hold a `ballot_hash` or a receipt, but never a
  registration id next to either (`core/tokensession.py` header).
* **The audit log (INV-3).** Append-only by trigger. Events hold references
  and non-identifying state only. `audit/services.py` rejects known personal
  keys at any depth; `reason` is a code, and prose lives on the referenced row.
* **Back-office access.** `commune_admin` grants nothing on a poll;
  `is_superuser` is never consulted.
* **Uploads.** Images are identified from their bytes, never by extension
  (`core/images.py`); SVG is refused; stored files are content-addressed.
  Poll descriptions are Markdown sanitised with `nh3` at display time
  (`elections/richtext.py`).
* **Stored secrets.** The SMTP password uses Fernet, with a key derived from
  `SECRET_KEY` (`core/secretstore.py`). `token_salt` is in the database and
  the backups, so backup permissions are part of ballot secrecy.
* **Rate limiting.** `core/ratelimit.py` stores no IP address, only a salted
  digest. See review note M3 on which header it trusts.

## Invariants and where they are enforced

| Invariant | Application | Database | Test |
|---|---|---|---|
| INV-1 no voter–ballot join | module boundaries, `Ballot` fields | no FK | `test_inv1_separation.py` |
| INV-2 voting window | `elections/windows.py` | `inv2_*` triggers | `test_triggers.py`, `test_windows.py` |
| INV-3 append-only log and ballot history | `audit/services.py`, ballot services | `inv3_*` triggers | `test_triggers.py`, `test_audit_services.py` |
| INV-4 one registration per roll entry | `registrations.services` | partial unique constraint | `test_registration_flow.py`, `test_one_vote_per_elector.py` |
| INV-5 one live ballot per elector | `Registration.channel` | — | `test_one_vote_per_elector.py` |
| INV-6 frozen configuration | `Poll.save()` | `inv6_*` triggers | `test_triggers.py`, `test_backoffice_config.py` |
| INV-7 frozen snapshot | — | `inv7_*` triggers | `test_triggers.py` |
| INV-8 sandbox never public | `publicsite._public_polls`, `sandbox.may_reach` | — | `test_sandbox.py`, `test_publicsite.py` |
| INV-9 tally reads no registration | `tally/` imports no Django | — | `test_inv1_separation.py` |
| INV-10 one address per poll | `registrations.services` | partial unique constraint | `test_registration_flow.py` |
| INV-11 unique tracking code | `ballots.services._insert` | unique constraint | `test_ballot_services.py` |
| Single state writer | `elections/transitions.py` | `poll_state_irreversible` trigger | `test_single_transition_point.py` |
| Every poll screen gated | `backoffice/access.py` | — | `test_backoffice_access.py` |
| Python and Rust agree | `core/canonical.py` ↔ `verifier/core` | — | `test_verifier_agreement.py`, `cargo test` |

The triggers are the real enforcement; application checks exist to produce a
clear error message. A change that only touches one side is incomplete.

## Known fragile spots

* **Trigger ↔ model drift.** The `Registration` UPDATE trigger lists every
  column that must stay unchanged during the paper carve-out. A new model field
  missing from that list becomes writable after closure
  (`0002_invariant_triggers.py`, comment above `REGISTRATION_WINDOW`).
* **The clock refuses, the state admits** (decision log #33). A write needs
  `state = open` *and* the clock inside the window. Never let `state` alone
  refuse a write past a deadline: the scheduled transitions can lag, so
  `closes_at` and `paper_entry_deadline` are the clock's alone. For the same
  reason the public page (`_status_key`) and the dashboard read the clock at
  the closing end. Code that treats `poll.state == OPEN` as enough to accept a
  vote is wrong.
* **Row locks rely on SQLite `IMMEDIATE`.** `select_for_update()` does
  nothing on SQLite; the write lock taken at `BEGIN` is what serialises, e.g.,
  two concurrent modifications (T-35). One vote per elector does not depend
  on it: `registrations.services.mark_voted` is a compare-and-set, and a
  cast or paper entry that loses it refuses (review note M4).
* **Audit events inside a transaction that raises are lost.** Refusals are
  logged after the rollback (`transitions._run_transition`,
  `registrations.services.register`).
* **Mail goes out via `transaction.on_commit`.** Tests need
  `django_capture_on_commit_callbacks(execute=True)`.
* **Tests that read source code.** `test_audit_vocabulary.py` counts every
  `Action.<NAME>` in `src/`, docstrings included, so writing `Action.X` in a
  comment can hide an unused action. `test_single_transition_point.py` and
  `test_inv1_separation.py` parse the AST, so comments do not affect them.
* **The rest of CLAUDE.md "Gotchas".** UUIDs stored without dashes on SQLite,
  single-line `{# #}` template comments, the paginator row-count trap, and
  configuration frozen outside `draft` in tests.

## Running the checks

```sh
uv sync
uv run pytest -q                                          # ~850 tests, ~20 s, no network
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests                                     # --strict
uv run python manage.py makemigrations --check --dry-run
cargo test --manifest-path verifier/Cargo.toml
uv run python manage.py compilemessages                   # needs GNU gettext
```

All must pass before a commit lands. `tests/integration/test_end_to_end.py`
and `test_voting_journeys.py` are the best starting points for seeing whole
flows exercised.
