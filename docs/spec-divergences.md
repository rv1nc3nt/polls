# Divergences from the specification

Per §0 of `spec-plateforme-vote.md`, a divergence between the implementation
specification and the functional requirements it restates is resolved in favour
of the requirements, and the specification corrected. This file records where the
**code** departs from the specification, so a reviewer can settle each one rather
than discover it.

Items 1–6 were settled on 2026-09-09 by amending `spec-plateforme-vote.md` and,
where noted, the functional requirements (`cahier-des-charges.md` /
`requirements-en.md`). Each keeps its context and carries the resolution
inline.

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
`Commune.current()` reads it) carrying `name`, `data_protection_referent` and
`data_protection_contact`. The first-run wizard (screen 11) creates it in the
same transaction as the initial `commune_admin` account, so the two never
exist apart. A context processor (`apps.core.context.commune`) puts it on every
template; `base.html` uses `name` for the site title and the registration
privacy notice uses the referent fields (R-13.1, R-13.2), each with a generic
fallback for a not-yet-installed instance.

**Why a model and not settings.** R-13.2's referent is operator-editable
configuration an adopting commune sets once, at install, without touching the
source or the environment — which is the whole point of the wizard existing
(§6.5.11, §14). Settings would push it back into deployment. R-1.3 (single
commune, one instance) is what makes a one-row model the right shape rather
than a tenant table.

**Not settled by amending the spec.** This is additive — it implements
§6.5.11 rather than contradicting anything — so §3 should gain a `Commune`
entry and §13 item 4 should point at it. Recorded here until that edit is made.

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

**Not yet settled.** Either §3.8/T-23 should be reworded to say labels are
fixed at `draft` exit (the safer reading — a frozen label cannot drift from the
ballot a voter saw), or the option `UPDATE` trigger should admit a
`label_i18n`-only change with a matching screen-2 action. The first is the
smaller change and matches the current code; recorded here until the spec edit
is made.

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
