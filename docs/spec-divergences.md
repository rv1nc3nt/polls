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
