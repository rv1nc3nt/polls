<!-- SPDX-License-Identifier: 0BSD -->

# Specification decision log

Per §0 of `spec-plateforme-vote.md`, a divergence between the implementation
specification and the functional requirements it restates is resolved in favour
of the requirements, and the specification corrected. This file records where the
**code** departed from the specification, so a reviewer can settle each one rather
than discover it — and keeps the entry after it is settled, since the resolution
is the point: it is what stops the next reader from "fixing" the code back
towards a specification wording that was deliberately changed out from under it.

Items 1–6 were settled on 2026-09-09 by amending `spec-plateforme-vote.md` and,
where noted, the functional requirements (`cahier-des-charges.md` /
`requirements-en.md`). Each keeps its context and carries the resolution
inline.

## Status at a glance

Entries marked **open** still need a decision; the rest are kept for their
reasoning.

| # | Entry | Status |
|---|---|---|
| 1 | Retention purge on a poll that closed but was never published | settled |
| 2 | Tracking code in the registration email (R-5.6) | settled |
| 3 | Plurality with a tied first group | settled |
| 4 | The registration window admits a channel change for the paper channel | settled |
| 5 | Paper entry is refused outright when an online ballot exists | settled |
| 6 | A ballot *modification* sends no confirmation email | settled |
| 7 | The commune record is a model the domain model (§3) does not list | settled |
| 8 | Option labels cannot be corrected after the poll leaves draft | settled |
| 9 | TLS in the Ansible role is certbot only | recorded, no spec change — nginx-acme deferred until Debian packages a build |
| 10 | No screen ever created a poll | **open in part** — creation and templates settled; direct duplication of a poll open |
| 11 | Screen 3 (import de la liste électorale) was gated per poll | settled |
| 12 | Nothing ever called `open_poll` or `close_poll` by hand | settled; superseded in part by #19, #33, #34 |
| 13 | R-3.10's early preview is a state, not a flag | settled; its optional `announced` reversed by #19 |
| 14 | The public page read "open" off `state`, not the clock | settled |
| 15 | The back-office read the same "open" off `state`, and R-3.4's extension did not check the clock either | settled |
| 16 | R-8.6's formal reconciliation has no described flow | settled; see #34 for manual closure |
| 17 | R-8.2 bis's required content is not carried by the receipt as specified | **open in part** — receipt settled; signed-form layout unspecified |
| 18 | Option images and commune branding are not yet in the backup/restore playbook | settled |
| 19 | `announced` became mandatory, reversing item 13's "optional waypoint" | settled |
| 20 | The draft-preview share link (R-3.10 bis) is deliberately not frozen | not a divergence; rationale recorded |
| 21 | R-3.12's images moved from per-option to a shared per-poll library | settled |
| 22 | `PollImage.alt_text` is a default, overridable per reference | settled |
| 23 | `image:<n>` gained an optional display-size suffix | settled |
| 24 | A poll opened by hand ahead of `opens_at` opened in the back-office only | settled |
| 25 | Deleting a paper ballot re-opened online voting for nobody who had not registered | settled |
| 26 | Sandbox polls became triable through their link, and deletable | settled |
| 27 | Approving an application onto a cleared paper shell | settled |
| 28 | Electors awaiting confirmation: resend, not confirm | settled |
| 29 | A paper ballot keyed for an unconfirmed registration was not counted | **open question** for the requirements owner (R-5.5 wording) |
| 30 | An elector listed twice on the roll is flagged, not blocked | settled |
| 31 | Uncountersigned paper entries are published as their own figure | settled |
| 32 | A corrected paper ballot is countersigned again | settled |
| 33 | The clock refuses, the state admits | settled |
| 34 | A poll may be closed early, by hand, with a reason | decided |
| 35 | Definitive actions are confirmed on a separate page | decided |
| 36 | A sandbox poll's result is reachable through its link | decided |
| 37 | The verifier reads the publication document, and every method | decided |
| 38 | A poll requiring reconciliation cannot be closed early | **open question** for the requirements owner (R-3.4 and R-8.6) |

## 1. Retention purge on a poll that closed but was never published

**Specification, §11.** Two statements that cannot both hold:

> The anchor is closure and not publication, because a poll that closes and is
> never published […] would otherwise keep its identity data for ever.

> the INV-2 trigger […] permits `DELETE` of a registration only where the poll
> is `published`. […] The same applies to INV-7 […] permits `DELETE` only where
> the poll is `published`.

T-58 requires the first: *poll closed and never published, two months later →
purge runs on the closure anchor; identity data gone*. A trigger admitting
`DELETE` only in `published` would refuse exactly that purge, and the poll would
keep its identity data for ever — the outcome the closure anchor exists to
prevent.

**What the code does.** The INV-2 and INV-7 delete triggers permit `DELETE`
where the poll's state is `closed` **or** `published`
(`src/apps/elections/migrations/0002_invariant_triggers.py`). Everything else in
§11 is unchanged: the exception is expressed inside the trigger rather than by
disabling it, `AuditEvent` is untouched, and the purge remains the sole writer
past `closes_at`.

**Settled (2026-09-09).** §11's two trigger sentences now read `closed` or
`published`, with a line stating why `closed` alone must be admitted. The
`retention.py` and `RollEntry` docstrings were corrected to match. The
alternative — anchoring retention on publication — contradicts §11's own
reasoning and T-58.

**Settled (2026-09-09), related.** R-13.3 previously fixed the retention term at
"two months running from **publication** of the result", which the closure
anchor of §11, T-58 and the code all contradicted. R-13.3 was amended (both
language files) to run the term from **closure of the poll**, with the reason
stated inline. The specification's §11 already read "closure" and needed no
change.

## 2. Tracking code in the registration email (R-5.6)

Already flagged by §6.2 step 7 of the specification itself, repeated here
because it is a choice the code makes. The confirmation email carries **no**
tracking code: the code is issued at cast (§6.3) and on the paper receipt
(§6.4). Putting one on a `Registration` row and a `Ballot` row is a join in all
but name and would destroy INV-1 and INV-5, and T-25 asserts no value whatever
is common to the two rows.

**Settled (2026-09-09).** R-5.6 was amended (both language files) to drop the
tracking code from the confirmation email: the email carries only the
modification link, where the poll permits one. The derived-value alternative
(a value derived from the token, stored nowhere) was rejected — it forces a
reword of INV-11 and hands the voter a code before a ballot exists to bear it.
§6.2 step 7 of the specification was updated to point here.

## 3. Plurality with a tied first group

**Specification, §8.2** defines plurality as the count of first preferences,
without saying what a first *group* holding several options means — possible
only where `allow_ties_in_ballot` is set on a `plurality` poll.

**What the code does.** Each option in the first group receives one count
(`apps/tally/methods.py`). The configuration that permits it is a
misconfiguration for the back-office to warn about (§6.5 screen 2), not
something to resolve silently in the tally.

**Settled (2026-09-09).** §8.2 now states the one-count-per-tied-option rule
explicitly and records that screen 2 warns on the `plurality` +
`allow_ties_in_ballot` combination at configuration time. No requirements
change.

**Wired (2026-09-09).** `config.configuration_warnings` returns the warning
codes and `backoffice.forms.config_warnings` the French; screen 2 renders them
as an advisory `role="status"` callout in both the draft editor and the
read-only view. It is non-blocking by design — the tally handles the
combination deterministically, so it is not an opening blocker (§4).

## 4. The registration window admits a channel change for the paper channel

**Specification, §6.4 and INV-2.** A paper ballot may be keyed until
`paper_entry_deadline`, which is `≥ closes_at`, and keying sets the elector's
voting-channel indicator (R-9.1) to `paper`; deleting the ballot clears it
again (R-9.4). But INV-2 as restated in §5.1 and the trigger design (§10) forbid
*every* `Registration` write at or after `closes_at`, the retention `DELETE`
aside. A paper ballot keyed in the keying window — the case T-56 requires to
work — cannot then record its channel.

**What the code does.** `inv2_registration_insert_window` and
`inv2_registration_update_window`
(`src/apps/elections/migrations/0002_invariant_triggers.py`) permit one write
past `closes_at` and only until `paper_entry_deadline`: an `INSERT` on the
`paper` channel, or an `UPDATE` that moves `channel` to or from `paper` and
changes nothing else. `windows.check_registration_window` takes a `channel`
argument and applies the same wider bound. Every other registration write still
stops at `closes_at`, and the equality list in the `UPDATE` trigger is what
holds that line — it must track the model.

This mirrors the ballot window, which already admits the paper ballot itself
over exactly this period, and follows §6.4's own reasoning that keying is
transcription of a vote cast before `closes_at`, not a vote in its own right.

