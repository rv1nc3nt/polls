# SPDX-License-Identifier: 0BSD
"""The one module that assigns ``Poll.state`` (§5.1).

No view, no management command and no service anywhere else mutates it; a test
greps the tree to assert that (``tests/integration/test_single_transition.py``).
The transition table is here, the guards are here, and the audit event is
written in the same transaction as the state write.

``draft → open → closed → published``, irreversible (R-3.2).
"""

from __future__ import annotations

from datetime import datetime

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.audit.models import Action, Reason
from apps.ballots.models import BallotStatus
from apps.core.crypto import new_opening_seed
from apps.core.models import User

from .models import Poll, PollState, RollEntry, WorkingRollEntry

TRANSITIONS: dict[str, str] = {
    PollState.DRAFT: PollState.OPEN,
    PollState.OPEN: PollState.CLOSED,
    PollState.CLOSED: PollState.PUBLISHED,
}


class TransitionRefused(Exception):
    """A guard refused. The caller reports it loudly: the back-office shows it,
    a scheduled command logs the blocker and exits non-zero (§4)."""

    def __init__(self, message: str, blockers: list[str] | None = None) -> None:
        super().__init__(message)
        self.blockers = blockers or []


def opening_blockers(poll: Poll) -> list[str]:
    """Why ``open_poll`` would refuse (§4, T-53).

    Named on the dashboard while the poll is still in ``draft``, so a gap is
    visible before the opening hour rather than at it. A silent non-opening is
    the worst outcome available here.
    """
    blockers: list[str] = []
    if poll.state != PollState.DRAFT:
        blockers.append("not_draft")
    if poll.options.count() < 2:
        blockers.append("fewer_than_two_options")
    blockers += [f"missing_translation:{gap}" for gap in poll.missing_translations()]
    if not WorkingRollEntry.objects.exists():
        blockers.append("no_roll_to_snapshot")
    return blockers


def closing_blockers(poll: Poll) -> list[str]:
    """Why ``close_poll`` would refuse (§4, §9, T-57).

    Silently dropping uncountersigned ballots at closure is not acceptable, so
    the transition stops and the dashboard shows the count. This is safe rather
    than dangerous: the window checks already refuse every ballot write past
    ``paper_entry_deadline`` regardless of state, so the poll is closed in
    substance while the state field waits.
    """
    blockers: list[str] = []
    if poll.state != PollState.OPEN:
        blockers.append("not_open")
    pending = poll.ballots.filter(status=BallotStatus.PENDING_COUNTERSIGN).count()
    if pending:
        blockers.append(f"pending_countersign:{pending}")
    return blockers


def open_poll(poll: Poll, actor: User | None = None, now: datetime | None = None) -> Poll:
    """``draft → open``.

    The transition with side effects: the roll snapshot (§6.1) and
    ``opening_seed`` are written in the same transaction as the state, so two
    concurrent runs cannot produce two snapshots or two seeds (T-51). Selection
    by the caller is state-based — ``state = draft AND opens_at ≤ now`` — so a
    host that was down opens the poll late rather than never.
    """
    try:
        return _open_poll_locked(poll, actor, now)
    except TransitionRefused as refusal:
        # Recorded *outside* the transaction that just rolled back: an event
        # written inside it would vanish with the rollback, and §4 requires the
        # refusal to be loud — logged, and named on the dashboard (T-53).
        audit.record(
            action=Action.JOB_REFUSED,
            poll=poll,
            actor=actor,
            object_ref=audit.ref(poll),
            after={"command": "open_poll", "blockers": refusal.blockers},
        )
        raise


@transaction.atomic
def _open_poll_locked(poll: Poll, actor: User | None, now: datetime | None) -> Poll:
    poll = Poll.objects.select_for_update().get(pk=poll.pk)
    blockers = opening_blockers(poll)
    if blockers:
        raise TransitionRefused(_("Ouverture refusée : configuration incomplète."), blockers)

    RollEntry.objects.bulk_create(
        RollEntry(poll=poll, last_name=e.last_name, first_names=e.first_names, nne=e.nne)
        for e in WorkingRollEntry.objects.all().iterator()
    )
    snapshot_size = poll.roll_entries.count()
    poll.opening_seed = new_opening_seed()
    poll.state = PollState.OPEN
    poll.save(update_fields=["opening_seed", "state"])

    audit.record(
        action=Action.ROLL_SNAPSHOT_TAKEN,
        poll=poll,
        actor=actor,
        object_ref=audit.ref(poll),
        after={"row_count": snapshot_size},
    )
    audit.record(
        action=Action.POLL_STATE_CHANGED,
        poll=poll,
        actor=actor,
        object_ref=audit.ref(poll),
        before={"state": PollState.DRAFT},
        after={"state": PollState.OPEN, "opened_at": (now or timezone.now()).isoformat()},
    )
    return poll


