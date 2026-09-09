# Divergences from the specification

Per §0 of `spec-plateforme-vote.md`, a divergence between the implementation
specification and the functional requirements it restates is resolved in favour
of the requirements, and the specification corrected. This file records where the
**code** departs from the specification, so a reviewer can settle each one rather
than discover it.

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

**To settle:** amend §11's two trigger sentences to say `closed` or
`published`. The alternative — anchoring retention on publication — contradicts
§11's own reasoning and T-58.

## 2. Tracking code in the registration email (R-5.6)

Already flagged by §6.2 step 7 of the specification itself, repeated here
because it is a choice the code makes. The confirmation email carries **no**
tracking code: the code is issued at cast (§6.3) and on the paper receipt
(§6.4). Putting one on a `Registration` row and a `Ballot` row is a join in all
but name and would destroy INV-1 and INV-5, and T-25 asserts no value whatever
is common to the two rows.

If R-5.6 is read as requiring the code in the registration email, the safe
implementation named by §6.2 is a value derived from the token and stored
nowhere; INV-11 would then need rewording to tolerate a derived value that
cannot be re-rolled on collision.

## 3. Plurality with a tied first group

**Specification, §8.2** defines plurality as the count of first preferences,
without saying what a first *group* holding several options means — possible
only where `allow_ties_in_ballot` is set on a `plurality` poll.

**What the code does.** Each option in the first group receives one count
(`apps/tally/methods.py`). The configuration that permits it is a
misconfiguration for the back-office to warn about (§6.5 screen 2), not
something to resolve silently in the tally.

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

**To settle:** amend §5.1's "no `Registration` write after `closes_at`" to
carry the same paper-channel carve-out the ballot window has, or state that the
channel indicator for the paper channel is governed by `paper_entry_deadline`.

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

**To settle:** amend R-9.3 and T-8. Either drop the override (recording that a
paper ballot cannot displace an anonymous online one), or, if an in-person
change path is wanted for `allow_ballot_modification`-off polls, specify it as
*the elector presents their tracking code* and the paper ballot is keyed as a
new version of that ballot chain — the one handle that exists.
