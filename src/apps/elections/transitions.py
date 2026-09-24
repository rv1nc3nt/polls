# SPDX-License-Identifier: 0BSD
"""The one module that assigns ``Poll.state`` (§5.1).

No view, no management command and no service anywhere else mutates it; a test
greps the tree to assert that (``tests/integration/test_single_transition_point.py``).
The transition table is here, the guards are here, and the audit event is
written in the same transaction as the state write.

``draft → announced → open → closed → published``, irreversible (R-3.2).
``announced`` is a mandatory waypoint (R-3.10): ``open_poll`` only ever
accepts ``announced`` as its source, so a poll nobody has reviewed by
announcing it can never open, scheduled or by hand. A fifth, terminal state,
``withdrawn``, branches off ``announced``, ``open``, ``closed`` or
``published`` through ``withdraw_poll`` (R-3.11) and joins nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.audit.models import Action, Reason
from apps.ballots.models import BallotStatus, ReconciliationRecord
from apps.core.crypto import new_opening_seed
from apps.core.models import User

from .models import Poll, PollState, RollEntry, WorkingRollEntry
from .windows import online_voting_closed

TRANSITIONS: dict[str, tuple[str, ...]] = {
    PollState.DRAFT: (PollState.ANNOUNCED,),
    PollState.ANNOUNCED: (PollState.OPEN, PollState.WITHDRAWN),
    PollState.OPEN: (PollState.CLOSED, PollState.WITHDRAWN),
    PollState.CLOSED: (PollState.PUBLISHED, PollState.WITHDRAWN),
    PollState.PUBLISHED: (PollState.WITHDRAWN,),
}


class TransitionRefused(Exception):
    """A guard refused. The caller reports it loudly: the back-office shows it,
    a scheduled command logs the blocker and exits non-zero (§4)."""

    def __init__(self, message: str, blockers: list[str] | None = None) -> None:
        super().__init__(message)
        self.blockers = blockers or []


def announcing_blockers(poll: Poll, now: datetime | None = None) -> list[str]:
    """Why ``announce_poll`` would refuse (R-3.10).

    Lighter than ``opening_blockers`` in one respect only: a preview needs no
    roll snapshot, since none is taken until the poll actually opens (§6.1).
    It does need a complete configuration, same as opening — R-3.10 requires
    it, because announcing freezes the configuration exactly as opening does
    (R-3.3) and the public preview it produces cannot show a translation gap
    that would fall back silently for a viewer who never sees ``draft``.
    Fewer than two propositions would not be a preview of anything either, so
    that alone still blocks it too.

    ``opens_at`` must still be in the future: since ``announced`` is now the
    only door to ``open`` (R-3.2), announcing a poll whose opening hour has
    already passed would freeze a public preview only to open immediately
    behind it, defeating the review this step exists to provide. The recovery
    is an ordinary draft edit — push ``opens_at`` forward (R-3.3) — not an
    override, since R-3.3 already grants one.
    """
    blockers: list[str] = []
    if poll.state != PollState.DRAFT:
        blockers.append("not_draft")
    if poll.opens_at <= (now or timezone.now()):
        blockers.append("opens_at_not_in_future")
    if poll.options.count() < 2:
        blockers.append("fewer_than_two_options")
    blockers += [f"missing_translation:{gap}" for gap in poll.missing_translations()]
    return blockers


def opening_blockers(poll: Poll) -> list[str]:
    """Why ``open_poll`` would refuse (§4, T-53).

    Named on the dashboard while the poll is still ``announced``, so a gap is
    visible before the opening hour rather than at it. A silent non-opening is
    the worst outcome available here. The translation and option checks below
    are in practice redundant once a poll has actually been announced —
    ``announcing_blockers`` already required them, and config is frozen from
    that point on (R-3.3) — but stay, defensively, in case a poll somehow
    reaches here without having passed through ``announce_poll``.
    """
    blockers: list[str] = []
    if poll.state != PollState.ANNOUNCED:
        blockers.append("not_announced")
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

    ``reconciliation_pending`` (R-8.6) is never overridable, unlike
    ``pending_countersign`` — the requirements give ``close_poll`` a mandatory-
    reason escape hatch for an outstanding countersignature (R-8.7 bis) but
    none for a missing reconciliation, so ``_close_poll_locked``'s
    ``overridable`` check, which accepts only ``pending_countersign:`` blockers,
    already refuses this one unconditionally without any change there.
    """
    blockers: list[str] = []
    if poll.state != PollState.OPEN:
        blockers.append("not_open")
    pending = poll.ballots.filter(status=BallotStatus.PENDING_COUNTERSIGN).count()
    if pending:
        blockers.append(f"pending_countersign:{pending}")
    if (
        poll.paper_requires_reconciliation
        and not ReconciliationRecord.objects.filter(poll=poll).exists()
    ):
        blockers.append("reconciliation_pending")
    return blockers