**Settled (2026-09-09).** §5.1's INV-2 statement now carries the paper-channel
carve-out: a change to the voting-channel indicator for the `paper` channel is
permitted until `paper_entry_deadline`, mirroring the ballot window. The note
records that the equality list in the `Registration` `UPDATE` trigger is what
confines the carve-out to the channel field and must track the model. No
requirements change — INV-2 is a specification concept.

## 5. Paper entry is refused outright when an online ballot exists

**Specification, §6.4 / R-9.3, T-8.** Where an elector has already voted online,
the operator may key a paper ballot "only after express confirmation and entry
of a mandatory reason, both being recorded" — a reasoned override. T-8 asserts
the same: *proceeds only with confirmation and reason; both logged.*

**What the code does.** `enter_paper` refuses. There is no override path: the
elector's online vote stands, and screen 5 is a dead end for them (a red notice,
no form). Where the poll permits modification the notice points the elector to
the online modification link; where it does not, it states that the online vote
is final.

**Why.** R-9.3's override only makes sense if the paper ballot then *replaces*
the online one, and that is not implementable. §7 makes an online ballot
unlocatable from the registration — the operator holds a roll entry, not the
token, and no server-side path maps a registration to its ballot (that is the
anonymity guarantee, not an omission). So the override could only either:

- write the paper ballot `live` alongside the un-findable online one → two live
  ballots for one voter, double-counted in the tally, breaking INV-5 and
  "live set = tally set"; or
- write it not-in-force → recorded but never counted, which is a confusing
  artefact that changes nothing about the outcome.

Refusing is the honest option. It also matches the spec's own intent for the
common case: a poll with `allow_ballot_modification` off has deliberately made
an online vote final (§7), and an override that counted would be a back door
around exactly that. The rarer case — a compromised online vote — has no remedy
under §7 regardless (R-7.6: token loss is unrecoverable by anyone), so the
override could not have helped there either.

**Settled (2026-09-09).** R-9.3 was amended (both language files) to drop the
reasoned override: paper entry against an existing online ballot is refused,
because an anonymous online ballot cannot be located from the registration
(R-7.4) and so cannot be displaced. §6.4's `channel = online` bullet and T-8
were rewritten to match. The tracking-code-based in-person change path is
recorded here as a possible future feature, not adopted.

## 6. A ballot *modification* sends no confirmation email

**Specification, §6.3 / R-6.4, T-13's neighbourhood.** R-6.4: "On submission,
the elector is shown a summary of their ranking and their tracking code, and
receives both by email." It does not distinguish a first cast from a
modification.

**What the code does.** A first cast emails the summary and tracking code
(`registrations.services.send_ballot_receipt`, called from the ballot view's
`on_commit`). A modification shows the summary on the confirmation page but
sends **no** email.

**Why.** The modification flow runs from a session entry holding only
`ballot_hash` — the token was exchanged and the voter redirected to a
token-free URL (R-7.4 ter, T-21), and `apps.core.tokensession` deliberately
keeps no voter reference beside the ballot hash (INV-1). `modify` therefore has
no path to the registration and no way to obtain the address: the only mapping
that could yield it is `ballot_hash` → `voter_hash` → `Registration`, which
R-7.4's "no join between the two tables is possible" forbids. First cast can
mail because it alone runs in the request that carries the token
(`voter_hash` → registration), which is spent immediately after.

The tracking code is unchanged across versions (R-7.2) and was mailed at the
first cast, so a modifying voter is not left without it; the receipt page
restates it in any case.

**Settled (2026-09-09).** R-6.4 was amended (both language files): the emailed
receipt is required on the *first* cast only; a later modification shows the
on-screen summary and sends no email, the tracking code being unchanged (R-7.2)
and already held. §6.3 was updated to match. The weaker-token alternative
(token kept in the modification URL) was rejected — it trades away part of
T-21 for a redundant email.

## 7. The commune record is a model the domain model (§3) does not list

**Specification, §6.5.11** has the first-run wizard "creating the commune
record and the initial administrator", but §3 enumerates no such entity and no
requirement fixes its fields. §13 item 4 defers "the named data-protection
referent for the privacy notice" as configuration without saying where it
lives.

**What the code does.** `apps/core/models.py` gains a `Commune` model: a
singleton (`id` pinned to `1`, a check constraint holding it there;
`Commune.current()` reads it) carrying `name`, `data_protection_referent`,
`data_protection_contact`, and, since (§6.5.14), `public_base_url`, `logo` and
`favicon` (each with a `*_content_type`/`*_content_hash` pair). The first-run
wizard (screen 11) creates the row in the same transaction as the initial
`commune_admin` account, so the two never exist apart; screen 14 is the only
writer afterwards. A context processor (`apps.core.context.commune`) puts it on
every template; `base.html` uses `name` (or `logo`, once one is set) for the
site header and the favicon link, and the registration privacy notice uses the
referent fields (R-13.1, R-13.2) — each with a generic fallback for a
not-yet-installed instance.

**Why a model and not settings.** R-13.2's referent is operator-editable
configuration an adopting commune sets once, at install, without touching the
source or the environment — which is the whole point of the wizard existing
(§6.5.11, §14). Settings would push it back into deployment. R-1.3 (single
commune, one instance) is what makes a one-row model the right shape rather
than a tenant table.

**Settled (2026-09-12).** §3 gained a `Commune` entry (§3.10) listing every
field above, and §13 item 4 now points at it. This was additive — it
implements §6.5.11 rather than contradicting anything — so nothing else in
the specification changed.

## 8. Option labels cannot be corrected after the poll leaves draft

**Specification, §3.8 and T-23.** §3.8: "A translation added or **corrected
after closure** therefore cannot change the closure hash or the result — a
property the verifier depends on." T-23 exercises exactly that: *option label
corrected after publication → closure hash and result unchanged*. Both sentences
presuppose that correcting a label after `draft` is a supported operation.

**What the code does.** The INV-6 option triggers
(`inv6_option_insert_frozen` / `_update_frozen` / `_delete_frozen`,
`src/apps/elections/migrations/0002_invariant_triggers.py`) freeze
`elections_polloption` **whole** once the poll is not `draft` — every column,
`label_i18n` included. Screen 2 is read-only past `draft` (§6.5.2) with no
label-only edit path, and no service function writes one. So a post-publication
label correction is not merely unimplemented, it is refused at the database.

**Why this is nonetheless fine for T-23's property.** The hash and the result
are functions of option **ids** and tracking codes only: `canonical_record`
serialises `tracking_code` and a `ranking` of ids, and `closure.tallied` tallies
`ranking` against `[option_id …]`. Neither reads `label_i18n`; labels reach the
publication solely through `document["options"]`, a lookup table beside the
result. `tests/integration/test_publicsite.py::test_t23_*` asserts this
directly — two polls identical but for their labels (tracking codes and ballots
pinned equal) produce byte-identical closure hashes and identical winner,
matrix and derivation — and also asserts the freeze, so the divergence is
pinned rather than latent.

**Settled (2026-09-09).** Labels are fixed at `draft` exit — the safer reading:
a label is the record of what a voter ranked, and the id-based hash and tally
mean nothing is lost by forbidding a later edit. The code already does this
(`inv6_option_*_frozen` freeze `elections_polloption` whole outside `draft`, and
R-3.3 freezes all configuration at `open`), so no code change.

The blocker was that R-10.7 — authoritative, both language files — read "a
translation **added or corrected after closure** can affect neither the result
nor the hash", which presupposes the edit is possible; §3.8 faithfully restated
it. R-10.7 was amended (both files) to state the property affirmatively — the
result and the hash are *independent of* the labels and their translations — and
to point at the R-3.3 freeze, dropping the post-closure-edit presupposition.
§3.8 and the T-23 row were reworded to match; T-23 now asserts the freeze as the
intended rule (a `label_i18n` write past `draft` is refused) rather than as a
pinned divergence. The docstrings in `canonical.py`, `closure.py`,
`elections/models.py` and `docs/canonical-serialisation.md` that phrased the
property as "a translation corrected after closure cannot move the hash" were
reworded the same way.

## 9. TLS in the Ansible role is certbot only

**Specification, §15 step 7 / §14.** "TLS per §14", where §14 describes
`ngx_http_acme_module` (nginx-acme) as the preferred mechanism "where a
vendor-packaged build is available" and certbot as "the lower-maintenance
choice … despite being an extra component" on a machine meant to be left alone.

**What the code does.** `roles/polls/tasks/provision.yml` implements the
certbot path: it installs `certbot` and `python3-certbot-nginx`, obtains the
certificate with `certbot --nginx`, and re-renders the vhost from
`nginx-vhost.conf.j2` with an equivalent `:443` block so the file stays under
Ansible's control. `polls_tls_method: nginx-acme` is accepted but only emits a
`debug` note pointing back to certbot; `polls_tls_method` defaults to `certbot`.

