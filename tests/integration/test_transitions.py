# SPDX-License-Identifier: 0BSD
"""The transition function and its guards (§4, §5.1)."""

from __future__ import annotations

import pytest

from apps.audit.models import Action, AuditEvent
from apps.ballots.models import Ballot, BallotSource, BallotStatus
from apps.core.codes import new_tracking_code
from apps.elections.models import Poll, PollOption, PollState, WorkingRollEntry
from apps.elections.transitions import (
    TransitionRefused,
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