#: How long a scheduled transition may lag its instant before it is reported
#: overdue. Several runs of a job that fires every few minutes
#: (``polls_job_interval_minutes``, 5 by default) plus slack for a slow host.
OVERDUE_AFTER = timedelta(minutes=30)


def overdue_transition(poll: Poll, now: datetime | None = None) -> str | None:
    """The scheduled transition that should have moved ``poll`` by now, if any.

    ``"open_poll"`` for an ``announced`` poll past ``opens_at``,
    ``"close_poll"`` for an ``open`` poll past ``paper_entry_deadline``, each
    by more than ``OVERDUE_AFTER``. The window checks require ``open``
    (decision log #33), so a missed opening delays voting and must be noticed:
    a job that refuses says so loudly (``JOB_REFUSED``), but one that never
    ran is otherwise silent. A missed closing admits nothing late — the clock
    alone refuses — but still holds up the closure hash and publication.
    """
    now = now or timezone.now()
    if poll.state == PollState.ANNOUNCED and now >= poll.opens_at + OVERDUE_AFTER:
        return "open_poll"
    if poll.state == PollState.OPEN and now >= poll.paper_entry_deadline + OVERDUE_AFTER:
        return "close_poll"
    return None


def transitions_overdue(now: datetime | None = None) -> bool:
    """Whether any poll has an ``overdue_transition`` — the ``/sante`` flag
    monitoring alerts on (§14). Sandbox polls included: they run on the same
    scheduler, so a stuck one is the same fault."""
    threshold = (now or timezone.now()) - OVERDUE_AFTER
    return Poll.objects.filter(
        Q(state=PollState.ANNOUNCED, opens_at__lte=threshold)
        | Q(state=PollState.OPEN, paper_entry_deadline__lte=threshold)
    ).exists()


def _run_transition(
    command: str, locked: Callable[..., Poll], poll: Poll, actor: User | None, *rest: object
) -> Poll:
    """Call one ``_x_poll_locked``, logging a refusal after its rollback.

    An audit event written inside a transaction that then raises is rolled
    back with it, so §4's "the refusal is loud" cannot be satisfied from
    inside ``locked`` itself — every one of the four callers below needed
    this exact shape, differing only in ``command`` and the extra positional
    arguments ``locked`` takes.
    """
    try:
        return locked(poll, actor, *rest)
    except TransitionRefused as refusal:
        audit.record(
            action=Action.JOB_REFUSED,
            poll=poll,
            actor=actor,
            object_ref=audit.ref(poll),
            after={"command": command, "blockers": refusal.blockers},
        )
        raise


def announce_poll(poll: Poll, actor: User | None = None, now: datetime | None = None) -> Poll:
    """``draft → announced`` (R-3.10).

    Manual only, from screen 2 (R-2.1) — nothing schedules it, since nothing
    about *when* a poll should become an early preview follows from a
    configured instant the way opening and closing do. Mandatory, though:
    ``open_poll`` only ever accepts ``announced`` as its source, so a poll
    admin who wants their poll to open at all must call this first. Config
    freezes the moment this runs, same as opening does — ``Poll.save()`` and
    the INV-6 trigger both key off ``state != draft``, so a poll past this
    point cannot change under a viewer's eyes.
    """
    return _run_transition("announce_poll", _announce_poll_locked, poll, actor, now)


