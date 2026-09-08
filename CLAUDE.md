# CLAUDE.md

Consultative polling platform for one French commune. `spec-plateforme-vote.md`
is the specification and is authoritative; `§n` in code comments and commit
messages refers to its sections, `R-x.y` to the functional requirements it
restates, `INV-n` and `T-n` to its invariants (§5) and acceptance tests (§12).

## Commands

```sh
uv sync                                   # Python 3.13, Django 5.2 LTS
uv run python manage.py migrate           # settings default to config.settings.dev
uv run pytest -q                          # 51 tests, fast; no network
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests                     # --strict, must stay clean
cargo test --manifest-path verifier/Cargo.toml
uv run python manage.py compilemessages   # needs GNU gettext installed
```

All four gates run in CI and must be green before a commit lands.

## Layout

`src/config/` project settings and URLs · `src/apps/core/` types, crypto,
canonical serialisation, name matching, tracking codes, job locking ·
`src/apps/elections/` poll, options, snapshot, transitions, voting window,
closure, retention · `src/apps/registrations/` (§6.2: `services`, `mail`, `forms`, `views`) ·
`src/apps/ballots/` ·
`src/apps/audit/` · `src/apps/tally/` pure, imports no model ·
`src/apps/backoffice/` espace mairie (§6.5, the bulk of the remaining work;
`access.py` is the role gate every screen goes through, `dashboard.py` and
`auditlog.py` the read models for screens 1 and 8) · `src/apps/publicsite/`
· `src/templates/` · `src/static/` · `locale/` (French is the msgid language, so
only `en` has a catalogue) · `verifier/` independent Rust verifier · `ansible/`
· `contrib/init/`.

## Properties that must not be broken

These encode privacy or integrity guarantees that cannot be retrofitted. If a
task seems to require breaking one, that is a signal to stop and say so, not to
find a way round it.

- **INV-1 / INV-5.** No column, view, index or query joins `Registration` to an
  online `Ballot`. "Has this person voted" is answered by
  `Registration.channel`, never by counting ballots. `Ballot` carries no voter,
  registration or NNE reference, and the two apps' modules do not import each
  other. `tests/integration/test_inv1_separation.py` asserts all of this.
- **INV-3.** `AuditEvent` has no update or delete path, in the application or
  the database. Events store a reference plus non-identifying state — never a
  name, NNE or email; `reason` is a code from `audit.models.Reason`, never
  prose. Operator prose belongs on the referenced row, where the retention
  purge takes it (§10).
- **The closure hash** covers exactly the `status = live` ballots, serialised
  with option ids and tracking codes only. `docs/canonical-serialisation.md` is
  the contract between Python, the published CSV and the Rust verifier; change
  one and you change all three, deliberately.
- **The tie-break** is the hash chain of §8.3. No language PRNG, no
  `random.shuffle`, no seeded sort.
- **`Poll.state` is assigned in exactly one module**,
  `apps/elections/transitions.py`, and a test enforces it. Ballot writes go
  through `apps/elections/windows.py`, which never consults `state` — the
  scheduled job may run late, twice, or not at all.
- **The plaintext token is never persisted.** Only `voter_hash` is stored
  (§7). It follows that the token-for-session exchange of §6.3
  (`apps/core/tokensession.py`) puts a *registration id* in the session, never
  the token: Django's session backend is a database table.
- **No Django admin**, in any environment.
- **Every poll-scoped back-office screen goes through `require_poll_role`**
  (`apps/backoffice/access.py`). `commune_admin` is commune-level and grants
  nothing on an individual poll, and `is_superuser` is never consulted: reaching
  the screens that show a voter beside a ballot must follow an audited grant, not
  a flag. `tests/integration/test_backoffice_access.py` asserts both, and fails
  on any view taking a `poll` that is not wrapped.

Database triggers (`elections/migrations/0002_invariant_triggers.py`) are the
real enforcement for INV-2, INV-3, INV-6 and INV-7. Application checks produce
the good error message; the triggers are what hold.

## Conventions

- Interface, labels and operator-facing text in French; identifiers, code and
  comments in English.
- Comments explain *why*, citing the section that decided it. Do not restate
  what the code says.
- Do not name the source requirements document; cite `R-x.y` as "the functional
  requirements".
- Copyright is **Romain VINCENT**'s. Licence 0BSD, `SPDX-License-Identifier:
  0BSD` in every source file.
- Where the code departs from the specification, record it in
  `docs/spec-divergences.md` rather than leaving it to be discovered.

## Pushing back

The specification is careful and mostly right, so treat it as the default. But
it is not infallible, and neither is a request in the chat. When you find a real
contradiction, an instruction that would break one of the properties above, or a
plan that will not survive contact with the data, say so plainly in a sentence
or two, propose the fix, and carry on with the rest of the work. §11 versus
T-58 is a worked example: the retention anchor and the delete triggers cannot
both be as written, and the resolution is recorded rather than papered over.

Push back when there is something to push back about. Do not manufacture
objections, hedge finished work, or open a debate about a decision already
taken — that costs more than it saves.

## Gotchas found the hard way

- Django stores `UUIDField` on SQLite as 32 hex characters **without dashes**;
  raw SQL in a test must use `obj.pk.hex` or it silently matches no row and the
  trigger never fires.
- An audit event written inside a transaction that then raises is rolled back
  with it. Refusals are logged *after* the rollback — see `open_poll`, and
  `registrations.services.register`, where the duplicate-NNE flag of R-5.9 is
  written outside the transaction the refusal aborts.
- Mail is sent from `transaction.on_commit`, so a rolled-back registration
  cannot produce a delivered message. Tests must wrap the call in
  pytest-django's `django_capture_on_commit_callbacks(execute=True)` or the
  outbox stays empty.
- Configuration is frozen once a poll leaves `draft` (INV-6) and the **trigger**
  enforces it, so a test that needs `allow_ballot_modification`, `opens_at` or
  `is_sandbox` to differ must build a second poll rather than update one.
  `closes_at` and `paper_entry_deadline` are the two that still move (R-3.4).
- `ruff` ignores RUF001–003 here: French text is full of typographic
  apostrophes and accents that would otherwise be flagged on every line.
- A Django `{# … #}` comment is **single-line only**. Spanning one over two
  lines does not comment it out — it renders verbatim into the page, with no
  error anywhere. Multi-line commentary uses `{% comment %}`, and
  `tests/unit/test_templates.py` fails the build on the mistake.
- `Paginator` caps its slice at the count it took a moment earlier, and
  `page.object_list` is lazy. A row inserted between the two — the audit
  screen's own access event, say — silently pushes the oldest row off the page.
  Materialise the page before writing anything.
- Under `mypy --strict`, `voter_hash(...) != ballot_hash(...)` is a
  non-overlapping comparison. That is the point (§5.1); convert with `bytes()`
  in a test that deliberately compares them.