def close_poll(
    poll: Poll,
    actor: User | None = None,
    override_reason: Reason | str = "",
    now: datetime | None = None,
) -> Poll:
    """``open → closed``.

    Computes ``closure_hash`` over the live ballot set and freezes the
    participation counts of §9 — both on entry, never re-derived later, since
    the registrations the counts read are deleted by the retention job (T-58).
    The tally is deliberately not run here: it is a pure function that gains
    nothing from running early, and a ``physical`` tie-break stops for a human
    in any case (§4).

    ``override_reason`` is the poll admin's mandatory code for closing with
    ``pending_countersign`` ballots outstanding; it is logged and appears in the
    publication (T-19, T-32). It cannot be supplied by a scheduled command.
    """
    try:
        return _close_poll_locked(poll, actor, override_reason, now)
    except TransitionRefused as refusal:
        # As in open_poll: the refusal is logged after the rollback, or it is
        # not logged at all (§4).
        audit.record(
            action=Action.JOB_REFUSED,
            poll=poll,
            actor=actor,
            object_ref=audit.ref(poll),
            after={"command": "close_poll", "blockers": refusal.blockers},
        )
        raise


@transaction.atomic
def _close_poll_locked(
    poll: Poll, actor: User | None, override_reason: Reason | str, now: datetime | None
) -> Poll:
    from .closure import compute_closure  # local: closure imports the tally

    poll = Poll.objects.select_for_update().get(pk=poll.pk)
    blockers = closing_blockers(poll)
    overridable = all(b.startswith("pending_countersign:") for b in blockers)
    if blockers and not (override_reason and overridable):
        raise TransitionRefused(_("Clôture refusée."), blockers)

    if blockers:
        audit.record(
            action=Action.CLOSURE_OVERRIDE,
            poll=poll,
            actor=actor,
            object_ref=audit.ref(poll),
            after={"blockers": blockers},
            reason=override_reason,
        )
        poll.closure_override_reason = str(override_reason)

    closure = compute_closure(poll)
    poll.closure_hash = closure.closure_hash
    poll.frozen_counts = closure.counts
    poll.closed_at = now or timezone.now()
    poll.state = PollState.CLOSED
    poll.save(
        update_fields=[
            "closure_hash",
            "frozen_counts",
            "closed_at",
            "state",
            "closure_override_reason",
        ]
    )
    audit.record(
        action=Action.POLL_STATE_CHANGED,
        poll=poll,
        actor=actor,
        object_ref=audit.ref(poll),
        before={"state": PollState.OPEN},
        after={
            "state": PollState.CLOSED,
            "closure_hash": closure.closure_hash.hex(),
            "counts": closure.counts,
        },
    )
    return poll


@transaction.atomic
def publish_poll(poll: Poll, actor: User) -> Poll:
    """``closed → published``. The artefacts of §9 become public."""
    poll = Poll.objects.select_for_update().get(pk=poll.pk)
    if poll.state != PollState.CLOSED:
        raise TransitionRefused(_("Seul un scrutin clos peut être publié."), ["not_closed"])
    if poll.closure_hash is None:
        raise TransitionRefused(_("Aucune empreinte de clôture."), ["no_closure_hash"])
    poll.state = PollState.PUBLISHED
    poll.save(update_fields=["state"])
    audit.record(
        action=Action.RESULTS_PUBLISHED,
        poll=poll,
        actor=actor,
        object_ref=audit.ref(poll),
        before={"state": PollState.CLOSED},
        after={"state": PollState.PUBLISHED},
    )
    return poll


@transaction.atomic
def extend_closes_at(
    poll: Poll, new_closes_at: datetime, actor: User, reason: Reason | str
) -> Poll:
    """R-3.4: permitted only while ``open``, only to a later instant, logged
    with a reason and displayed publicly (T-5).

    ``paper_entry_deadline`` moves with it, preserving the configured window
    length (§4).
    """
    poll = Poll.objects.select_for_update().get(pk=poll.pk)
    if poll.state != PollState.OPEN:
        raise TransitionRefused(_("Report possible uniquement sur un scrutin ouvert."))
    if new_closes_at <= poll.closes_at:
        raise TransitionRefused(_("La nouvelle date doit être postérieure."))

    window = poll.paper_entry_deadline - poll.closes_at
    before = {
        "closes_at": poll.closes_at.isoformat(),
        "paper_entry_deadline": poll.paper_entry_deadline.isoformat(),
    }
    poll.closes_at = new_closes_at
    poll.paper_entry_deadline = new_closes_at + window
    poll.save(update_fields=["closes_at", "paper_entry_deadline"])
    audit.record(
        action=Action.POLL_CLOSES_AT_EXTENDED,
        poll=poll,
        actor=actor,
        object_ref=audit.ref(poll),
        before=before,
        after={
            "closes_at": poll.closes_at.isoformat(),
            "paper_entry_deadline": poll.paper_entry_deadline.isoformat(),
        },
        reason=reason,
    )
    return poll
