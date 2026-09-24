# SPDX-License-Identifier: 0BSD
"""The transition function and its guards (§4, §5.1)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit.models import Action, AuditEvent, Reason
from apps.ballots.models import Ballot, BallotSource, BallotStatus
from apps.core.codes import new_tracking_code
from apps.core.models import User
from apps.elections.models import Poll, PollOption, PollState, WorkingRollEntry
from apps.elections.transitions import (
    TransitionRefused,
    announce_poll,
    announcing_blockers,
    close_poll,
    closing_blockers,
    open_poll,
    opening_blockers,
    publish_poll,
    withdraw_poll,
    withdrawing_blockers,
)
from tests.conftest import _create_open_poll, force_open


def test_opening_takes_the_snapshot_and_the_seed_in_one_transaction(
    open_window_poll: Poll,
) -> None:
    """§4: both MUST occur in the same transaction as the state write, so two
    concurrent runs cannot produce two snapshots or two seeds (T-51)."""
    # announce_poll now requires opens_at still in the future (R-3.10); this
    # fixture's is deliberately in the past for other tests' sake.
    open_window_poll.opens_at = timezone.now() + timedelta(hours=1)
    open_window_poll.save(update_fields=["opens_at"])
    announce_poll(open_window_poll)
    poll = open_poll(Poll.objects.get(pk=open_window_poll.pk))
    assert poll.state == PollState.OPEN
    assert poll.opening_seed is not None
    assert poll.roll_entries.count() == WorkingRollEntry.objects.count()
    assert AuditEvent.objects.filter(action=Action.ROLL_SNAPSHOT_TAKEN).exists()


def _announced_with_future_opens_at(poll: Poll, hours: int = 3) -> Poll:
    poll.opens_at = timezone.now() + timedelta(hours=hours)
    poll.save(update_fields=["opens_at"])
    announce_poll(poll)
    return Poll.objects.get(pk=poll.pk)


def test_t67_opening_by_hand_ahead_of_opens_at_pulls_it_back_to_now(
    open_window_poll: Poll,
) -> None:
    """R-3.4: the poll must be votable, and listed, from the moment the poll
    admin forces the opening, not just read ``open`` in the back-office."""
    poll = _announced_with_future_opens_at(open_window_poll)
    planned = poll.opens_at
    now = timezone.now()

    opened = open_poll(poll, now=now)

    assert opened.state == PollState.OPEN
    assert opened.opens_at == now
    assert Poll.objects.get(pk=poll.pk).opens_at == now
    assert opened.closes_at > opened.opens_at
    event = AuditEvent.objects.filter(action=Action.POLL_STATE_CHANGED).latest("at")
    assert event.before["opens_at"] == planned.isoformat()
    assert event.after["opens_at"] == now.isoformat()


def test_t67_the_scheduled_opening_leaves_opens_at_alone(open_window_poll: Poll) -> None:
    poll = _announced_with_future_opens_at(open_window_poll, hours=1)
    planned = poll.opens_at

    opened = open_poll(poll, now=planned + timedelta(minutes=5))

    assert opened.opens_at == planned
    event = AuditEvent.objects.filter(action=Action.POLL_STATE_CHANGED).latest("at")
    assert "opens_at" not in event.before
    assert "opens_at" not in event.after


def test_t67_an_early_opened_poll_accepts_a_registration_window_check_at_once(
    open_window_poll: Poll,
) -> None:
    from apps.elections.windows import check_ballot_window, check_registration_window

    poll = open_poll(_announced_with_future_opens_at(open_window_poll))
    check_registration_window(poll)
    check_ballot_window(poll, BallotSource.ONLINE)


def test_t67_opens_at_moves_only_on_the_opening_write_and_only_earlier(
    open_window_poll: Poll,
) -> None:
    """INV-6 stays the enforcement: the trigger admits the one carve-out of
    R-3.4 and nothing wider, and so does ``Poll.save()`` (the message)."""
    from django.db import connection

    poll = _announced_with_future_opens_at(open_window_poll)
    later = poll.opens_at + timedelta(hours=1)

    # Announced, not opening: frozen as before, in the model and in the trigger.
    poll.opens_at = poll.opens_at - timedelta(minutes=30)
    with pytest.raises(ValidationError):
        poll.save(update_fields=["opens_at"])
    poll = Poll.objects.get(pk=poll.pk)
    with connection.cursor() as cursor, pytest.raises(Exception, match="INV-6"):
        cursor.execute(
            "UPDATE elections_poll SET opens_at = %s WHERE id = %s",
            [poll.opens_at - timedelta(minutes=30), poll.pk.hex],
        )
    # Opening, but later: refused by the trigger.
    with connection.cursor() as cursor, pytest.raises(Exception, match="INV-6"):
        cursor.execute(
            "UPDATE elections_poll SET state = 'open', opens_at = %s WHERE id = %s",
            [later, poll.pk.hex],
        )
    poll = open_poll(Poll.objects.get(pk=poll.pk))
    # Already open: frozen again.
    with connection.cursor() as cursor, pytest.raises(Exception, match="INV-6"):
        cursor.execute(
            "UPDATE elections_poll SET opens_at = %s WHERE id = %s",
            [poll.opens_at - timedelta(hours=1), poll.pk.hex],
        )


def test_t70_announcing_is_lighter_than_opening(open_window_poll: Poll) -> None:
    """T-70, R-3.10: an absent roll does not block ``announce_poll`` — a
    preview needs no snapshot, unlike opening (§6.1) — but a missing
    translation still does, exactly as it would for opening (§3.8): the
    preview announcing freezes must not show a gap that only fell back
    silently because nobody but the poll admin could see it. Configuration
    is frozen the instant it runs (INV-6 already reads ``state != draft``)."""
    open_window_poll.opens_at = timezone.now() + timedelta(hours=1)
    open_window_poll.save(update_fields=["opens_at"])
    WorkingRollEntry.objects.all().delete()
    assert announcing_blockers(open_window_poll) == []
    # Would block opening, though — announcing is lighter in this one respect.
    assert "no_roll_to_snapshot" in opening_blockers(open_window_poll)

    poll = announce_poll(open_window_poll)
    assert poll.state == PollState.ANNOUNCED
    assert AuditEvent.objects.filter(action=Action.POLL_STATE_CHANGED, poll=poll).exists()

    # Frozen like `open` — the same INV-6 guard (``Poll.save()``'s
    # ``state != draft`` check), not a separate mechanism for this state.
    poll.tally_method_version = "9"
    with pytest.raises(ValidationError, match="figée"):
        poll.save(update_fields=["tally_method_version"])


def test_t70_announcing_refuses_a_missing_translation(open_window_poll: Poll) -> None:
    """R-3.10, §3.8: unlike an absent roll, a missing translation blocks
    ``announce_poll`` exactly as it blocks ``open_poll`` — the same
    ``missing_translation`` blocker code, so the dashboard's ``describe_blocker``
    needs no case of its own for this state."""
    open_window_poll.languages = ["fr", "en"]  # an English translation is missing everywhere
    open_window_poll.save(update_fields=["languages"])
    assert "missing_translation:title:en" in announcing_blockers(open_window_poll)

    with pytest.raises(TransitionRefused):
        announce_poll(open_window_poll)
    open_window_poll.refresh_from_db()
    assert open_window_poll.state == PollState.DRAFT


def test_t82_open_poll_refuses_a_still_draft_poll(open_window_poll: Poll) -> None:
    """T-82, R-3.2/R-3.10: ``announced`` is now mandatory, not a detour —
    ``open_poll`` refuses a poll that never announced itself, whatever its
    ``opens_at``, and leaves it in ``draft``."""
    assert "not_announced" in opening_blockers(open_window_poll)
    with pytest.raises(TransitionRefused):
        open_poll(open_window_poll)
    open_window_poll.refresh_from_db()
    assert open_window_poll.state == PollState.DRAFT


def test_t83_announcing_refuses_once_opens_at_has_passed_and_recovers(
    open_window_poll: Poll,
) -> None:
    """T-83, R-3.10: announcing a poll whose opening hour is already behind
    it would freeze a preview only to open immediately behind it. Recovery
    is an ordinary draft edit — push ``opens_at`` forward (R-3.3) — not an
    override."""
    assert "opens_at_not_in_future" in announcing_blockers(open_window_poll)
    with pytest.raises(TransitionRefused):
        announce_poll(open_window_poll)
    open_window_poll.refresh_from_db()
    assert open_window_poll.state == PollState.DRAFT

    open_window_poll.opens_at = timezone.now() + timedelta(hours=1)
    open_window_poll.save(update_fields=["opens_at"])
    poll = announce_poll(open_window_poll)
    assert poll.state == PollState.ANNOUNCED

    opened = open_poll(Poll.objects.get(pk=poll.pk))
    assert opened.state == PollState.OPEN
    assert opened.opening_seed is not None

    events = AuditEvent.objects.filter(action=Action.POLL_STATE_CHANGED, poll=opened).order_by("at")
    assert [e.before.get("state") for e in events] == ["draft", "announced"]
    assert [e.after.get("state") for e in events] == ["announced", "open"]


def test_t70_announcing_refuses_fewer_than_two_propositions(open_window_poll: Poll) -> None:
    open_window_poll.options.exclude(option_id="a").delete()
    assert "fewer_than_two_options" in announcing_blockers(open_window_poll)
    with pytest.raises(TransitionRefused):
        announce_poll(open_window_poll)
    open_window_poll.refresh_from_db()
    assert open_window_poll.state == PollState.DRAFT


def test_t53_opening_refuses_an_untranslated_poll_and_one_with_no_roll(
    open_window_poll: Poll,
) -> None:
    """A refusal must be loud: the poll stays in ``draft``, the blocker is
    logged, and the command exits non-zero (§4)."""
    open_window_poll.languages = ["fr", "en"]
    open_window_poll.save(update_fields=["languages"])

    blockers = opening_blockers(open_window_poll)
    assert any(b.startswith("missing_translation:") for b in blockers)
    with pytest.raises(TransitionRefused):
        open_poll(open_window_poll)
    open_window_poll.refresh_from_db()
    assert open_window_poll.state == PollState.DRAFT
    assert AuditEvent.objects.filter(action=Action.JOB_REFUSED).exists()

    WorkingRollEntry.objects.all().delete()
    assert "no_roll_to_snapshot" in opening_blockers(open_window_poll)


def test_t57_closure_refuses_while_a_ballot_awaits_countersignature(
    open_window_poll: Poll,
) -> None:
    """§9: silently dropping uncountersigned ballots at closure is not
    acceptable, so the transition stops and the dashboard shows the count."""
    poll = force_open(open_window_poll)
    Ballot.objects.create(
        poll=poll,
        tracking_code=new_tracking_code(),
        ranking=[["a"], ["b"], ["c"]],
        source=BallotSource.PAPER,
        status=BallotStatus.PENDING_COUNTERSIGN,
    )
    assert "pending_countersign:1" in closing_blockers(poll)
    with pytest.raises(TransitionRefused):
        close_poll(poll, early_reason=Reason.ADMINISTRATIVE_DECISION)
    poll.refresh_from_db()
    assert poll.state == PollState.OPEN


def test_t32_closure_override_excludes_uncountersigned_ballots(
    open_window_poll: Poll,
) -> None:
    """T-32: overridden closure leaves those ballots out of the tally, the
    closure hash and the published CSV, and the reason appears in the
    publication."""
    from apps.audit.models import Reason
    from apps.core.canonical import closure_hash
    from apps.elections.closure import live_ballots

    poll = force_open(open_window_poll)
    live = Ballot.objects.create(
        poll=poll,
        tracking_code=new_tracking_code(),
        ranking=[["a"], ["b"], ["c"]],
        source=BallotSource.ONLINE,
    )
    Ballot.objects.create(
        poll=poll,
        tracking_code=new_tracking_code(),
        ranking=[["c"], ["b"], ["a"]],
        source=BallotSource.PAPER,
        status=BallotStatus.PENDING_COUNTERSIGN,
    )

    closed = close_poll(
        poll,
        override_reason=Reason.COUNTERSIGN_UNAVAILABLE,
        early_reason=Reason.ADMINISTRATIVE_DECISION,
    )
    assert closed.state == PollState.CLOSED
    assert closed.closure_override_reason == Reason.COUNTERSIGN_UNAVAILABLE

    covered = live_ballots(closed)
    assert [str(b.tracking_code) for b in covered] == [live.tracking_code]
    assert closed.closure_hash is not None
    assert bytes(closed.closure_hash) == closure_hash(covered)
    assert AuditEvent.objects.filter(action=Action.CLOSURE_OVERRIDE).exists()


def test_frozen_counts_are_stored_at_closure_not_derived_later(
    open_window_poll: Poll,
) -> None:
    """§9, T-58: they read ``Registration``, which the retention job deletes."""
    poll = force_open(open_window_poll)
    closed = close_poll(poll, early_reason=Reason.ADMINISTRATIVE_DECISION)
    assert set(closed.frozen_counts) == {
        "registered",
        "ballots_online",
        "ballots_paper",
        "paper_uncountersigned",
        "non_voters",
    }


def test_a_poll_with_fewer_than_two_options_cannot_open(open_window_poll: Poll) -> None:
    PollOption.objects.filter(poll=open_window_poll).exclude(option_id="a").delete()
    assert "fewer_than_two_options" in opening_blockers(open_window_poll)


# --- withdrawal (R-3.11) ----------------------------------------------------


def _minimal_poll(title: str) -> Poll:
    now = timezone.now()
    poll = Poll.objects.create(
        title_i18n={"fr": title},
        description_i18n={"fr": title},
        languages=["fr"],
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
    )
    for position, option_id in enumerate(["a", "b"]):
        PollOption.objects.create(
            poll=poll, option_id=option_id, label_i18n={"fr": option_id}, position=position
        )
    return poll


def test_t72_withdraw_poll_succeeds_from_each_of_the_four_public_states(
    open_window_poll: Poll,
) -> None:
    """T-72, R-3.11: ``announced``, ``open``, ``closed`` and ``published`` all
    accept a reasoned withdrawal and land in ``withdrawn``; a further
    transition attempted on any of them — including a second withdrawal — is
    refused, since ``withdrawn`` joins nothing (R-3.2)."""
    admin = User.objects.create_user(username="p.admin", password="x")

    open_window_poll.opens_at = timezone.now() + timedelta(hours=1)
    open_window_poll.save(update_fields=["opens_at"])
    announced = withdraw_poll(announce_poll(open_window_poll), reason=Reason.OTHER)
    assert announced.state == PollState.WITHDRAWN
    assert announced.withdrawn_at is not None
    with pytest.raises(TransitionRefused):
        withdraw_poll(announced, reason=Reason.OTHER)

    opened = withdraw_poll(force_open(_minimal_poll("Ouvert")), reason=Reason.OTHER)
    assert opened.state == PollState.WITHDRAWN

    closed = withdraw_poll(
        close_poll(force_open(_minimal_poll("Clos")), early_reason=Reason.ADMINISTRATIVE_DECISION),
        reason=Reason.OTHER,
    )
    assert closed.state == PollState.WITHDRAWN
    # A poll withdrawn after closure keeps the earlier, correct anchor (§11).
    assert closed.closed_at is not None
    assert closed.withdrawn_at is not None
    assert closed.closed_at < closed.withdrawn_at

    published_source = publish_poll(
        close_poll(
            force_open(_minimal_poll("Publié")), early_reason=Reason.ADMINISTRATIVE_DECISION
        ),
        admin,
    )
    published = withdraw_poll(published_source, reason=Reason.OTHER)
    assert published.state == PollState.WITHDRAWN

    assert AuditEvent.objects.filter(action=Action.POLL_WITHDRAWN).count() == 4


def test_t73_withdraw_poll_refuses_draft_and_a_missing_reason(open_window_poll: Poll) -> None:
    """T-73: a ``draft`` poll is deleted, not withdrawn — ``not_withdrawable``
    — and an open poll with no reason is refused as ``reason_required``, both
    logged as ``job_refused`` and leaving the state untouched."""
    assert withdrawing_blockers(open_window_poll, Reason.OTHER) == ["not_withdrawable"]
    with pytest.raises(TransitionRefused):
        withdraw_poll(open_window_poll, reason=Reason.OTHER)
    assert Poll.objects.get(pk=open_window_poll.pk).state == PollState.DRAFT

    poll = force_open(open_window_poll)
    assert withdrawing_blockers(poll, "") == ["reason_required"]
    with pytest.raises(TransitionRefused):
        withdraw_poll(poll, reason="")
    poll.refresh_from_db()
    assert poll.state == PollState.OPEN

    assert AuditEvent.objects.filter(action=Action.JOB_REFUSED).count() == 2


def test_withdrawal_leaves_ballots_and_closure_hash_untouched(open_window_poll: Poll) -> None:
    """R-3.11: a visibility change, not a deletion — the live ballot set, the
    closure hash and the frozen counts a published poll carries stay exactly
    as they were."""
    poll = force_open(open_window_poll)
    Ballot.objects.create(
        poll=poll,
        tracking_code=new_tracking_code(),
        ranking=[["a"], ["b"], ["c"]],
        source=BallotSource.ONLINE,
    )
    closed = close_poll(poll, early_reason=Reason.ADMINISTRATIVE_DECISION)
    assert closed.closure_hash is not None
    closure_hash = bytes(closed.closure_hash)
    frozen_counts = dict(closed.frozen_counts)

    withdrawn = withdraw_poll(closed, reason=Reason.OTHER)
    assert Ballot.objects.filter(poll=poll, status=BallotStatus.LIVE).count() == 1
    assert withdrawn.closure_hash is not None
    assert bytes(withdrawn.closure_hash) == closure_hash
    assert dict(withdrawn.frozen_counts) == frozen_counts


# --- R-3.4, decision log #34: early closure ----------------------------------


def test_early_closure_during_the_paper_stretch_keeps_closes_at(db: None) -> None:
    """Closed after ``closes_at`` but before ``paper_entry_deadline``: online
    voting really did stop at ``closes_at``, so only the paper deadline moves."""
    now = timezone.now()
    poll = _create_open_poll(
        title="Fenêtre papier",
        description="Saisie différée.",
        opens_at=now - timedelta(days=2),
        closes_at=now - timedelta(hours=1),
        paper_entry_deadline=now + timedelta(days=1),
        roll_name=("Dupont", "Émile", "12/05/1970", "1970-05-12"),
    )
    closes_at = poll.closes_at
    with pytest.raises(TransitionRefused) as refused:
        close_poll(poll, now=now)
    assert refused.value.blockers == ["early_closure_reason_required"]

    closed = close_poll(poll, now=now, early_reason=Reason.ADMINISTRATIVE_DECISION)
    assert closed.closes_at == closes_at
    assert closed.paper_entry_deadline == now == closed.closed_at


def test_the_scheduled_closure_is_never_early(open_paper_poll: Poll) -> None:
    """At or after the deadline nothing moves and no reason is asked for."""
    deadline = open_paper_poll.paper_entry_deadline
    closed = close_poll(open_paper_poll, now=deadline)
    assert closed.paper_entry_deadline == deadline
    assert not AuditEvent.objects.filter(action=Action.POLL_CLOSED_EARLY).exists()
