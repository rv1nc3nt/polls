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

No high-severity issue was found. Every entry below has since been resolved
(2026-09-24); each says how, and keeps the analysis as found.

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

### M2. The verifier's winner check is Schulze-only, but the manual says otherwise — resolved

**Resolved:** the verifier implements plurality and approval
(`verifier/core/src/counted.rs`) and takes the method from the caller —
`--method` on the CLI, a choice in the GUI — since the CSV does not carry it;
Schulze stays the default, and the report names the method it applied. The
manual says to pass the method the results page shows.
`test_verifier_agreement.py` checks Python and Rust agree under all three
methods. The analysis below is kept as found.

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

### M3. The rate limiter trusts a client-controlled `X-Forwarded-For` entry — resolved

**Resolved:** `client_digest` now counts from the right of the header,
`TRUSTED_PROXY_HOPS` entries from the end (default 1, this role's nginx;
`polls_trusted_proxy_hops` in Ansible), so the key is an address a trusted
proxy wrote. `tests/unit/test_ratelimit.py` covers forged leading entries and a
second proxy. The analysis below is kept as found.

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

### M4. One vote per elector under concurrency depends on SQLite's `IMMEDIATE` mode — resolved

**Resolved:** `registrations.services.mark_voted` only moves `channel` off
`none` (`UPDATE … WHERE channel = 'none'`) and reports whether it did;
`cast_online` refuses before inserting and `enter_paper` refuses and rolls
back when it did not. That holds on any backend. `settings/dev.py` now keeps
base's database options. Covered by the "concurrent casts" tests in
`test_ballot_services.py`. The analysis below is kept as found.

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

| # | Location | Note | Resolution |
|---|---|---|---|
| L1 | `src/apps/backoffice/communesettings.py:134,152`; `src/apps/elections/pollimages.py:105` | Stored files are deleted inside the transaction, before commit. If a later write raises, the database rolls back to a row that names a file no longer on disk. `elections/sandbox.delete_poll` defers the same delete with `transaction.on_commit`. | File deleted with `transaction.on_commit`, as `sandbox.delete_poll` does; a rollback test covers it. |
| L2 | `src/apps/audit/services.py`, `record` | `reason` is typed `Reason \| str` and never checked against `Reason`; model `choices` are not enforced on `create()`. The "a code, never prose" rule (§10) rests entirely on callers. | `record` raises `UnknownAuditReason` for anything not a `Reason` value. |
| L3 | `tests/integration/test_inv1_separation.py`, `test_neither_models_module_imports_the_other` | Checks three modules only. Nothing would catch `ballots/views.py` (which already imports `registrations.services`) starting to import `registrations.models`. CLAUDE.md's "the two apps' modules do not import each other" overstates the rule actually held: `ballots.services` and `ballots.views` do import `registrations.services`, by design. | `test_every_module_of_the_two_apps_keeps_the_boundary` walks every module of both apps; CLAUDE.md states the rule as held. |
| L4 | `src/apps/tally/methods.py`, `_tally_counted` | With ballots but no options, `max()` over an empty dict raises `ValueError`. Probably unreachable, since a poll needs two options to announce. | `max(…, default=0)`: no winner, no crash. |
| L5 | `verifier/core/src/canonical.rs`, `options_in` | The option set is derived from the CSV, so an option no ballot ranked is missing from the verifier's printed matrix although present in the published one. The winner is unaffected. | The verifier takes the poll's option list (`--options`, a GUI field); a ranked option missing from it is an input error. |
| L6 | `verifier/core/src/canonical.rs`, `parse_hex` | Slices by byte offset: a non-ASCII character in user-supplied hex can land mid-UTF-8 sequence and panic instead of returning `None`. `u8::from_str_radix` also accepts a leading `+`. | Decoded byte-wise; any non-ASCII-hex character, `+` included, is refused. |
| L7 | `src/apps/backoffice/views.py`, `_filters` | The audit-log `date_to` becomes 23:59:59.000000, so events in the last second of the chosen day are excluded. | The bound is the next local midnight, exclusive. |
| L8 | `src/apps/elections/management/commands/run_tally.py` | `help` says it "écrit les artefacts de publication"; it prints the publication JSON to stdout and writes nothing. | Help text says it prints the publication document. |
| L9 | `src/apps/core/jobs.py` | `EXIT_ERROR = 2` is never used: an unhandled exception exits with Django's default status. `JobCommand.handle` logs `self.job_name`, which is empty for a subclass relying on the module-name fallback (all current subclasses set it). | An unhandled exception is logged with the resolved job name and exits `EXIT_ERROR`; `CommandError` keeps Django's path. |
| L10 | `src/apps/core/tokensession.py`, `clear_ballot` | No caller in `src/`: a modification session entry is never cleared explicitly. | Cleared after a modification and once the window has closed, so a shared browser keeps no ballot hash. |
| L11 | `src/apps/tally/tiebreak.py`, `break_tie` | No caller in `src/` (closure uses `tiebreak_order`); used by tests only. | Removed; tests and the tally-methods page use `tiebreak_order`. |

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
  trustworthy? *Answered by configuration:* `polls_trusted_proxy_hops`, documented
  in the instance administrator's guide.
* **There is no threat-model document.** The receipt-mail question above asks
  whether that linkage is stated "in the threat model", and there is none. Its
  substance is spread over spec §5 and §7, `review-guide.md`
  ("Security- and privacy-sensitive areas") and this file. Writing one is new
  work, not yet agreed.