@transaction.atomic
def _announce_poll_locked(poll: Poll, actor: User | None, now: datetime | None) -> Poll:
    poll = Poll.objects.select_for_update().get(pk=poll.pk)
    blockers = announcing_blockers(poll, now)
    if blockers:
        raise TransitionRefused(_("Annonce refusée : configuration incomplète."), blockers)

    poll.state = PollState.ANNOUNCED
    poll.save(update_fields=["state"])
    audit.record(
        action=Action.POLL_STATE_CHANGED,
        poll=poll,
        actor=actor,
        object_ref=audit.ref(poll),
        before={"state": PollState.DRAFT},
        after={"state": PollState.ANNOUNCED},
    )
    return poll


def open_poll(poll: Poll, actor: User | None = None, now: datetime | None = None) -> Poll:
    """``announced → open``.

    The transition with side effects: the roll snapshot (§6.1) and
    ``opening_seed`` are written in the same transaction as the state, so two
    concurrent runs cannot produce two snapshots or two seeds (T-51). Source
    state is always ``announced`` (R-3.2, R-3.10) — a poll nobody has
    reviewed by announcing it cannot open, scheduled or by hand. Two callers:
    the scheduled ``open_poll`` command, selecting on ``state = announced AND
    opens_at ≤ now`` so a host that was down opens the poll late rather than
    never; and the poll admin, by hand, from screen 2 (R-2.1), at any time.

    A manual opening ahead of ``opens_at`` pulls ``opens_at`` back to the
    instant of opening (R-3.4, T-67). The window checks of §5.1 gate voting
    on the clock against ``opens_at`` as well as on ``state``, so leaving it
    in place would have produced a poll that reads ``open`` in the back-office
    while the public site still says it has not started. The INV-6 trigger
    admits exactly this write and no other change to ``opens_at``; the
    scheduled command never triggers it, since it selects on ``opens_at ≤
    now``.
    """
    return _run_transition("open_poll", _open_poll_locked, poll, actor, now)


@transaction.atomic
def _open_poll_locked(poll: Poll, actor: User | None, now: datetime | None) -> Poll:
    poll = Poll.objects.select_for_update().get(pk=poll.pk)
    blockers = opening_blockers(poll)
    if blockers:
        raise TransitionRefused(_("Ouverture refusée : configuration incomplète."), blockers)

    previous_state = poll.state  # always announced (R-3.2, R-3.10) — kept for the audit event below
    opened_at = now or timezone.now()
    planned_opens_at = poll.opens_at
    opened_early = opened_at < planned_opens_at
    RollEntry.objects.bulk_create(
        RollEntry(
            poll=poll,
            birth_name=e.birth_name,
            usual_name=e.usual_name,
            first_names=e.first_names,
            date_of_birth=e.date_of_birth,
            date_of_birth_parsed=e.date_of_birth_parsed,
            date_uncertain=e.date_uncertain,
            list_types=e.list_types,
        )
        for e in WorkingRollEntry.objects.all().iterator()
    )
    snapshot_size = poll.roll_entries.count()
    poll.opening_seed = new_opening_seed()
    poll.state = PollState.OPEN
    update_fields = ["opening_seed", "state"]
    if opened_early:
        poll.opens_at = opened_at
        update_fields.append("opens_at")
    poll.save(update_fields=update_fields)

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
        before={
            "state": previous_state,
            **({"opens_at": planned_opens_at.isoformat()} if opened_early else {}),
        },
        after={
            "state": PollState.OPEN,
            "opened_at": opened_at.isoformat(),
            **({"opens_at": poll.opens_at.isoformat()} if opened_early else {}),
        },
    )
    return poll


