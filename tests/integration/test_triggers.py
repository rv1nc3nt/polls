# SPDX-License-Identifier: 0BSD
"""The triggers of §5.1, exercised through raw SQL.

Every assertion here goes around the ORM deliberately: application-level checks
are the layer that produces a decent error message, and these are the layer that
holds against ``update()``, raw SQL, the Django shell and a future maintainer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from django.db import connection, models, transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.models import Action, AuditEvent
from apps.ballots.models import Ballot, BallotSource, BallotStatus
from apps.core.codes import new_tracking_code
from apps.elections.models import OptionImage, Poll


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


def test_paper_channel_registration_moves_in_the_keying_window(open_window_poll: Poll) -> None:
    """D1 / §6.4: a paper voter's channel indicator tracks the *ballot* window,
    so it may be created and moved after ``closes_at`` and until
    ``paper_entry_deadline`` — and nothing else on the row may."""
    from apps.elections.models import RollEntry
    from apps.registrations.models import Channel, Registration, RegistrationState

    entry = RollEntry.objects.create(
        poll=open_window_poll,
        birth_name="Dupont",
        first_names="Émile",
        date_of_birth="12/05/1970",
        list_types=["principale"],
    )
    now = timezone.now()
    raw(
        "UPDATE elections_poll SET closes_at = %s, paper_entry_deadline = %s WHERE id = %s",
        [
            sql_time(now - timedelta(hours=1)),
            sql_time(now + timedelta(days=1)),
            pk(open_window_poll),
        ],
    )

    # A paper-channel registration may still be created; an online one may not.
    paper = Registration.objects.create(
        poll=open_window_poll,
        roll_entry=entry,
        state=RegistrationState.ACTIVE,
        channel=Channel.PAPER,
        declared_last_name="Dupont",
        declared_first_names="Émile",
        declared_dob="12/05/1970",
        email="",
        email_canonical="",
    )
    with pytest.raises(Exception, match="INV-2"), transaction.atomic():
        Registration.objects.create(
            poll=open_window_poll,
            state=RegistrationState.PENDING_EMAIL,
            channel=Channel.ONLINE,
            declared_last_name="X",
            declared_first_names="Y",
            email="x@example.test",
            email_canonical="x@example.test",
        )

    # The channel may be cleared (paper ballot deleted, R-9.4) and set again ...
    Registration.objects.filter(pk=paper.pk).update(channel=Channel.NONE)
    Registration.objects.filter(pk=paper.pk).update(channel=Channel.PAPER)
    # ... but no other column may move in this window.
    with pytest.raises(Exception, match="INV-2"), transaction.atomic():
        Registration.objects.filter(pk=paper.pk).update(state=RegistrationState.REJECTED)

    # Past paper_entry_deadline even the channel is frozen.
    raw(
        "UPDATE elections_poll SET paper_entry_deadline = %s WHERE id = %s",
        [sql_time(now - timedelta(minutes=1)), pk(open_window_poll)],
    )
    with pytest.raises(Exception, match="INV-2"), transaction.atomic():
        Registration.objects.filter(pk=paper.pk).update(channel=Channel.NONE)


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


def test_t80_option_image_frozen_outside_draft(open_window_poll: Poll) -> None:
    """INV-6 extended to ``OptionImage`` (R-3.12, §3.1 bis).

    The table carries no ``poll`` column of its own, so "frozen outside
    draft" is read through ``option_id`` rather than directly — the one INV-6
    trigger here that does not just compare ``OLD``/``NEW`` against
    ``elections_poll`` by ``poll_id``.
    """
    option = open_window_poll.options.first()
    assert option is not None
    image = OptionImage.objects.create(
        option=option, content_type="image/png", content_hash="a" * 64
    )
    raw("UPDATE elections_poll SET state = 'open' WHERE id = %s", [pk(open_window_poll)])

    with pytest.raises(Exception, match="INV-6"), transaction.atomic():
        raw(
            "INSERT INTO elections_optionimage "
            "(id, option_id, file, content_type, content_hash, alt_text, uploaded_at) "
            "VALUES (%s, %s, '', 'image/png', %s, '', %s)",
            [uuid.uuid4().hex, pk(option), "b" * 64, sql_time(timezone.now())],
        )
    with pytest.raises(Exception, match="INV-6"), transaction.atomic():
        raw("UPDATE elections_optionimage SET alt_text = 'x' WHERE id = %s", [pk(image)])
    with pytest.raises(Exception, match="INV-6"), transaction.atomic():
        raw("DELETE FROM elections_optionimage WHERE id = %s", [pk(image)])
    assert OptionImage.objects.filter(pk=image.pk, alt_text="").exists()


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


def test_t71_the_optional_announced_waypoint_is_legal_but_no_detour_from_it(
    open_window_poll: Poll,
) -> None:
    """T-71, R-3.10: ``draft → announced`` and ``announced → open`` are legal
    additions to the table above; ``announced`` is still a strict waypoint —
    no path leads back out of it except forward to ``open``."""
    raw("UPDATE elections_poll SET state = 'announced' WHERE id = %s", [pk(open_window_poll)])
    with pytest.raises(Exception, match="R-3.2"), transaction.atomic():
        raw("UPDATE elections_poll SET state = 'draft' WHERE id = %s", [pk(open_window_poll)])
    with pytest.raises(Exception, match="R-3.2"), transaction.atomic():
        raw(
            "UPDATE elections_poll SET state = 'closed' WHERE id = %s",
            [pk(open_window_poll)],
        )
    raw("UPDATE elections_poll SET state = 'open' WHERE id = %s", [pk(open_window_poll)])
    with pytest.raises(Exception, match="R-3.2"), transaction.atomic():
        raw(
            "UPDATE elections_poll SET state = 'announced' WHERE id = %s",
            [pk(open_window_poll)],
        )


def test_inv7_roll_snapshot_is_immutable_and_purgeable_only_after_closure(
    open_window_poll: Poll,
) -> None:
    """§11: a snapshot is frozen, not immortal."""
    from apps.elections.models import RollEntry

    entry = RollEntry.objects.create(
        poll=open_window_poll,
        birth_name="Dupont",
        first_names="Émile",
        date_of_birth="12/05/1970",
        list_types=["principale"],
    )
    with pytest.raises(Exception, match="INV-7"), transaction.atomic():
        raw("UPDATE elections_rollentry SET birth_name = 'Autre' WHERE id = %s", [pk(entry)])
    with pytest.raises(Exception, match="INV-7"), transaction.atomic():
        raw("DELETE FROM elections_rollentry WHERE id = %s", [pk(entry)])

    raw("UPDATE elections_poll SET state = 'open' WHERE id = %s", [pk(open_window_poll)])
    raw("UPDATE elections_poll SET state = 'closed' WHERE id = %s", [pk(open_window_poll)])
    raw("DELETE FROM elections_rollentry WHERE id = %s", [pk(entry)])
    assert not RollEntry.objects.filter(pk=entry.pk).exists()


# --- withdrawal (R-3.11) ----------------------------------------------------


def test_t74_the_withdrawn_branches_are_legal_but_withdrawn_itself_is_a_dead_end(
    open_window_poll: Poll,
) -> None:
    """T-74, R-3.2/R-3.11: each of the four legal sources may reach
    ``withdrawn`` directly by raw SQL, but nothing leaves it — not back to its
    source, not forward to any other state — and ``draft`` cannot reach it at
    all, matching ``withdrawing_blockers``' ``not_withdrawable``."""
    with pytest.raises(Exception, match="R-3.2"), transaction.atomic():
        raw(
            "UPDATE elections_poll SET state = 'withdrawn' WHERE id = %s",
            [pk(open_window_poll)],
        )

    raw("UPDATE elections_poll SET state = 'open' WHERE id = %s", [pk(open_window_poll)])
    raw("UPDATE elections_poll SET state = 'withdrawn' WHERE id = %s", [pk(open_window_poll)])
    with pytest.raises(Exception, match="R-3.2"), transaction.atomic():
        raw("UPDATE elections_poll SET state = 'open' WHERE id = %s", [pk(open_window_poll)])
    with pytest.raises(Exception, match="R-3.2"), transaction.atomic():
        raw(
            "UPDATE elections_poll SET state = 'closed' WHERE id = %s",
            [pk(open_window_poll)],
        )