**Why.** §14 already names certbot the right default for the "left alone"
target this role serves, and a self-compiled dynamic module "must be rebuilt on
every nginx upgrade" — which an unattended-upgrades host will do without a
human present. The nginx-acme path is worth adding once Debian ships a
vendor-packaged build; until then it is a documented no-op rather than a
half-working second path.

**Not settled by amending the spec.** This implements one of the two options
§14 offers rather than contradicting it. Recorded here so the gap is visible;
no spec or requirements change.

## 10. No screen ever created a poll

**Specification, §6.5.** R-3.1 says what a poll comprises and R-3.2 that it
starts in `draft`, but the twelve numbered screens never include the step that
produces the first row: screen 2 is explicitly "editable only in `draft`",
which presupposes the `draft` poll it edits already exists. `access.py`'s own
docstring named the gap before any screen closed it — `commune_admin` is
"gère les comptes et crée les scrutins" — and `Action.POLL_CREATED` sat in the
audit vocabulary (`apps/audit/models.py`) unused by any write path but tests.
Until now the only way to get a `Poll` row into a running instance was the
Django shell.

**What the code does.** A "Nouveau scrutin" screen, commune-level like
screens 10 and 12 (`access.require_commune_admin` — a poll being created has
no `poll_admin` yet), at `/mairie/nouveau/`. It reuses screen 2's form
(`PollConfigForm`) and option formset unchanged, adding only `is_sandbox`
(`PollCreateForm`, R-3.7 — fixed at creation and so excluded from
`save_configuration`'s field set). The write path is
`elections.config.create_poll`, which builds the `Poll` and its options in one
transaction and logs `Action.POLL_CREATED`. Creating grants the admin no role
on the poll (§3.7's split, same as `role_admin`): the screen redirects to
"Rôles par scrutin" for the new poll so that granting one stays a separate,
audited step.

**Why R-3.6 was left out at first.** "A poll may be created by duplicating an
existing poll or a template" is a convenience on top of creation, not a
substitute for it — the gap this item closes is that there was no base case
at all, template or not. Duplication carried its own decisions (what a
"template" is, whether a sandbox poll can be a source) that were worth their
own review rather than folding into the fix for a missing screen. The create
screen started from a blank configuration only until that review landed.

**The template half settled and built (2026-09-11), by amending the
requirements.** R-3.6 bundled two different sources — "an existing poll" and
"a template" — under one phrase, "the configuration," without saying what a
template itself is or how one is produced; that omission is exactly what made
it a convenience nobody could build yet. A new R-3.9 supplies the missing
half: a template is a named, commune-level object distinct from a poll,
carrying the tally mechanism and ballot rules only — never `title`,
`description` or `options`, which a direct poll duplication would keep and a
template-built poll enters fresh, same as a blank one. §3.9 and §6.5 (screen
13, plus *enregistrer comme modèle* on screen 2) describe the design, and both
are now built: `apps.elections.models.PollTemplate` is the row,
`apps.elections.polltemplates` the one writer (`save_as_template`, callable in
any poll state since INV-6 freezes the fields it reads from `draft` onward;
`rename` and `delete`), and "Nouveau scrutin"'s `?modele=` seeds the creation
form from a chosen template's mechanism fields alone. This settles the divergence
the way §0 asks — by correcting the requirements rather than leaving the spec
to paper over a gap — and closes it: direct duplication is what remains
open, tracked below.

**Direct duplication of an existing poll remains open on its own terms.**
R-3.9 settled the template half only. Cloning a poll's `title`, `description`
and `options` verbatim raises questions a template sidesteps by not carrying
them at all — whether a sandbox poll may be a source, whether per-language
content missing at the source should block the clone the way it blocks
opening (§3.8) — and stays tracked here rather than folded into this item.

## 11. Screen 3 (import de la liste électorale) was gated per poll

**Requirements, R-2.1's role table.** "Commune administrator — Creates polls,
assigns the roles specific to each poll, **imports the electoral roll**. This
role does not of itself carry any access to ballots." The roll import is
explicitly a commune administrator's action, not a poll administrator's.

**Specification, §6.5.** The screen list read "Screens, gated by the per-poll
roles of §3.7 — except 10, 11 and 12" — screen 3 among the nine gated per poll,
contradicting R-2.1 directly.

**What the code did.** `roll_import` and `roll_import_review` were
`@require_poll_role(Role.POLL_ADMIN)`, reached from one poll's own menu at
`scrutin/<poll_id>/liste-electorale/`. This was backwards on its own terms
quite apart from R-2.1: `WorkingRollEntry` is commune-wide (§3.2), so an import
started from one poll's back-office silently replaced what *every* poll still
in `draft` would pick up at its opening — a poll submenu is exactly the wrong
place to invite that confusion from, and a user of the back-office noticed the
same thing from the UI side before this was traced to R-2.1.

**Settled (2026-09-11).** The two screens moved to the general menu, gated by
`require_commune_admin` like screens 10 and 12, at `liste-electorale/` and
`liste-electorale/verification/` with no poll in the URL at all. A poll's own
menu keeps a read-only entry, `roll_status` (`require_poll_role(POLL_ADMIN)`,
`scrutin/<poll_id>/liste-electorale/`) — filename, row count, when it was
imported and by whom, no form. §6.5's screen list and item 3 were corrected to
match (screen 3 added to the commune-level exception, its description
rewritten); `apps/elections/rollimport.py`'s module docstring, which had made
the same "reached from one poll's back-office" claim, was corrected too.

## 12. Nothing ever called `open_poll` or `close_poll` by hand

**Requirements, R-2.1.** The role table gives the *administrateur de scrutin*
the power to "ouvre, clôt et publie le scrutin" — opens, closes and publishes
the poll — the same three verbs, in a row, for the same role. (R-2.1 has since
gained a fourth, "annonce" — item 13 below — but that one was never a gap the
way these three were: R-3.10's `announced` state didn't exist yet to have a
missing button.)

**Specification, §4, as it read until now.** "Both boundary transitions are
scheduled, and neither is trusted to be punctual" — `draft → open` and
`open → closed` were described, and built, as exclusively the work of the
`open_poll`/`close_poll` cron commands. Screen 2 (§6.5) offered nothing to
call either one; only *publier* (screen 9, `transitions.publish_poll`) had a
button. R-2.1's "ouvre, clôt" had no code behind it at all — not a case of the
spec disagreeing with the requirements so much as the spec never having been
asked to reconcile the two, since nobody had traced R-2.1's verb against §4
until this was raised.

**What the code does now.** Screen 2 gained two actions, both going through
the same guarded transition functions the scheduled commands call
(`opening_blockers`/`closing_blockers`), so nothing a cron run would refuse
can be forced through by hand either:

- *Ouvrir maintenant* — offered throughout `draft` (and, since item 13,
  `announced`), at any time, including ahead of `opens_at`. Safe to allow
  early: the ballot and registration write paths (`apps.elections.windows`)
  gate on the clock against `opens_at` itself, never on `state`, so opening
  early moves the roll snapshot and `opening_seed` sooner but admits no vote
  and no registration before the configured instant.
- *Clôturer maintenant* — offered only once `paper_entry_deadline` has
  passed, never before. Early closure is not safe the same way: `closure_hash`
  and the §9 counts are computed once, at the instant `close_poll` runs, while
  the same clock-only write paths keep accepting ballots and registrations up
  to the real deadline regardless of `state`. A manual close ahead of the
  deadline would freeze a hash that omits ballots the window would still
  legitimately accept, and would hide the paper-entry screens from the entry
  operator before their window has actually closed — so the two manual
  transitions are deliberately not symmetric. This is also the only caller of
  `close_poll`'s `override_reason` (R-8.7 bis): nothing before this called it
  with a reason, since a scheduled command cannot supply one.

**Settled (2026-09-11).** §4 was corrected to describe both the scheduled and
the manual path, with the asymmetry above stated inline; §6.5's screen-2 entry
and §12's acceptance tests (T-67, T-68) were updated to match. No requirements
change was needed — R-2.1 already said this; the specification and the code
were the two that had to catch up.

**Superseded in part** by #19 (no opening from `draft`: a poll must be
`announced` first), #33 (the window checks now require `state = open`) and #34
(*Clôturer maintenant* is offered before the deadline too, as an early closure
with a reason).

## 13. R-3.10's early preview is a state, not a flag

Not a divergence discovered after the fact — recorded because the first
attempt at R-3.10 (same day) got this wrong and it is worth saying why, rather
than leaving a future reader to wonder why the obvious-looking alternative was
rejected.

**The rejected design.** A `visible_before_opening` boolean on `Poll`,
editable like any other `draft` field, with the public site showing a poll in
`draft` whenever the flag was set. This worked, but a `draft` poll is — by
R-3.3 — one whose configuration is *still freely modifiable*: the public page
would have had to either show content that could change under a viewer's eyes
between two requests, or the feature would have had to freeze configuration
early on some basis *other* than the state field INV-6 already keys off,
duplicating that mechanism for one flag.

**What the code does instead.** `PollState` gained a fifth value, `announced`,
sitting optionally between `draft` and `open` (R-3.2, R-3.10). Reaching it is
a transition (`announce_poll`, manual only, screen 2, R-2.1) like the others,
not a field edit, so it freezes configuration through the *existing* INV-6
trigger (`state != draft`) rather than a new mechanism — and a `draft` poll
is, and remains, invisible on every public page under every configuration,
which is what R-3.10 actually needed to guarantee.

**Settled (2026-09-11).** Decided and built the same day the flag-based
version was replaced; no period where the flag design shipped. R-3.10, R-3.1,
R-3.2, R-3.3 and R-13.3 bis were written for the state-based design from the
start of this entry's existence in the requirements.

**Not reopened by R-3.10 bis (2026-09-19).** The share-link preview added
later (item 20) is not the rejected design above revived: that one made a
`draft` *publicly discoverable* by a flag any visitor could trip over; this
one is opt-in, unlisted, and reachable only by a link the poll admin
generates and hands out deliberately. The one objection from this entry that
does carry over — a viewer sees content that can still change — is accepted
there explicitly, and the page says so, rather than solved by freezing.

## 14. The public page read "open" off `state`, not the clock

**Specification, §6.6 (before this entry).** "While the poll is open the page
shows the propositions, the closing instant, [...]" — read literally, this
keys the "Consultation ouverte." banner and the registration link off
`Poll.state`, the same way `apps/publicsite/views.py` did.

**Why that is wrong.** §5.1 and §6.4 are explicit that the write path never
consults `state` for exactly this reason: the scheduled `open_poll`/`close_poll`
commands can run late, and `close_poll` in particular waits for
`paper_entry_deadline`, which sits after `closes_at` whenever a paper window is
configured (§6.4) — a gap measured in days on a poll that wants one, not
minutes. A poll admin may also call `open_poll` by hand ahead of `opens_at`
(§4). In every one of these windows `state` disagreed with the clock, and the
public page — unlike the write path — was still keying its display off
`state` alone: it kept showing "Consultation ouverte." and the "S'inscrire
pour voter" link deep into the paper-entry window, when every online vote
those visitors could have attempted was already being refused with "Le vote
en ligne est clos." (§5.1); a poll opened early by hand would conversely have
shown the "not yet open" notice's opposite — an "ouverte" banner — before the
window checks would accept anything. A user reported the first case directly:
the poll page kept reading open well after the actual deadline had passed and
no vote could get through.

**What the code does.** `apps/publicsite/views._status_key(poll, now)`
computes `"preview" | "open" | "published" | "closed"` from `state` **and**
`opens_at`/`closes_at`, mirroring exactly what `apps.elections.windows` checks
on the write path, and both `poll_list` and `poll_detail` render off that
instead of off `state` directly. The one substantive new case is the gap
between `closes_at` and whichever of `paper_entry_deadline` or the scheduled
job's next run comes later: `state` still reads `open` there (correctly —
paper keying and countersignature legitimately continue), but the page now
says "Le vote en ligne est clos." instead of repeating "Consultation
ouverte.", and withholds the registration link, since nothing behind it would
accept a submission.

