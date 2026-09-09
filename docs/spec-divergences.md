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

## 5. R-9.3 override records the paper ballot without displacing the online one

**Specification, §6.4 / R-9.3, T-8.** Where an elector has already voted online,
the operator may key a paper ballot after an express confirmation and a
mandatory reason, "both being recorded". The specification does not say what
becomes of the online ballot, and INV-5 allows only one live ballot per voter
across both channels.

**What the code does.** The override proceeds: the paper ballot is written with
status `not_in_force_collision` (a `BallotStatus` value added for this), with
its `PaperBallotLink` for traceability and later deletion-on-request
(R-8.2 bis), but it is excluded from the live set — so the tally, closure hash
and published CSV are unchanged, and `Registration.channel` stays `online`. The
online ballot remains the vote that counts. `Action.CHANNEL_COLLISION_OVERRIDE`
is logged with the reason code.

The online ballot is not superseded because §7 makes it unlocatable from the
registration: the operator holds a roll entry, not the token, and no server-side
path maps a registration to its ballot. Writing the paper ballot `live` instead
would leave two live ballots for one voter and break "live set = tally set".

**To settle:** record in §6.4 that a collision-override paper entry is filed
not-in-force and that R-9.3's "may proceed" means the entry is made and logged,
not that it replaces the online ballot; the preferred resolution remains the
one R-9.3 already names — the elector modifies their own ballot online.