def test_t77_the_delete_carveout_opens_only_once_withdrawn_not_before(
    open_window_poll: Poll,
) -> None:
    """T-77: the same ``DELETE`` that is refused while a poll is ``open`` is
    admitted once it is ``withdrawn`` — the trigger reads the state, not the
    elapsed time, which is ``due_polls``' own selection to enforce (§11)."""
    from apps.elections.models import RollEntry

    entry = RollEntry.objects.create(
        poll=open_window_poll,
        birth_name="Dupont",
        first_names="Émile",
        date_of_birth="12/05/1970",
        list_types=["principale"],
    )
    with pytest.raises(Exception, match="INV-7"), transaction.atomic():
        raw("DELETE FROM elections_rollentry WHERE id = %s", [pk(entry)])

    raw("UPDATE elections_poll SET state = 'open' WHERE id = %s", [pk(open_window_poll)])
    raw("UPDATE elections_poll SET state = 'withdrawn' WHERE id = %s", [pk(open_window_poll)])
    raw("DELETE FROM elections_rollentry WHERE id = %s", [pk(entry)])
    assert not RollEntry.objects.filter(pk=entry.pk).exists()


def test_t78_withdrawn_refuses_ballots_and_registrations_even_inside_the_window(
    open_window_poll: Poll,
) -> None:
    """T-78: ``open_window_poll``'s window is wide open (``opens_at`` in the
    past, ``closes_at`` a day out) — the clock alone would admit every write
    below. Withdrawal refuses them anyway, application check and trigger
    alike, because it is never a delayed scheduled transition (§5.1)."""
    from apps.elections.models import RollEntry
    from apps.elections.transitions import open_poll
    from apps.elections.windows import WindowClosed, check_ballot_window, check_registration_window
    from apps.registrations.models import Channel, Registration, RegistrationState

    poll = open_poll(open_window_poll)
    entry = RollEntry.objects.get(poll=poll)
    raw("UPDATE elections_poll SET state = 'withdrawn' WHERE id = %s", [pk(poll)])
    poll.refresh_from_db()

    with pytest.raises(WindowClosed):
        check_ballot_window(poll, BallotSource.ONLINE)
    with pytest.raises(WindowClosed):
        check_registration_window(poll)

    with pytest.raises(Exception, match="INV-2"), transaction.atomic():
        Ballot.objects.create(
            poll=poll,
            tracking_code=new_tracking_code(),
            ranking=[["a"], ["b"], ["c"]],
            source=BallotSource.ONLINE,
        )
    with pytest.raises(Exception, match="INV-2"), transaction.atomic():
        Registration.objects.create(
            poll=poll,
            roll_entry=entry,
            state=RegistrationState.ACTIVE,
            channel=Channel.NONE,
            declared_last_name="Dupont",
            declared_first_names="Émile",
            declared_dob="12/05/1970",
            email="x@example.test",
            email_canonical="x@example.test",
        )