**Settled (2026-09-16).** §6.6 now states the clock-gating explicitly, next to
§5.1's and §6.4's existing statements of the same principle for the write
path.

## 15. The back-office read the same "open" off `state`, and R-3.4's extension did not check the clock either

**Specification, §4 and §6.5.2 (before this entry).** "Extension of `closes_at`
is permitted only while `state = open` and only to a later timestamp" (§4);
screen 2 offered the extension "as a separate, reasoned action while `open`"
(§6.5.2) — both keyed purely off `state`, the same gap entry 14 found and fixed
on the public page.

**Why that is wrong.** Two separate problems, one on each side of the same
gap:

- **Display.** The dashboard (§6.5.1) and screen 2 (§6.5.2) both still showed
  the raw `état: Ouvert` deep into the paper-keying stretch after `closes_at`,
  with no notice that online voting had actually stopped — exactly the
  confusion entry 14 fixed on the public page, just not carried over to the
  screens the poll admin themselves uses. A user reported this directly: the
  public page said the right thing, the back-office didn't.
- **A real gap, not just a display one.** `extend_closes_at` checked only
  `poll.state == PollState.OPEN`, never the clock. Since `state` reads `open`
  through the whole paper-keying stretch, nothing stopped a poll admin —
  intentionally or by a stale page reload — from "extending" `closes_at` to a
  future instant *after* online voting had already, actually, closed. Because
  `apps.elections.windows.check_ballot_window` and
  `check_registration_window` consult only the clock against `closes_at`, not
  `state`, doing so would have genuinely reopened online voting and
  registration for real ballots and registrations, not merely displayed a
  stale banner. R-3.4 calls this "extending the closing date," which
  presupposes a vote still running to extend; past the actual `closes_at`
  there is nothing left to postpone, only a closed vote to reopen.

**What the code does.** `apps.elections.windows.online_voting_closed(poll,
now)` is the one clock gate, shared by three callers: the public page
(`apps.publicsite.views.poll_detail`, refactored from entry 14's bespoke
check onto this shared function), the dashboard
(`apps.backoffice.dashboard._actions_for_state`, which now omits "Reporter la
date de clôture" from the permitted actions once it is true, rather than
linking to a form that is no longer there) and screen 2
(`apps.backoffice.views.poll_config`, which shows the same "Le vote en ligne
est clos." notice as the other two and does not construct `ExtensionForm` at
all once it is true). `elections.transitions.extend_closes_at` calls the same
function directly and refuses with `TransitionRefused` if it is true — the
backstop behind all three display fixes, so a forged POST past the missing
form still cannot reopen a closed vote.

**Settled (2026-09-16).** §4 and §6.5.2 now state the clock gate explicitly,
next to §6.6's existing statement of the same principle for the public page.

## 16. R-8.6's formal reconciliation has no described flow

**Requirements, R-8.6.** "Where formal reconciliation is required by the
configuration, the paper forms are retained by the commune and reconciled
against the recorded ballots at closure, the reconciliation record being
signed and archived. Failing that, the audit log serves as the record."

**Specification.** `paper_requires_reconciliation` exists as a `Poll` field
(§3.1, default `false`) and is named in §13's deferred-configuration list, but
nothing else in the document says what happens when it is set: no screen, no
flow, no closure-time step, no audit action, no acceptance test. Contrast with
the other two paper-channel options R-8.2 offers alongside it: countersignature
(R-8.7/R-8.7 bis) gets a full description — `pending_countersign` status,
screen 7, the closure guard and override in §9 and §4, T-19/T-32/T-57/T-68 —
and the signed form is at least named everywhere paper entry is described
(§6.4, R-8.2). Reconciliation alone is a bare boolean with nothing behind it.

**Settled (2026-09-17).** A count comparison, not a per-form checklist: a
per-form match against `PaperBallotLink` rows would require the paper forms
themselves to carry a machine-readable identifier, which R-8.2 bis's signed
form does not and the plain R-8.4 receipt cannot (it is handed to the elector,
not retained by the commune). What R-8.6 actually asks the commune to compare
is a count the commune holds physically (the retained forms) against a count
the system holds (the recorded ballots) — the same shape §9's own participation
counts already take.

`ballots.models.ReconciliationRecord` (§3.5's neighbour): one row per poll,
`forms_retained_count` entered by the poll admin, `recorded_ballots_count`
computed from the live paper ballots at the instant of signing — never entered,
since the operator has no independent way to know it is right — plus an
optional prose `note` for a discrepancy, `signed_by` and `signed_at`. Kept as
its own model rather than a structured audit event: §10 already reserves
`AuditEvent.reason` for a code, never prose, and a discrepancy note is exactly
the kind of thing that belongs on a referenced row instead (the same reasoning
that keeps `PaperBallotLink.note` off the audit table). `Action.RECONCILIATION_RECORDED`
logs that it happened, referencing the new row, with the two counts in `after`
— no prose, same discipline as every other audit event.

Screen 9 (§6.5.9), not a new numbered screen: it is entered by the poll admin
while the poll is still `open`, once `paper_entry_deadline` has passed — the
same restriction screen 2 already puts on the manual `close_poll` trigger, for
the same reason (a count taken earlier could be made stale by a paper entry or
correction the window still legitimately admits). It gates closure: unlike
`pending_countersign` (R-8.7 bis), R-8.6 offers no override, so
`transitions.closing_blockers` adds a `reconciliation_pending` blocker that
`_close_poll_locked`'s existing `overridable` check (which accepts only
`pending_countersign:`-prefixed blockers) already refuses unconditionally.
Where the flag is off, none of this runs and `closing_blockers` never mentions
it — R-8.6's own fallback, "the audit log serves as the record", already holds
for that poll from the paper-ballot audit events §10 requires regardless
(`PAPER_BALLOT_CREATED`/`_CORRECTED`/`_DELETED`).

