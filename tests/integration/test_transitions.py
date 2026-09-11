# SPDX-License-Identifier: 0BSD
"""The transition function and its guards (§4, §5.1)."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.audit.models import Action, AuditEvent
from apps.ballots.models import Ballot, BallotSource, BallotStatus
from apps.core.codes import new_tracking_code
from apps.elections.models import Poll, PollOption, PollState, WorkingRollEntry
from apps.elections.transitions import (
    TransitionRefused,
    announce_poll,
    announcing_blockers,
    close_poll,
    closing_blockers,
    open_poll,
    opening_blockers,
)


def test_opening_takes_the_snapshot_and_the_seed_in_one_transaction(
    open_window_poll: Poll,
) -> None:
    """§4: both MUST occur in the same transaction as the state write, so two
    concurrent runs cannot produce two snapshots or two seeds (T-51)."""
    poll = open_poll(open_window_poll)
    assert poll.state == PollState.OPEN
    assert poll.opening_seed is not None
    assert poll.roll_entries.count() == WorkingRollEntry.objects.count()
    assert AuditEvent.objects.filter(action=Action.ROLL_SNAPSHOT_TAKEN).exists()


def test_t70_announcing_is_lighter_than_opening(open_window_poll: Poll) -> None:
    """T-70, R-3.10: an absent roll does not block ``announce_poll`` — a
    preview needs no snapshot, unlike opening (§6.1) — but a missing
    translation still does, exactly as it would for opening (§3.8): the
    preview announcing freezes must not show a gap that only fell back
    silently because nobody but the poll admin could see it. Configuration
    is frozen the instant it runs (INV-6 already reads ``state != draft``)."""
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


def test_open_poll_accepts_an_announced_poll_exactly_like_draft(
    open_window_poll: Poll,
) -> None:
    """R-3.10: announcing is a detour, not a different destination."""
    poll = announce_poll(open_window_poll)
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
    poll = open_poll(open_window_poll)
    Ballot.objects.create(
        poll=poll,
        tracking_code=new_tracking_code(),
        ranking=[["a"], ["b"], ["c"]],
        source=BallotSource.PAPER,
        status=BallotStatus.PENDING_COUNTERSIGN,
    )
    assert "pending_countersign:1" in closing_blockers(poll)
    with pytest.raises(TransitionRefused):
        close_poll(poll)
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

    poll = open_poll(open_window_poll)
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

    closed = close_poll(poll, override_reason=Reason.COUNTERSIGN_UNAVAILABLE)
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
    poll = open_poll(open_window_poll)
    closed = close_poll(poll)
    assert set(closed.frozen_counts) == {
        "registered",
        "ballots_online",
        "ballots_paper",
        "non_voters",
    }


def test_a_poll_with_fewer_than_two_options_cannot_open(open_window_poll: Poll) -> None:
    PollOption.objects.filter(poll=open_window_poll).exclude(option_id="a").delete()
    assert "fewer_than_two_options" in opening_blockers(open_window_poll)
