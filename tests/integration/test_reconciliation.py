# SPDX-License-Identifier: 0BSD
"""R-8.6's formal reconciliation: ``ballots.services.record_reconciliation`` and
the ``reconciliation_pending`` closure guard it feeds (§9, docs/specification-decision-log.md #16).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import Action, AuditEvent
from apps.ballots import services
from apps.ballots.models import Ballot, BallotSource, BallotStatus, ReconciliationRecord
from apps.ballots.ranking import BallotRefused
from apps.core.codes import new_tracking_code
from apps.core.models import User
from apps.elections.models import Poll, PollState
from apps.elections.transitions import TransitionRefused, close_poll, closing_blockers


@pytest.fixture
def operator(db: None) -> User:
    return User.objects.create_user(username="op1", password="x", full_name="Op Un")


def test_flag_off_is_never_a_blocker(open_paper_poll: Poll) -> None:
    """A poll that never set ``paper_requires_reconciliation`` sees no trace
    of it — the audit log is the record instead, per R-8.6's own fallback."""
    assert "reconciliation_pending" not in closing_blockers(open_paper_poll)


def test_flag_on_blocks_closure_until_recorded(
    paper_poll_reconciliation: Poll, operator: User
) -> None:
    """R-8.6: the boolean now has teeth — unlike ``pending_countersign``, there
    is no override (R-8.7 bis names one only for countersignature)."""
    poll = paper_poll_reconciliation
    assert "reconciliation_pending" in closing_blockers(poll)
    with pytest.raises(TransitionRefused):
        close_poll(poll)
    poll.refresh_from_db()
    assert poll.state == PollState.OPEN

    services.record_reconciliation(poll, forms_retained_count=0, operator_id=str(operator.pk))
    assert "reconciliation_pending" not in closing_blockers(poll)
    closed = close_poll(poll)
    assert closed.state == PollState.CLOSED


def test_override_reason_does_not_bypass_a_missing_record(
    paper_poll_reconciliation: Poll, operator: User
) -> None:
    """Unlike ``pending_countersign:n``, ``reconciliation_pending`` does not
    start with that prefix, so ``_close_poll_locked``'s ``overridable`` check
    already refuses it even with a reason supplied — no code change needed
    there, only the new blocker."""
    from apps.audit.models import Reason

    with pytest.raises(TransitionRefused):
        close_poll(paper_poll_reconciliation, override_reason=Reason.ADMINISTRATIVE_DECISION)


def test_records_the_systems_own_paper_count_not_the_operators(
    paper_poll_reconciliation_window_open: Poll, operator: User
) -> None:
    """The operator supplies only the physical count; the system count is
    computed from the live paper ballots, never taken on their word."""
    poll = paper_poll_reconciliation_window_open
    Ballot.objects.create(
        poll=poll,
        tracking_code=new_tracking_code(),
        ranking=[["a"], ["b"], ["c"]],
        source=BallotSource.PAPER,
        status=BallotStatus.LIVE,
    )
    # A superseded and a deleted paper ballot must not be counted either.
    Ballot.objects.create(
        poll=poll,
        tracking_code=new_tracking_code(),
        ranking=[["a"], ["b"], ["c"]],
        source=BallotSource.PAPER,
        status=BallotStatus.DELETED,
    )
    Ballot.objects.create(
        poll=poll,
        tracking_code=new_tracking_code(),
        ranking=[["a"], ["b"], ["c"]],
        source=BallotSource.ONLINE,
        status=BallotStatus.LIVE,
    )

    # The ballots above were seeded as if keyed during the still-open window;
    # neither field is frozen config (R-3.4), so closing the window now, the
    # way ``extend_closes_at`` would move it forward, is a legitimate plain
    # save rather than a config edit INV-6 would refuse.
    past = timezone.now() - timedelta(hours=1)
    poll.closes_at = past
    poll.paper_entry_deadline = past
    poll.save(update_fields=["closes_at", "paper_entry_deadline"])

    record = services.record_reconciliation(
        poll, forms_retained_count=2, operator_id=str(operator.pk), note="un écart"
    )
    assert record.forms_retained_count == 2
    assert record.recorded_ballots_count == 1
    assert record.discrepancy == 1
    assert record.note == "un écart"
    assert record.signed_by == operator

    event = AuditEvent.objects.get(action=Action.RECONCILIATION_RECORDED)
    assert event.after == {"forms_retained_count": 2, "recorded_ballots_count": 1}
    assert event.reason == ""


def test_refuses_before_the_paper_entry_deadline(
    paper_poll_reconciliation_window_open: Poll, operator: User
) -> None:
    """A count taken before the window closes could be made stale by a paper
    entry or correction the window still legitimately admits (§6.4)."""
    poll = paper_poll_reconciliation_window_open
    assert poll.paper_entry_deadline > timezone.now()

    with pytest.raises(BallotRefused, match="fin de la saisie"):
        services.record_reconciliation(poll, forms_retained_count=0, operator_id=str(operator.pk))


def test_refuses_a_second_record(paper_poll_reconciliation: Poll, operator: User) -> None:
    poll = paper_poll_reconciliation
    services.record_reconciliation(poll, forms_retained_count=0, operator_id=str(operator.pk))
    with pytest.raises(BallotRefused, match="déjà"):
        services.record_reconciliation(poll, forms_retained_count=1, operator_id=str(operator.pk))
    assert ReconciliationRecord.objects.filter(poll=poll).count() == 1


def test_refuses_on_a_poll_that_is_not_open(
    paper_poll_reconciliation: Poll, operator: User
) -> None:
    poll = paper_poll_reconciliation
    # A raw update, not ``transitions.close_poll`` (which this very guard is
    # tested against elsewhere) — only the field value matters here.
    Poll.objects.filter(pk=poll.pk).update(state=PollState.CLOSED, closed_at=timezone.now())
    poll.refresh_from_db()
    with pytest.raises(BallotRefused, match="ouvert"):
        services.record_reconciliation(poll, forms_retained_count=0, operator_id=str(operator.pk))