Not published: unlike the countersignature override, which R-8.7 bis and
T-19/T-32 explicitly send into the publication, R-8.6 says only "signed and
archived" — an internal record, visible to the poll admin and the auditor on
screen 9, never on the public results page or in the CSV/JSON artefacts.

**Since #34** the manual `close_poll` is no longer held back until
`paper_entry_deadline`; recording the reconciliation still is.

## 17. R-8.2 bis's required content is not carried by the receipt as specified

**Requirements, R-8.2 bis.** Where the signed paper form is required, it must
comprise the ranking, the honour declaration, the elector's identity, and a
statement that a paper ballot stays associated with the elector's identity in
the system for traceability and any subsequent deletion at their request. "In
the absence of a form, this information is carried on the receipt provided for
at R-8.4."

**Specification.** `paper_requires_signed_form` defaults to `false` (§3.1,
§13 item 5), so by default the receipt is the *only* document that can carry
R-8.2 bis's statement. At the time this entry was written, every place the
receipt was described — `PaperBallotLink` (§3.5), the keying flow (§6.4), and
screen 5 (§6.5, "a printable receipt (R-8.4) rendered as an HTML page with a
print stylesheet") — said only that it bears the tracking code, with nothing
requiring the ranking or R-8.2 bis's traceability/deletion statement when no
signed form exists.

**Settled (2026-09-20), receipt side.** `paper_receipt.html` now renders the
recorded ranking unconditionally and, whenever `show_identity_notice` is true
— `paper_receipt` (`apps/backoffice/views.py`) sets it to exactly
`not poll.paper_requires_signed_form`, i.e. "in the absence of a form" — the
R-8.2 bis traceability/deletion statement. R-8.2 bis's "cette information" is
read as the singular *mention* it immediately follows, not the form's full
contents, so neither the elector's identity nor the honour declaration is
expected on the receipt: an unsigned slip handed back to the elector is not
the place for either. **Not settled**: the signed-form path still has no
described layout, so nothing yet specifies where on that form its four
elements — ranking, honour declaration, identity, traceability mention —
must appear.

## 18. Option images and commune branding are not yet in the backup/restore playbook

**Specification, §14 (Backups).** "Since §3.1 bis, the database alone no
longer reconstructs every public page: `DJANGO_MEDIA_ROOT` (option images,
R-3.12; the commune logo and favicon, §6.5.14) needs the same nightly
coverage and the same off-host replication as the database snapshot."

**What the code does.** `ansible/roles/polls/tasks/backup.yml` and
`polls-backup.sh.j2` still snapshot only `db.sqlite3` — `VACUUM INTO`,
integrity check, retention window, optional `rsync` to
`polls_backup_replicate_to`. `provision.yml` creates
`{{ polls_state_dir }}/media`, `polls.env.j2` points `DJANGO_MEDIA_ROOT` at it
and nginx serves it, so uploads work end to end — but nothing backs the
directory up, and `restore.yml` restores the database alone. A restore today
brings back every poll's configuration, including `PollOption.details_i18n`
text that references images by id, with the images themselves gone: a broken
reference, not a wrong one, since rendering drops a reference to a missing
`OptionImage` row rather than erroring (§3.1 bis) — but broken all the same.
Screen 14's logo and favicon (`Commune.logo`/`.favicon`) land in the same
directory and are lost the same way, except there the database row still
names the missing file directly (`Commune.logo.name`), so a restore serves a
broken `<img>`/`<link rel="icon">` rather than a dropped reference.

**Why this is recorded rather than fixed here.** Pairing a media snapshot with
a database snapshot correctly needs a decision this file shouldn't make
silently: whether a restore should refuse when the two don't correspond (a
media directory older or newer than the chosen `db-*.sqlite3`), or accept the
mismatch and report it, and how `molecule/restore` should assert either
choice. That is a real piece of design, not a one-line addition to
`polls-backup.sh.j2`.

**Not settled.** Until this is done, an adopting commune's disaster-recovery
story has a gap: instructions to any operator following R-3.12 or §6.5.14 in
the field should say so, and `restore.yml`'s final report should probably say
so too, until the fix lands.

**Settled (2026-09-17).** `polls-backup.sh.j2` now writes `media-<stamp>.tar.gz`
beside `db-<stamp>.sqlite3` in the same run, sharing the timestamp — the
correspondence question above resolves by construction, since the two are
never produced independently: a `db-<stamp>.sqlite3` and its `media-<stamp>.tar.gz`
either both exist (one backup run) or the media side is simply absent (a
snapshot from before this change, or a directory an operator deleted by hand).
`restore.yml` derives the media archive's path from whichever snapshot it is
restoring and, finding no match, restores the database anyway and reports the
gap rather than failing the whole restore — reported, not refused, per the
open question above, on the view that a database back with a stale-but-present
media directory beats no restore at all. Retention and off-host replication
apply to both files unchanged, since `polls-backup.sh.j2`'s retention `find`
now matches either pattern and `rsync` already mirrors the whole backup
directory. `molecule/restore` asserts the round trip with a marker file under
`media/`.

## 19. `announced` became mandatory, reversing item 13's "optional waypoint"

**What changed.** R-3.2 and R-3.10 used to make `announced` an optional
waypoint: `open_poll` accepted either `draft` or `announced` as its source,
so a poll admin who never announced still had their poll open on schedule,
unattended, at `opens_at`. Item 13 recorded the deliberate choice to make
`announced` a real state rather than a boolean flag, precisely so that
choosing it was free of side effects beyond freezing configuration early —
optionality was central to that entry's reasoning and is explicitly what this
item reverses.

**Why.** An unattended `draft → open` transition means nobody ever reviewed
the frozen configuration a poll opens with — the scheduled `open_poll` command
cannot distinguish "deliberately skipped the preview" from "forgot the poll
existed". Requested directly: the scheduled job, and manual opening, should
only ever act on a poll a human deliberately announced.

**What the requirements say now.** R-3.2: `draft → announced → open → closed
→ published`, no `draft → open` edge — announcing is mandatory, not optional.
R-3.10 gained a second guard beyond the existing translation check:
announcing is refused once `opens_at` has already passed, so a stale preview
can never freeze open immediately behind it. R-3.3 already made `opens_at`
freely editable while still `draft`; that is the only recovery path for a
poll admin who missed the window — push `opens_at` forward, then announce —
deliberately with no override mechanism, since R-3.3 already provides one.

**What the code does.** `TRANSITIONS` in `apps/elections/transitions.py` no
longer has a `draft → open` edge; `poll_state_irreversible`
(`elections/migrations/`) drops the matching trigger clause, so a raw SQL
`UPDATE` is refused identically to the application. `opening_blockers` now
requires `state == announced` (blocker `not_announced`, replacing
`not_draft_or_announced`); `announcing_blockers` gained the `opens_at`
guard (blocker `opens_at_not_in_future`). The scheduled `open_poll` command's
selection narrowed from `state IN (draft, announced)` to `state = announced`.
Screen 2's draft-state "ouvrir maintenant" button (bypassing announce) was
removed; only the already-`announced` state offers it now.

**Settled (2026-09-18).**

## 20. The draft-preview share link (R-3.10 bis) is deliberately not frozen

Not a divergence — recorded because it's the obvious question a future
reader would ask, given item 13's neighbouring entry: why does this second
preview mechanism *not* freeze the configuration the way `announced` does?

**Why not.** Freezing would mean either duplicating INV-6's mechanism for a
second, `draft`-only case (exactly what item 13 rejected once already), or
routing the share link through a real state transition — but there is no
state to put a still-secret, not-yet-reviewed poll into that wouldn't also
make it a candidate for the scheduled `open_poll` job or the public listing.
`announced` already exists for "frozen and reviewable"; this feature exists
for the different, narrower case of "let one outside person look at what's
there right now, without either of those consequences."

**What the code does instead.** `Poll.preview_token` is a plain, mutable
field, deliberately outside `FROZEN_CONFIG_FIELDS` — the page it gates
re-renders the *current* draft on every request, exactly like the poll
admin's own internal aperçu, and says plainly that it can change. The
mutability item 13 objected to is accepted here, not engineered around,
because unlike that rejected design this one is never publicly listed: only
someone the admin deliberately handed the link to can see it change.

