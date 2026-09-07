# SPDX-License-Identifier: 0BSD
"""The triggers of §5.1, exercised through raw SQL.

Every assertion here goes around the ORM deliberately: application-level checks
are the layer that produces a decent error message, and these are the layer that
holds against ``update()``, raw SQL, the Django shell and a future maintainer.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from django.db import connection, models, transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.models import Action, AuditEvent
from apps.ballots.models import Ballot, BallotSource, BallotStatus
from apps.core.codes import new_tracking_code
from apps.elections.models import Poll


def raw(sql: str, params: list[str] | None = None) -> None:
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])


def pk(obj: models.Model) -> str:
    """Django stores a ``UUIDField`` on SQLite as 32 hex characters without
    dashes, so raw SQL must ask for it in that form or match nothing at all."""
    return str(obj.pk.hex)


def sql_time(moment: datetime) -> str:
    """The wire format Django writes for an aware datetime on SQLite: UTC,
    six fractional digits, no offset."""
    return moment.strftime("%Y-%m-%d %H:%M:%S.%f")


def test_t24_audit_event_cannot_be_updated_or_deleted(open_window_poll: Poll) -> None:
    """INV-3, absolute — no exception even for the retention purge (§10)."""
    event = audit.record(
        action=Action.POLL_CREATED, poll=open_window_poll, object_ref=audit.ref(open_window_poll)
    )
    with pytest.raises(Exception, match="INV-3"), transaction.atomic():
        raw("UPDATE audit_auditevent SET action = 'tally_run' WHERE id = %s", [pk(event)])
    with pytest.raises(Exception, match="INV-3"), transaction.atomic():
        raw("DELETE FROM audit_auditevent WHERE id = %s", [pk(event)])
    assert AuditEvent.objects.filter(pk=event.pk).exists()


def test_t24_superseded_ballot_versions_are_immutable(open_window_poll: Poll) -> None:
    ballot = Ballot.objects.create(
        poll=open_window_poll,
        tracking_code=new_tracking_code(),
        ranking=[["a"], ["b"], ["c"]],
        source=BallotSource.ONLINE,
        status=BallotStatus.SUPERSEDED,
    )
    with pytest.raises(Exception, match="INV-3"), transaction.atomic():
        raw("UPDATE ballots_ballot SET ranking = '[[\"c\"]]' WHERE id = %s", [pk(ballot)])
    with pytest.raises(Exception, match="INV-3"), transaction.atomic():
        raw("DELETE FROM ballots_ballot WHERE id = %s", [pk(ballot)])


def test_t52_ballot_before_opens_at_is_refused_even_with_state_forced_to_open(
    open_window_poll: Poll,
) -> None:
    """The window check never consults ``state`` (§4, INV-2).

    Here the poll's opening instant is moved into the future by raw SQL — the
    state field says nothing that would save the write.
    """
    # Still inside closes_at, so only the opening instant moves.
    future = timezone.now() + timedelta(hours=12)
    raw(
        "UPDATE elections_poll SET opens_at = %s, state = 'open' WHERE id = %s",
        [sql_time(future), pk(open_window_poll)],
    )

    with pytest.raises(Exception, match="INV-2"), transaction.atomic():
        Ballot.objects.create(
            poll=open_window_poll,
            tracking_code=new_tracking_code(),
            ranking=[["a"], ["b"], ["c"]],
            source=BallotSource.ONLINE,
        )


def test_t56_paper_keying_window_outlives_online_voting(open_window_poll: Poll) -> None:
    """§6.4: online voting stops at ``closes_at``; keying continues to
    ``paper_entry_deadline``."""
    now = timezone.now()
    raw(
        "UPDATE elections_poll SET closes_at = %s, paper_entry_deadline = %s WHERE id = %s",
        [
            sql_time(now - timedelta(hours=1)),
            sql_time(now + timedelta(days=1)),
            pk(open_window_poll),
        ],
    )
    paper = Ballot.objects.create(
        poll=open_window_poll,
        tracking_code=new_tracking_code(),
        ranking=[["a"], ["b"], ["c"]],
        source=BallotSource.PAPER,
        status=BallotStatus.PENDING_COUNTERSIGN,
    )
    assert paper.pk is not None

    with pytest.raises(Exception, match="INV-2"), transaction.atomic():
        Ballot.objects.create(
            poll=open_window_poll,
            tracking_code=new_tracking_code(),
            ranking=[["a"], ["b"], ["c"]],
            source=BallotSource.ONLINE,
        )

    # Countersignature is itself a write to the ballot and gets the paper
    # window, so the queue stays usable up to the deadline.
    paper.status = BallotStatus.LIVE
    paper.save(update_fields=["status"])


def test_t4_poll_configuration_is_frozen_outside_draft(open_window_poll: Poll) -> None:
    """INV-6 / R-3.3, at the database, since ``save()`` is bypassed by
    ``update()`` and raw SQL."""
    raw("UPDATE elections_poll SET state = 'open' WHERE id = %s", [pk(open_window_poll)])
    with pytest.raises(Exception, match="INV-6"), transaction.atomic():
        raw(
            "UPDATE elections_poll SET require_complete_ranking = 0 WHERE id = %s",
            [pk(open_window_poll)],
        )
    with pytest.raises(Exception, match="INV-6"), transaction.atomic():
        raw(
            "UPDATE elections_polloption SET option_id = 'z' WHERE poll_id = %s",
            [pk(open_window_poll)],
        )
    # closes_at moves, with a reason, through the extension action of R-3.4 —
    # and paper_entry_deadline moves with it, preserving the window length (§4).
    later = timezone.now() + timedelta(days=3)
    raw(
        "UPDATE elections_poll SET closes_at = %s, paper_entry_deadline = %s WHERE id = %s",
        [sql_time(later), sql_time(later), pk(open_window_poll)],
    )


def test_state_machine_is_irreversible(open_window_poll: Poll) -> None:
    """R-3.2. ``draft → open → closed → published``, one step at a time."""
    raw("UPDATE elections_poll SET state = 'open' WHERE id = %s", [pk(open_window_poll)])
    with pytest.raises(Exception, match="R-3.2"), transaction.atomic():
        raw("UPDATE elections_poll SET state = 'draft' WHERE id = %s", [pk(open_window_poll)])
    with pytest.raises(Exception, match="R-3.2"), transaction.atomic():
        raw(
            "UPDATE elections_poll SET state = 'published' WHERE id = %s",
            [pk(open_window_poll)],
        )


def test_inv7_roll_snapshot_is_immutable_and_purgeable_only_after_closure(
    open_window_poll: Poll,
) -> None:
    """§11: a snapshot is frozen, not immortal."""
    from apps.elections.models import RollEntry

    entry = RollEntry.objects.create(
        poll=open_window_poll, last_name="Dupont", first_names="Émile", nne="12345678"
    )
    with pytest.raises(Exception, match="INV-7"), transaction.atomic():
        raw("UPDATE elections_rollentry SET nne = '87654321' WHERE id = %s", [pk(entry)])
    with pytest.raises(Exception, match="INV-7"), transaction.atomic():
        raw("DELETE FROM elections_rollentry WHERE id = %s", [pk(entry)])

    raw("UPDATE elections_poll SET state = 'open' WHERE id = %s", [pk(open_window_poll)])
    raw("UPDATE elections_poll SET state = 'closed' WHERE id = %s", [pk(open_window_poll)])
    raw("DELETE FROM elections_rollentry WHERE id = %s", [pk(entry)])
    assert not RollEntry.objects.filter(pk=entry.pk).exists()
