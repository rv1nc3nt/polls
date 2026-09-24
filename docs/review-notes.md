<!-- SPDX-License-Identifier: 0BSD -->

# Review notes

Suspected bugs, fragile spots, dead code and inconsistencies found while
documenting the code (September 2026). **Nothing here has been fixed.** The
documentation pass changed only comments, docstrings and `docs/`. Each entry
gives a location, a severity and what would confirm or resolve it.

Severity: **high** means a privacy or integrity guarantee can be broken in
normal operation; **medium** means wrong behaviour reachable in practice, or a
guarantee that holds only by accident; **low** means cosmetic, dead code, or an
edge case unlikely in practice.

Where an entry is really a departure from the specification, the decision
belongs in `specification-decision-log.md`, not here.

No high-severity issue was found. M1 has since been resolved (see its entry).

## Medium

### M1. Registration is accepted on a poll that is not open — resolved

**Resolved** by decision log #33 (the clock refuses, the state admits):
the window checks and the INV-2 triggers (migration 0014) now require
`state = open`, the registration page answers 404 for a `draft` poll and
shows no form outside the window, and a missed opening is flagged on the
dashboard and by `/sante`. The analysis below is kept as found.

* **Where:** `src/apps/registrations/views.py:36` (`register`), which gates
  only on sandbox reachability; `src/apps/registrations/services.py:196`, which
  calls `check_registration_window`; `src/apps/elections/windows.py`
  (`check_registration_window`), which compares against the clock only.
* **What:** a POST to `/fr/inscription/<poll-uuid>/` for a **draft** poll whose
  `opens_at` has passed returned `302 → …/recu/pending_review/` and created a
  `Registration`. This was confirmed with a throwaway test, not committed. The
  same applies to an `announced` poll whose `open_poll` run is late or
  refused. With no snapshot yet, every applicant goes to `pending_review`.
* **Why it matters:** identity data (name, date of birth, email) is collected
  for a poll that is not open. A poll admin who approves such a registration
  mints a token for a poll that has not opened. The INV-2 delete trigger then
  refuses to delete those rows until the poll is `closed`/`published`. The
  public page does not offer the link early (`publicsite.views._status_key`
  returns `preview` for `announced`, and `_public_polls` excludes `draft`), so
  the exposure needs the poll's UUID. That UUID is unguessable but not secret.
* **Constraint on a fix:** CLAUDE.md forbids `windows.py` from consulting
  `state`, so a state gate belongs at the registration view or service entry.
  `tests/conftest.py::open_window_poll` relies on the current behaviour: it
  registers against a `draft` poll.

### M2. The verifier's winner check is Schulze-only, but the manual says otherwise

* **Where:** `verifier/core/src/report.rs` (`verify`);
  `docs/manuel/verifier.md:264-266` and `docs/manuel/verifier-en.md:247`.
* **What:** the verifier implements Schulze only, and the published CSV does
  not say which method a poll used. The manual says it recomputes "la méthode
  de Schulze, majoritaire ou par assentiment". For a plurality or approval
  poll, `--winner` compares the announced winner with the *Schulze* winner.
  An honest result can print `winner DISAGREES` and exit 1, and a wrong one
  can agree by coincidence. The closure-hash check is unaffected.
* **Resolution:** implement plurality and approval with a `--method` flag, or
  say plainly in the manual and in the CLI/GUI output that the winner check
  applies to Schulze polls only.

### M3. The rate limiter trusts a client-controlled `X-Forwarded-For` entry

* **Where:** `src/apps/core/ratelimit.py`, `client_digest`;
  `ansible/roles/polls/templates/nginx-vhost.conf.j2:89,102`.
* **What:** behind the proxy, the limiter keys on the **first**
  `X-Forwarded-For` entry. nginx sets the header with
  `$proxy_add_x_forwarded_for`, which *appends* to any value the client sent,
  so the first entry is whatever the client chose.
* **Why it matters:** the per-address limits on the registration form and on
  outgoing mail (R-5.8) can be bypassed by sending a fresh forged header per
  request. Forging a victim's address also fills the victim's bucket. The
  trustworthy values are `X-Real-IP` (set from `$remote_addr`) or the *last*
  entry. The docstring's claim that "the first entry is the client where nginx
  sets it" is inaccurate for this nginx configuration.

### M4. One vote per elector under concurrency depends on SQLite's `IMMEDIATE` mode

* **Where:** `src/config/settings/base.py` (`transaction_mode: IMMEDIATE`, now
  commented); `src/apps/ballots/services.py`, `cast_online`;
  `src/apps/registrations/services.py`, `token_channel`.