## 21. R-3.12's images moved from per-option to a shared per-poll library

**Specification, R-3.12 (as first written).** Each option could carry an
extended description with images, one `OptionImage` row per option
(`option-images/<option_id>/<hash>`), addressed in Markdown by the image's
UUID.

**What changed and why.** Two gaps this design left: the poll's own
description (R-3.1) had no equivalent formatting at all, and the same
photograph reused across two options — a common case for a municipal
consultation illustrating one proposed layout from two angles, say — had to
be uploaded twice, as two unrelated rows with two different ids. Both are
requirements gaps, not implementation ones, so R-3.12 itself was rewritten
(cahier-des-charges.md/requirements-en.md, same commit) rather than patched
around: a poll now holds one small image library, uploaded once at the poll
level, and both the poll's own description and every option's extended
description draw on it by a short `image:<n>` reference — sequential per
poll, not the image's UUID, since an operator retyping it while drafting
never has the row open to copy a UUID from.

**What the code does.** `OptionImage` (migration 0008) is replaced outright by
`PollImage` (migration 0011, `elections.PollImage`, FK to `Poll` rather than
`PollOption`, `short_id` assigned sequentially by
`apps.elections.pollimages.add_poll_image`). No migration path for existing
rows: pre-1.0, no deployment had data to carry through. `apps.elections.richtext`
(renamed from `optioncontent`) gained `render_poll_description` alongside the
existing `render_option_details`, both delegating to one private renderer so
the image-resolution/YouTube/Markdown/sanitiser pipeline of §3.1 bis is
defined once.

**Settled (2026-09-19).**

## 22. `PollImage.alt_text` is a default, overridable per reference

**Specification, R-3.12 / §3.1 bis (as first implemented).** `PollImage`
carries an `alt_text` collected at upload, alongside the `![alt](image:<n>)`
Markdown syntax that already names its own alt text inline. Nothing in
`apps.elections.richtext._resolve_image` read the model field: it was used
only to caption the image's own thumbnail in the back-office library panel,
never in a rendered description.

**What changed and why.** As built, the field was write-only for anything
public-facing — an operator had to retype the same wording into every
`![...]()` reference to an image, with no indication the two could drift.
Neither R-3.12 nor §3.1 bis says the field should feed rendering, but
collecting it and then never using it outside the editor screen serves no
purpose either, so this is a gap the specification left implicit rather than
a conflict — closed here rather than left to be rediscovered.

**What the code does.** `![](image:<n>)` — empty brackets — now resolves to
`image.alt_text`; `![texte](image:<n>)` still overrides it for that one
reference, e.g. when the same photograph illustrates two different options
and needs different wording in each. `apps.elections.pollimages` and the
upload form are unchanged. The back-office help text (poll/option
description fields and the images panel) documents the empty-brackets form.

**Settled (2026-09-19).**

## 23. `image:<n>` gained an optional display-size suffix

Not a divergence — a gap neither R-3.12 nor §3.1 bis addressed at all: the
Markdown image reference had no way to influence how large the image renders,
so every embedded image showed at whatever size the uploaded file happened to
be, however that compared to the surrounding text column.

**What the code does.** `image:<n>` now accepts an optional `:small`,
`:medium` or `:large` suffix — `image:<n>:large` — read by
`apps.elections.richtext._IMAGE_REF`/`_resolve_image`. A sized reference is
rendered as a raw `<img class="poll-image--<size>">` rather than through
Markdown's own `![]()` image syntax, since that syntax has no way to carry a
`class`; the three classes (`static/css/app.css`) fix the widths. An
unsuffixed reference is completely unaffected — same output as before this
existed — and a suffix outside the fixed three-value set is not recognised as
a suffix at all, so the whole reference is dropped exactly like a foreign or
nonexistent `short_id`, rather than guessed at or passed through raw.

**Why a fixed three-value enum and not a free-form width/percentage.** The
same reasoning R-3.12's other constraints already follow (§3.1 bis point 3):
an operator with no design background is choosing between "small", "medium"
and "large", not picking pixels, and a fixed, sanitiser-independent set means
the `class` attribute this feature adds to the `img` allow-list can only ever
hold one of three server-chosen strings — never operator-supplied text — so
allowing `class` at all costs nothing security-wise.

**Settled (2026-09-19).** §3.1 bis, the sanitiser's `img` attribute list and
T-79's neighbouring row (new T-86) were updated to describe the suffix; the
back-office help text next to the description/details fields and the images
panel documents it for the operator. No requirements change — display size is
an implementation detail R-3.12 leaves unspecified, not a rule it states.

## 24. A poll opened by hand ahead of `opens_at` opened in the back-office only

**Specification, §4 and item 12 above.** *Ouvrir maintenant* was offered at any
time once `announced`, including ahead of `opens_at`, on the grounds that the
window checks read the clock against `opens_at` and never `state`, so opening
early "admits no vote before the configured instant".

**Why that is wrong.** It is safe but useless, and it misleads: the back-office
and the public site disagreed about the same poll. The dashboard read `open`;
the public listing (`_status_key`, item 14) rightly kept it under "à venir"
until the clock reached `opens_at`, and neither votes nor registrations were
accepted. A poll admin who forces the opening wants the poll open now.

**What the code does.** `_open_poll_locked` sets `opens_at` to the instant of
opening when that instant is earlier than the configured one, and logs both
values in the `POLL_STATE_CHANGED` event (`before.opens_at`, `after.opens_at`).
`opens_at` is an INV-6 field, so this needed a second carve-out beside
`closes_at`: migration 0012 recreates `inv6_poll_config_frozen` to admit a
change of `opens_at` only on the `announced → open` write and only to an
earlier instant, and `Poll.save()` mirrors it. The scheduled command is
unaffected (it selects on `opens_at ≤ now`, so there is nothing to move).

**Settled (2026-09-23).** R-3.4 now lists the two exceptions (both language
files); §4, §5.1's INV-6 and T-67 were updated to match. No reason is required,
unlike the `closes_at` extension: nothing is postponed, and the two dates are
in the audit event.

## 25. Deleting a paper ballot re-opened online voting for nobody who had not registered

**Specification, §6.2 step 6, §6.4 and INV-10.** Keying a paper ballot for an
elector who never registered online creates a bound, `active`, address-less
`Registration` on the `paper` channel, so the channel indicator has a row to
live on. Deleting the ballot clears the indicator to `none` (R-9.4, T-31) and
nothing else. T-31 only covers an elector who *had* registered online and so
still holds a token.

**Why that is wrong.** For an elector who had not, the leftover row is the roll
entry's one non-rejected registration, so the registration form — the only way
to obtain a token — refused them under R-5.9 as a duplicate, with the neutral
message, and logged a duplicate-attempt flag against their own row. R-9.4's
"re-opens online voting" was true in name only. Separately, the cleared row is
on the `none` channel with `email_canonical = ""`, which the INV-10 constraint
(exempt on `paper` only) treated as one shared address: deleting a second paper
ballot in the same poll raised an `IntegrityError`.

**What the code does.** `register` recognises a cleared paper shell (`active`,
channel `none`, blank address) bound to the matched entry and completes it in
place (`_adopt_paper_shell`): declared identity, address and language are
written, the state goes to `pending_email`, `confirmed_at` is cleared and a
token is issued, exactly as for a new registration. It is still one registration
per roll entry (R-5.9, INV-4), the address check (R-5.9, T-17) still applies, and
a live paper ballot — channel `paper` — is still refused and flagged. Migration
`registrations.0002` narrows `uniq_registration_poll_email` to rows with a
non-blank address.

**Settled (2026-09-23).** No requirements change: R-5.9 and R-9.4 are both met.
INV-10 in §5.1 now states the blank-address exemption.

## 26. Sandbox polls became triable through their link, and deletable

**Specification, INV-8, T-15, §6.6 and INV-3.** A sandbox poll was reachable from
nowhere: every public, registration and ballot route 404ed on `is_sandbox`, so
the flag could be set but the poll could never actually be exercised end to end.
No code deleted a poll at all, although §6.5 spoke of deleting a draft; and the
retention purge was the only thing allowed to remove ballots, registrations or
roll entries.

**Why that is wrong.** A rehearsal that cannot be voted on tests nothing, and one
that cannot be cleaned up leaves test electors' identities in the database for
good — the retention purge starts at closure, and a sandbox poll may never close.
Neither is something R-3.7 asks for: it excludes the poll from public listings,
published results and statistics, and says nothing about who may reach it.

**What the code does.** Requirements first: R-3.7 now says a sandbox poll can be
tried end to end through the unguessable link and deleted by its poll admin in any
state, and states outright that this is an exception, for sandbox polls only, to
R-7.2 (no ballot physically deleted) and R-12.3 (no role deletes a registration);
R-3.10 bis no longer redirects a sandbox poll's link once it leaves `draft`, since
there is no public page to redirect to.

