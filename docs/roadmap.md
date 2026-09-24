<!-- SPDX-License-Identifier: 0BSD -->

# Roadmap

Changes agreed in principle but deferred to a future release. Nothing here is
implemented. An entry that is taken up moves to the decision log (if it departs
from the specification) or into the requirements and the specification.

## A distinct state for the paper-keying stretch

**Proposal.** Split today's `open` in two, so the lifecycle reads
`draft → announced → open → voting_closed → closed → published` (names to be
settled in French first): `open` while online voting runs, `voting_closed`
from `closes_at` to `paper_entry_deadline`, when only paper ballots may still
be keyed and countersigned (§6.4), then `closed`.

**Why.** Today the poll stays `open` for the whole keying stretch and the
sub-phase is derived from the clock alone (`windows.online_voting_closed`).
The public page and the dashboard both have to reconstruct it; the audit log
records no event at the moment online voting stops; and an operator reading
the raw state sees `open` when no elector can vote any more.

**What it would not change.** Decision log #33 still holds: the clock refuses,
the state admits. The scheduled job may run late or not at all, so online
writes past `closes_at` must still be refused on the clock even while the
state reads `open`. The new state gains clarity and an audit event; it does
not replace a single clock check. `online_voting_closed` keeps its clock
fallback for the same reason.

**Scope — significant, which is why it is deferred.**

- **Requirements:** R-3.2 (the ordered lifecycle), R-3.4 (extension is
  allowed only while `open`; early closure from either state), R-3.11
  (`withdrawn` reachable from the new state too). Both requirement files,
  same commit.
- **Specification:** §4 state machine and its transition table, §5.1 / INV-2,
  §6.4, and the acceptance tests on transitions and windows.
- **Database:** a migration for the new choice, and the triggers that read
  `state = 'open'` — INV-2 (0014: paper writes admitted in both states,
  online in `open` only), INV-3 / INV-6 and the irreversibility trigger
  (0006, 0007, 0009) which enumerate the allowed state moves.
- **Code:** `PollState`, a new transition (`end_online_voting`) in
  `transitions.py` with its scheduled command and `overdue_transition` /
  `/sante` entry; `windows._require_open` split by source; `close_poll`,
  `is_early_closure`, `extend_closes_at`, withdrawal blockers;
  `ballots/services.py`, `send_reminders`, the public site and dashboard
  (`online_voting_closed` callers); a new audit `Reason`/event type.
- **Tests:** about a dozen modules reference `PollState.OPEN`.
- **Operators:** `docs/manuel/`, the `en` catalogue.

The closure hash, canonical serialisation and the Rust verifier are
unaffected: they depend on ballots, not on the state name.