def close_poll(
    poll: Poll,
    actor: User | None = None,
    override_reason: Reason | str = "",
    now: datetime | None = None,
    early_reason: Reason | str = "",
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
    publication (T-19, T-32). It cannot be supplied by a scheduled command — it
    is exactly the parameter the poll admin's manual trigger on screen 2
    exists to supply (R-2.1).

    Called before ``paper_entry_deadline`` this is an **early closure**
    (R-3.4, decision log #34), the mirror of an early opening: ``early_reason``
    is then mandatory, and ``closes_at`` (if still ahead) and
    ``paper_entry_deadline`` are brought back to the instant of closure, logged
    as ``POLL_CLOSED_EARLY`` with both instants and shown on the public page.
    Nothing admitted after that instant can exist, since every write requires
    ``state = open`` (decision log #33), so the hash and counts cover exactly
    what the window admitted. The scheduled command selects on
    ``paper_entry_deadline ≤ now`` and so never closes early (T-68).
    """
    return _run_transition(
        "close_poll", _close_poll_locked, poll, actor, override_reason, now, early_reason
    )


@transaction.atomic
def _close_poll_locked(
    poll: Poll,
    actor: User | None,
    override_reason: Reason | str,
    now: datetime | None,
    early_reason: Reason | str,
) -> Poll:
    from .closure import compute_closure  # local: closure imports the tally

    poll = Poll.objects.select_for_update().get(pk=poll.pk)
    closed_at = now or timezone.now()
    early = poll.state == PollState.OPEN and closed_at < poll.paper_entry_deadline
    blockers = closing_blockers(poll)
    overridable = all(b.startswith("pending_countersign:") for b in blockers)
    if blockers and not (override_reason and overridable):
        raise TransitionRefused(_("Clôture refusée."), blockers)
    if early and not early_reason:
        raise TransitionRefused(
            _("Une clôture anticipée exige un motif."), ["early_closure_reason_required"]
        )

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
    poll.closed_at = closed_at
    poll.state = PollState.CLOSED
    update_fields = [
        "closure_hash",
        "frozen_counts",
        "closed_at",
        "state",
        "closure_override_reason",
    ]
    if early:
        # R-3.4: the dates published with the poll say when it actually
        # closed. ``closes_at`` stays put if online voting had already stopped
        # by the clock, which is where it really stopped.
        planned = {
            "closes_at": poll.closes_at.isoformat(),
            "paper_entry_deadline": poll.paper_entry_deadline.isoformat(),
        }
        poll.closes_at = min(poll.closes_at, closed_at)
        poll.paper_entry_deadline = closed_at
        update_fields += ["closes_at", "paper_entry_deadline"]
    poll.save(update_fields=update_fields)
    if early:
        audit.record(
            action=Action.POLL_CLOSED_EARLY,
            poll=poll,
            actor=actor,
            object_ref=audit.ref(poll),
            before=planned,
            after={
                "closes_at": poll.closes_at.isoformat(),
                "paper_entry_deadline": poll.paper_entry_deadline.isoformat(),
            },
            reason=early_reason,
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
    """``closed → published``. The artefacts of §9 become public.

    Refused while a ``physical`` tie-break is unresolved (§8.3): the tally
    reports the tie and stops for a human, and there is no winner to publish
    until the poll admin records the draw on screen 9. The tally itself is a
    pure function of the live set (§8) and is logged here, at the instant its
    derivation is frozen into the public record, rather than on every screen
    view.
    """
    from .closure import tallied, unresolved_physical_tiebreak  # local: closure imports the tally

    poll = Poll.objects.select_for_update().get(pk=poll.pk)
    if poll.state != PollState.CLOSED:
        raise TransitionRefused(_("Seul un scrutin clos peut être publié."), ["not_closed"])
    if poll.closure_hash is None:
        raise TransitionRefused(_("Aucune empreinte de clôture."), ["no_closure_hash"])
    if unresolved_physical_tiebreak(poll):
        raise TransitionRefused(
            _("Départage par tirage au sort physique non saisi."), ["tiebreak_pending"]
        )

    _ballots, _options, result = tallied(poll)
    audit.record(
        action=Action.TALLY_RUN,
        poll=poll,
        actor=actor,
        object_ref=audit.ref(poll),
        after={
            "method": poll.tally_method,
            "method_version": result.method_version,
            "ballot_count": result.ballot_count,
            "winner": result.winner,
            "tied": list(result.tied),
        },
    )

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

    ``state == open`` alone is not the guard: it also covers the whole
    paper-keying stretch after ``closes_at`` (§6.4), and extending from there
    would push ``closes_at`` back into the future and reopen online voting
    that had already, actually, stopped — not a "postponement" of anything,
    since there is nothing left running to postpone. So the clock is checked
    too, the same gate ``apps.elections.windows.online_voting_closed`` uses
    for the dashboard and the public page's display (§5.1): once it is true
    here, this function refuses exactly as it would in any other closed
    state, not just once the scheduled ``close_poll`` catches up.

    ``paper_entry_deadline`` moves with it, preserving the configured window
    length (§4).
    """
    poll = Poll.objects.select_for_update().get(pk=poll.pk)
    if poll.state != PollState.OPEN:
        raise TransitionRefused(_("Report possible uniquement sur un scrutin ouvert."))
    if online_voting_closed(poll):
        raise TransitionRefused(
            _("Le vote en ligne est déjà clos ; la date de clôture ne peut plus être reportée.")
        )
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


def withdrawing_blockers(poll: Poll, reason: Reason | str) -> list[str]:
    """Why ``withdraw_poll`` would refuse (R-3.11).

    Shorter than the other guards: nothing about configuration or the roll
    bears on a poll whose only remaining business is to stop being shown.
    Just the source state — ``announced``, ``open``, ``closed`` or
    ``published``, never ``draft``, which has *delete* for that — and the
    reason, mandatory here and checked in the service, not only in the form
    (§6.5), since this guard is what a forged or stale request still has to
    pass.
    """
    blockers: list[str] = []
    if poll.state not in (
        PollState.ANNOUNCED,
        PollState.OPEN,
        PollState.CLOSED,
        PollState.PUBLISHED,
    ):
        blockers.append("not_withdrawable")
    if not reason:
        blockers.append("reason_required")
    return blockers


def withdraw_poll(
    poll: Poll,
    actor: User | None = None,
    reason: Reason | str = "",
    now: datetime | None = None,
) -> Poll:
    """``announced``/``open``/``closed``/``published`` → ``withdrawn`` (R-3.11).

    Manual only, from screen 2 — nothing schedules it, and nothing about
    *when* a poll should be pulled follows from a configured instant the way
    opening and closing do (§4). Irreversible like every transition (R-3.2).

    Leaves ballots, ``closure_hash`` and the audit log exactly as they were:
    withdrawal is a visibility change, not a deletion. Its only writes beyond
    ``state`` are ``withdrawn_at`` — the retention anchor R-13.3 needs for a
    poll pulled before ever reaching ``closed`` (§11) — and the audit event
    the mandatory reason is attached to.
    """
    return _run_transition("withdraw_poll", _withdraw_poll_locked, poll, actor, reason, now)


@transaction.atomic
def _withdraw_poll_locked(
    poll: Poll, actor: User | None, reason: Reason | str, now: datetime | None
) -> Poll:
    poll = Poll.objects.select_for_update().get(pk=poll.pk)
    blockers = withdrawing_blockers(poll, reason)
    if blockers:
        raise TransitionRefused(_("Retrait refusé."), blockers)

    previous_state = poll.state
    poll.withdrawn_at = now or timezone.now()
    poll.state = PollState.WITHDRAWN
    poll.save(update_fields=["withdrawn_at", "state"])
    audit.record(
        action=Action.POLL_WITHDRAWN,
        poll=poll,
        actor=actor,
        object_ref=audit.ref(poll),
        before={"state": previous_state},
        after={"state": PollState.WITHDRAWN, "withdrawn_at": poll.withdrawn_at.isoformat()},
        reason=reason,
    )
    return poll