- *Reaching it.* The share link (`preview_token`) stays valid in every state and
  serves the poll page. The session stores the presented token, compared with
  the current one on every request, so regenerating or revoking ends the access
  of whoever used the old link. Registration needs that grant; ballot routes
  need it or a valid voter token (`ballots.access` grants on one — the mail is
  opened on any device). Nothing stored identifies a voter (INV-1).
- *Deleting it.* `elections.sandbox.delete_poll` deletes everything but the
  audit log. `AuditEvent.poll` drops its database constraint (`DO_NOTHING`), so
  the events outlive the poll — INV-3 stays absolute for the log. That
  constraint was also the only thing preventing deletion of a real poll, so
  `inv3_poll_no_delete` now does, at the table. The delete triggers of INV-2,
  INV-3, INV-6 and INV-7 each gain a single exemption, `is_sandbox = 1`, which is
  safe because INV-6 freezes the flag once a poll leaves `draft` and a `draft`
  holds no ballot, registration or snapshot.

**Settled (2026-09-23).** Requirements and spec updated (R-3.7, R-3.10 bis, INV-3,
INV-8, §6.6, §11 bis, T-15, T-87–T-90). A tester on a sandbox poll registers
against the real roll and so must be on it; a sandbox-only roll bypass was
rejected because it would test a different path than the one being rehearsed.
Sandbox results are not shown on the public site (R-3.7) and there is no
sandbox-specific results page: the operator reads them on screen 9. (Since
#36 the ordinary results page also answers a browser holding the link.)

## 27. Approving an application onto a cleared paper shell

**Specification, §6.2 steps 5 and 6.** Decision #25 let `register` complete the
cleared shell a deleted paper ballot leaves on a roll entry. It missed the other
way onto an entry: a poll admin approving a `pending_review` application
(a name spelled differently enough to fail the automatic match) binds the entry
by hand, and `approve` refused it under R-5.9 as "already attached to a
registration" — the shell, again, with no elector behind it. R-9.4's promise
failed for exactly the electors whose names the roll matches least well.

**What the code does.** `approve` recognises the same cleared shell
(`_is_cleared_paper_shell`: `active`, channel `none`, blank address) and
retires it (`_retire_paper_shell`) inside its own transaction before binding:
the shell is unbound and set `rejected`, which puts it outside INV-4's partial
unique constraint. The applicant's row is the one that survives, goes to
`pending_email` and gets its token as for any approval. The shell is re-read
under lock and re-checked, so a paper ballot keyed in the meantime — the shell
is then a live `paper` indicator — is still refused. The approval event carries
`after.replaces = registration:<shell id>`, a reference and no personal data
(INV-3). A live paper ballot, or any registration that is not a cleared shell,
is refused as before.

**Why retire rather than adopt in place, as #25 did.** There are two rows here,
and only the applicant's carries an address, a declared identity and a language.
A registration cannot be deleted before closure (INV-2), so the shell cannot
simply be dropped; completing it in place would instead have to retire the
applicant's row, leaving the review queue and the audit trail saying that an
application was rejected when the admin approved it.

**Consequence.** The retired shell stays as a `rejected` row until the retention
purge, and screen 1's live "registered" figure, which counted every row, would
have risen by one for each such approval. It now counts `active` registrations
only — the definition `frozen_counts` already froze at closure, so the figure no
longer drops when the poll closes — which leaves out the shell, ineligible
applicants and registrations still awaiting review or confirmation. The
separate "confirmed" tile, now identical to it, is removed.

**Settled (2026-09-23).** No requirements change: R-5.9 and R-9.4 are both met.
§6.2 step 6 states the exception, T-91 covers it.

## 28. Electors awaiting confirmation: resend, not confirm

**Request.** An operator should be able to see the electors who have not
confirmed their mailbox, to resend the link or to confirm those who should have
received one.

**What the code does.** Screen 4 lists the `pending_email` registrations under
the review queue, and screen 1 counts them (they are outside "registered",
decision #27, but no longer invisible). Each row has a *renvoyer le lien*
action, `services.resend_confirmation`: it mints a new token, replaces
`voter_hash`, mails it after commit and logs `registration_link_resent`
(reference and state only). It refuses any state but `pending_email`, and a
closed window.

**Why replace rather than re-send.** The plaintext token is never stored (§7),
so the first mail cannot be re-sent, only superseded. That is safe exactly while
the registration is `pending_email`: there is no ballot the old token could
reach, so nothing is orphaned (INV-1, INV-5 are untouched). After confirmation
the token is the elector's alone (R-7.6) and the action is refused.

**Why no operator-side confirmation.** R-5.5 has the mailed link confirm the
registration, and R-7.4 has the token travel by mail and nowhere else. An
operator moving a row to `active` by hand would produce a registration that
proves no mailbox and that nobody holds a token for, so the elector could still
not vote online; it would also weaken the guard R-5.12 says the mailbox is. The
useful part of the request is met by resending, and an elector whose address is
wrong or unreachable votes on paper. Correcting an address in place is not
offered: the address is what the elector declared, and INV-10 keys on it.

**Settled (2026-09-23).** No requirements change. §6.5.4 states the screen, T-92
covers it.

## 29. A paper ballot keyed for an unconfirmed registration was not counted

**Found in review.** An elector registers online and never opens the
confirmation mail, then votes on paper at the mairie. Keying binds the paper
channel to the registration already on their roll entry — the one registration
INV-4 allows — which is still `pending_email`. Every participation figure read
`state = active` only, so that live paper ballot was in the closure hash, the
tally and the published list, and missing from `ballots_paper` and
`registered`. The publication then showed six ballots beside counts adding up
to five.

**What the code does.** `registrations.models.PARTICIPATING` is the one
definition the three readers share — `frozen_counts` (§9), the live figures of
R-11.5 and screen 1: `active` rows, plus any non-rejected row carrying a vote.
Screen 4's list of electors awaiting confirmation, and screen 1's count of
them, leave such a row out: they have voted, there is nothing to chase.

**Why not change the registration instead.** Moving it to `active` at keying
would claim a mailbox proof that never happened (R-5.5), and the INV-2 trigger
freezes `state` through the transcription window after `closes_at`, so it
could not be done there anyway. Retiring it and creating a fresh paper
registration would strand the elector's address: the retired row keeps it, and
a later online registration after the paper ballot is deleted (R-9.4) would be
refused as a reused address.

**Open question.** R-5.5 says an unconfirmed registration "carries no ballot …
and is not counted in participation figures"; T-27 repeats the second half.
That holds for the online channel, which is what it was written for. A paper
vote is cast in person against the roll entry and does not depend on the
mailbox, so the code counts it. Whether R-5.5 should say so explicitly is for
the requirements owner.

## 30. An elector listed twice on the roll is flagged, not blocked

**Found in review.** The import collapses rows sharing a normalised name and
date of birth (R-4.6). One person listed under a birth name on one row and a
name in use on another — or with a typo — stays two snapshot entries with two
channel indicators, and nothing stopped an online vote on one and a paper
ballot, or an approved second registration, on the other.

**What the code does.** Screen 5 looks for other entries with the same parsed
date of birth and a forename in common that already carry a vote
(`backoffice.paper.voted_look_alikes`). If there are any, it shows them, and it
records the ballot only once the operator ticks "identité confirmée avec
l'électeur présent" — the R-8.3 procedure for entries the data cannot tell
apart, which already writes `identity_confirmed_at_mairie` to the audit event.
Screen 4 shows, for each entry offered for binding, whether it carries a
registration and whether it has voted; a cleared paper shell (#27) is not
shown as taken.

**Why a warning and not a refusal.** Twins and namesakes born on the same day
exist, and only the person at the counter can tell them apart (R-8.3). A
refusal would turn a rare false alarm into a lost vote; the confirmation puts
the judgement where R-8.3 puts it and leaves a trace. No requirements change.

## 31. Uncountersigned paper entries are published as their own figure

**Request.** When a poll admin closes past outstanding countersignatures
(R-8.7 bis), the entries still awaiting one are left out of the tally, the hash
and the ballot list — but their electors are on the paper channel, so
`ballots_paper` counted them. The published counts then exceeded the ballot
list, with only the override reason to explain it.

**What the code does.** `frozen_counts` publishes `ballots_paper` as the paper
ballots actually counted and adds `paper_uncountersigned`, the entries set
aside. `ballots_online + ballots_paper` is the ballot count, and `registered =
ballots_online + ballots_paper + paper_uncountersigned + non_voters`. Those
electors are not non-voters: they voted, and their ballot was not validated.
The figure is always present in a new publication (zero, usually), and shown on
screens 1 and 9 and the public results page only when non-zero. Counts frozen
before this change keep their stored shape and are not recomputed (T-58).

**Why no INV-1 concern.** The new figure is a bare count of `pending_countersign`
paper ballots. Each hangs off one paper-channel registration (INV-4, INV-5), so
the paper count is a subtraction of two totals, never a join.

**Settled (2026-09-24).** Spec §9 lists the figure. No requirements change:
R-8.7 bis already requires that uncountersigned entries be neither counted nor
dropped in silence.

## 32. A corrected paper ballot is countersigned again

**Found in review.** A correction (R-8.5) carried the previous version's
countersignature over to the new one, which stayed live. On a poll requiring
countersignature (R-8.7), one operator could therefore key a ballot, have it
countersigned, then correct it to any ranking — counted, and shown as validated
by a second operator who never saw that ranking. The before/after audit event
was the only trace.

**What the code does.** On such a poll, `correct_paper` writes the new version
`pending_countersign`, with no countersignature, whatever the previous status.
The corrector is the new version's operator, so `countersign` refuses them;
another operator validates it on screen 7. The audit event records the status
before and after. On a poll without countersignature nothing changes.

**Consequence.** A correction shortly before `paper_entry_deadline` puts the
ballot back in the queue, and closure is refused until it is countersigned or
the poll admin overrides with a reason (R-8.7 bis) — in which case it is
published as uncountersigned (#31). That is the intended cost: the requirement
is that no entry counts without a second operator, and a correction is an
entry.

**Settled (2026-09-24).** No requirements change: this is R-8.7 applied to
corrections.

## 33. The clock refuses, the state admits

**Found in review.** The window checks of §5.1 never read `state`, so that a
scheduled transition running late, twice or not at all cannot admit a write
outside the window. At the closing end that is exactly right. At the opening
end it admitted too much: a `draft` poll, or an `announced` one whose
`open_poll` had not run, accepted a registration posted to its URL once
`opens_at` had passed. With no snapshot to match against, every such
applicant landed in `pending_review`, identity data was collected for a poll
that was not open, and R-3.10 ("neither registration nor voting is offered"
while `announced`; a `draft` "appears on no public page") was not met.

Nothing was gained in exchange. Opening is the transition whose side effects
the write paths depend on — the snapshot every match, approval and paper entry
reads, and the `opening_seed` — so until it runs no vote is possible on either
channel, whatever the clock says. The public page already followed `state` at
this end (`announced` shows as a preview).

**Position.** Time bounds a window; the state admits to it. A ballot or
registration write is accepted only when the poll is `open` **and** the clock
is inside the window for its source. The rule behind §5.1 is kept in the form
its reason actually needs: nothing relies on `state` to *refuse* a write past a
deadline — `closes_at` and `paper_entry_deadline` are still enforced on the
clock alone, so a `close_poll` that runs late still admits nothing late.
Requiring `state = open` can only refuse more, never less, so a late
`open_poll` delays the start of voting and cannot admit anything outside the
window. The `withdrawn` exception of R-3.11 becomes a case of the general rule.

The two ends are asymmetric because the transitions are: closing's side
effects consume the writes (hash, counts), so the state may lag the clock;
opening's side effects enable them, so it may not.

**What the code does.** `elections.windows.check_ballot_window` and
`check_registration_window` refuse unless `state = open`, then check the clock
as before. The INV-2 `INSERT`/`UPDATE` triggers refuse any write to a poll not
`open` (migration 0014), replacing their `withdrawn`-only short-circuit. The
registration page answers 404 for a `draft` poll and shows no form while
registrations are not accepted. Because a missed opening now visibly delays
voting rather than silently doing nothing useful, it is surfaced: the
dashboard flags an `announced` poll past `opens_at` or an `open` poll past
`paper_entry_deadline`, and `/sante` reports `transitions_overdue` for
monitoring.

**Settled (2026-09-24).** No requirements change: R-3.10 already requires it.
§4, §5.1, INV-2, T-52 and T-78 are reworded to match.

## 34. A poll may be closed early, by hand, with a reason

**Decided (2026-09-24).** The poll administrator may close an open poll
before its deadline. The specification used to forbid it, because the window
checks read only the clock and would have gone on admitting ballots after a
hash that did not cover them. Since #33 every write needs `state = open`, so
that objection is gone.

**What the code does.** `close_poll` called before `paper_entry_deadline` is
an early closure. It needs a reason code, like an extension. It brings
`closes_at` (if still in the future) and `paper_entry_deadline` back to the
instant of closure, and logs `poll_closed_early` with both instants and the
reason. The poll's public page shows that event beside any extension. The
countersignature and reconciliation guards are unchanged. The scheduled job
never closes early.

**Requirements.** R-3.4 gains a third exception, in both languages.

## 35. Definitive actions are confirmed on a separate page

**Decided (2026-09-24).** Every definitive action on a poll is confirmed on a
page that restates its consequences before it runs. The actions are
announcing, opening, closing, publishing, withdrawing, extending the closing
date, deleting a sandbox poll, and recording the reconciliation. Before this,
one click acted; sandbox deletion alone had a checkbox.

**What the code does.** The action's form posts to the same screen. Without
`confirmed=1`, the view validates the input and renders
`backoffice/confirm.html`. That page names the action, lists its
consequences computed at that moment, and re-posts the input as hidden
fields with `confirmed=1`, or offers Cancel. Nothing is written on the first
POST. The role and state checks run on both POSTs.

**Requirements.** R-2.4 gains the rule, in both languages.

## 36. A sandbox poll's result is reachable through its link

**Decided (2026-09-24).** Once a sandbox poll is published, its results page,
CSV and JSON answer a browser holding the share link or a voter token of its
own. Before this they 404ed for everyone, while the sandbox poll page, which
reuses the public template, still offered "Voir les résultats": a link to a
404, and no way to try the tally, the publication or the verifier end to end.

**What the code does.** `publicsite.results` looks the poll up in any
`published` poll and refuses it unless `sandbox.may_reach` allows it, the same
gate as the sandbox poll page and ballot routes. A browser without the grant
gets the bare 404 a never-published poll gets. The page carries the rehearsal
notice and its breadcrumb leads to the share link, or to nothing for a
browser holding only a voter token. Nothing lists the poll (INV-8).

**Requirements.** R-3.7 no longer excludes the test poll from "published
results" as such: its result appears on no public page, and "tried end to
end" now includes the published result. Both languages. T-94.

## 37. The verifier reads the publication document, and every method

**Decided (2026-09-24).** §14 had the verifier read "only the published CSV" and
recompute "the Schulze winner". The CSV does not say which method a poll used,
so for a plurality or approval poll the winner check compared the announced
winner with the Schulze one (review note M2). It also carries no option list,
so an option nobody ranked was missing from the verifier's matrix (L5).

**What the code does.** The verifier implements all three methods of R-10.3.
Its preferred input is the JSON publication document, which R-11.2 already
requires and which carries the ballots, the method, the options and every
published value. From the ballots it recomputes the closure hash, the ballot
count, the matrix, the counts, the winner and the tie-break, and checks each
against the value the document states. A physical draw cannot be replayed; the
verifier checks that its order is a draw among exactly the tied options. The
document's layout is fixed in `docs/publication-format.md` and versioned by a
`format_version` member, and the verifier refuses a version it does not know.
The CSV remains a supported input, with the method and the other values supplied
by the caller.

**What it takes on trust.** The method, which decides what the winner should
be. The document states it, and so does the results page, from the same
server. The method is fixed before the poll opens and shown publicly from the
time the poll is announced. The verifier restates the method so the reader can
compare it with what was announced. No requirements change: R-11.4 asks that
anyone can recompute the result "from the published data", which the document
is. §14 and §9 were updated to match.

## 38. A poll requiring reconciliation cannot be closed early

**Found in review (2026-09-24).** #34 lets the poll administrator close an
open poll before its deadline, "the countersignature and reconciliation guards
unchanged". On a poll with `paper_requires_reconciliation`, those two
unchanged rules add up to no early closure at all:
`ballots.services.record_reconciliation` refuses before
`paper_entry_deadline` (#16: a count taken earlier could be made stale by a
paper entry the window still admits), and `transitions.closing_blockers`
refuses closure while `reconciliation_pending`, with no override (R-8.6 offers
none). Screen 2 still offers *Clôturer maintenant*, and the espace mairie
guide says it is available "à tout moment une fois le scrutin ouvert"; on such
a poll it can only be refused.

**Open question.** Either the manual and screen 2 say that early closure is
unavailable when reconciliation is required, or recording the reconciliation
follows the early-closure instant: an early closure moves
`paper_entry_deadline` to the moment of closing, so the count could be taken
at that moment, in the same confirmed action. The second changes what R-8.6's
record attests to, and is for the requirements owner to decide.