* **What:** `cast_online` reads the elector's `channel` without a row lock,
  then inserts. Elsewhere `select_for_update()` is used, but SQLite ignores it.
  Two concurrent casts on one token are serialised only because every atomic
  block takes the write lock at `BEGIN`. That is correct today. On another
  backend (PostgreSQL's default `READ COMMITTED`) both casts could insert a live
  ballot.
* **Also:** `src/config/settings/dev.py` replaces the whole `OPTIONS` dict,
  dropping `IMMEDIATE`, WAL and `busy_timeout`, so development does not run
  with the production concurrency semantics.

## Low

| # | Location | Note |
|---|---|---|
| L1 | `src/apps/backoffice/communesettings.py:134,152`; `src/apps/elections/pollimages.py:105` | Stored files are deleted inside the transaction, before commit. If a later write raises, the database rolls back to a row that names a file no longer on disk. `elections/sandbox.delete_poll` defers the same delete with `transaction.on_commit`. |
| L2 | `src/apps/audit/services.py`, `record` | `reason` is typed `Reason \| str` and never checked against `Reason`; model `choices` are not enforced on `create()`. The "a code, never prose" rule (§10) rests entirely on callers. |
| L3 | `tests/integration/test_inv1_separation.py`, `test_neither_models_module_imports_the_other` | Checks three modules only. Nothing would catch `ballots/views.py` (which already imports `registrations.services`) starting to import `registrations.models`. CLAUDE.md's "the two apps' modules do not import each other" overstates the rule actually held: `ballots.services` and `ballots.views` do import `registrations.services`, by design. |
| L4 | `src/apps/tally/methods.py`, `_tally_counted` | With ballots but no options, `max()` over an empty dict raises `ValueError`. Probably unreachable, since a poll needs two options to announce. |
| L5 | `verifier/core/src/canonical.rs`, `options_in` | The option set is derived from the CSV, so an option no ballot ranked is missing from the verifier's printed matrix although present in the published one. The winner is unaffected. |
| L6 | `verifier/core/src/canonical.rs`, `parse_hex` | Slices by byte offset: a non-ASCII character in user-supplied hex can land mid-UTF-8 sequence and panic instead of returning `None`. `u8::from_str_radix` also accepts a leading `+`. |
| L7 | `src/apps/backoffice/views.py`, `_filters` | The audit-log `date_to` becomes 23:59:59.000000, so events in the last second of the chosen day are excluded. |
| L8 | `src/apps/elections/management/commands/run_tally.py` | `help` says it "écrit les artefacts de publication"; it prints the publication JSON to stdout and writes nothing. |
| L9 | `src/apps/core/jobs.py` | `EXIT_ERROR = 2` is never used: an unhandled exception exits with Django's default status. `JobCommand.handle` logs `self.job_name`, which is empty for a subclass relying on the module-name fallback (all current subclasses set it). |
| L10 | `src/apps/core/tokensession.py`, `clear_ballot` | No caller in `src/`: a modification session entry is never cleared explicitly. |
| L11 | `src/apps/tally/tiebreak.py`, `break_tie` | No caller in `src/` (closure uses `tiebreak_order`); used by tests only. |

## Documentation corrected during this pass

These docstrings contradicted the code and were fixed in the documentation
commits. They are listed so a reviewer can check the new wording.

* `core/tokensession.py`: "two halves" introduced three bullets.
* `core/models.py`, `JobRun`: credited the row with the mutual exclusion the
  `flock` provides.
* `tally/methods.py`, `TallyResult`: implied a `None` winner arises only under
  the `physical` rule. `tally()` returns `None` on every tie.
* `elections/transitions.py`: cited `test_single_transition.py`; the file is
  `test_single_transition_point.py`.
* `backoffice/views.py`: said all eleven screens are poll-scoped and that
  Django admin is "not routed in production". Six screens are commune-level,
  and the admin is not installed anywhere.

## Open questions

* **Receipt mail links an address to a published ballot.**
  `registrations.mail.send_ballot_receipt` mails the voter their ranking and
  tracking code (R-6.4, decision log #6). The tracking code is also in the
  published CSV. Whoever can read that message (the mail relay's queue or
  logs, the recipient's provider) can therefore match an email address to a
  published ballot, outside the application and its retention purge. INV-1
  holds inside the database; this is a boundary it does not cover. Is it
  stated in the threat model and the data-protection notice?
* **Deployment of M3.** Is the production nginx the only proxy in front, or is
  there another hop that would change which `X-Forwarded-For` entry is
  trustworthy?
