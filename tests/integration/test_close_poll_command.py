# SPDX-License-Identifier: 0BSD
"""The scheduled closure, as cron or the systemd timer runs it (§4, T-57).

``transitions.close_poll`` is tested on its own elsewhere; these run the
management command itself — selection by deadline, ``--dry-run``, the exit
code, the ``JobRun`` row and the refusal's audit event — which nothing ran
before (review A-12). And ``run_tally``, the terminal's view of screen 9.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from django.core.management import call_command
from django.test import Client, override_settings
from django.utils import timezone

from apps.audit.models import Action, AuditEvent
from apps.ballots.models import Ballot, BallotSource, BallotStatus
from apps.core.codes import new_tracking_code
from apps.core.models import JobRun, PollRole, Role, User
from apps.elections.models import Poll, PollState
from apps.elections.windows import WindowClosed, check_ballot_window
from tests.conftest import force_open


@pytest.fixture
def lock_dir(tmp_path: Path) -> Path:
    return tmp_path


def _due(poll: Poll, *, pending: int = 0) -> Poll:
    """An open poll with two live ballots, ``pending`` paper entries awaiting a
    countersignature, and its keying deadline just passed."""
    force_open(poll)
    for _ in range(2):
        Ballot.objects.create(
            poll=poll,
            tracking_code=new_tracking_code(),
            ranking=[["a"]],
            source=BallotSource.ONLINE,
        )
    for _ in range(pending):
        Ballot.objects.create(
            poll=poll,
            tracking_code=new_tracking_code(),
            ranking=[["b"]],
            source=BallotSource.PAPER,
            status=BallotStatus.PENDING_COUNTERSIGN,
        )
    past = timezone.now() - timedelta(minutes=1)
    Poll.objects.filter(pk=poll.pk).update(closes_at=past, paper_entry_deadline=past)
    return Poll.objects.get(pk=poll.pk)


def _run(lock_dir: Path, *args: str) -> int:
    """The command's exit status, as cron would see it."""
    with override_settings(JOB_LOCK_DIR=lock_dir):
        try:
            call_command("close_poll", *args)
        except SystemExit as exit_:
            return int(exit_.code or 0)
    return 0


def test_a_poll_past_its_deadline_is_closed(
    open_window_poll: Poll, lock_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    poll = _due(open_window_poll)
    assert _run(lock_dir) == 0
    poll.refresh_from_db()
    assert poll.state == PollState.CLOSED
    assert poll.closure_hash is not None
    assert f"closed {poll.pk}" in capsys.readouterr().out
    run = JobRun.objects.filter(command="close_poll").latest("started_at")
    assert run.succeeded is True
    assert run.detail == {"closed": [str(poll.pk)], "refused": []}


def test_a_poll_whose_deadline_is_ahead_is_left_alone(
    open_window_poll: Poll, lock_dir: Path
) -> None:
    force_open(open_window_poll)
    assert _run(lock_dir) == 0
    assert Poll.objects.get(pk=open_window_poll.pk).state == PollState.OPEN


def test_dry_run_reports_and_writes_nothing(
    open_window_poll: Poll, lock_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    poll = _due(open_window_poll)
    assert _run(lock_dir, "--dry-run") == 0
    assert f"would close {poll.pk}" in capsys.readouterr().out
    assert Poll.objects.get(pk=poll.pk).state == PollState.OPEN


def test_t57_a_pending_countersignature_refuses_loudly_and_writes_nothing_more(
    client: Client, open_window_poll: Poll, lock_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """T-57: refuses, leaves the poll ``open``, logs the blocker, exits
    non-zero; no ballot write is accepted meanwhile; the dashboard names the
    blocker."""
    poll = _due(open_window_poll, pending=1)

    assert _run(lock_dir) == 1
    poll.refresh_from_db()
    assert poll.state == PollState.OPEN
    assert poll.closure_hash is None
    assert f"REFUSED {poll.pk}: pending_countersign:1" in capsys.readouterr().err

    run = JobRun.objects.filter(command="close_poll").latest("started_at")
    assert run.succeeded is False
    assert run.finished_at is not None
    assert run.detail["refused"] == [{"poll": str(poll.pk), "blockers": ["pending_countersign:1"]}]
    event = AuditEvent.objects.get(poll=poll, action=Action.JOB_REFUSED)
    assert event.after == {"command": "close_poll", "blockers": ["pending_countersign:1"]}

    # Closed in substance while the state waits (§4): the clock refuses.
    for source in (BallotSource.ONLINE, BallotSource.PAPER):
        with pytest.raises(WindowClosed):
            check_ballot_window(poll, source)

    admin = User.objects.create_user(username="t57.admin", password="x")
    PollRole.objects.create(poll=poll, user=admin, role=Role.POLL_ADMIN)
    client.force_login(admin)
    dashboard = client.get(f"/fr/mairie/scrutin/{poll.pk}/").content.decode()
    assert "contreseing" in dashboard


def test_one_refusal_does_not_stop_the_others_closing(
    open_window_poll: Poll, lock_dir: Path
) -> None:
    """Each due poll is its own transition: a blocked one is reported, the
    rest still close, and the run as a whole exits non-zero."""
    blocked = _due(open_window_poll, pending=1)
    now = timezone.now()
    other = Poll.objects.create(
        title_i18n={"fr": "Second scrutin"},
        description_i18n={"fr": "Deux propositions."},
        languages=["fr"],
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
    )
    for position, option_id in enumerate("ab"):
        other.options.create(option_id=option_id, label_i18n={"fr": option_id}, position=position)
    clean = _due(other)

    assert _run(lock_dir) == 1
    assert Poll.objects.get(pk=blocked.pk).state == PollState.OPEN
    assert Poll.objects.get(pk=clean.pk).state == PollState.CLOSED


# --- run_tally ---------------------------------------------------------------


def test_run_tally_prints_the_publication_document_of_a_closed_poll(
    open_window_poll: Poll, lock_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    poll = _due(open_window_poll)
    _run(lock_dir)
    capsys.readouterr()
    call_command("run_tally", str(poll.pk))
    document = json.loads(capsys.readouterr().out)
    assert document["poll_id"] == str(poll.pk)
    assert document["ballot_count"] == 2
    assert document["winner"] == "a"


def test_run_tally_refuses_a_poll_that_is_not_closed(open_window_poll: Poll) -> None:
    from django.core.management.base import CommandError

    force_open(open_window_poll)
    with pytest.raises(CommandError, match="clos"):
        call_command("run_tally", str(open_window_poll.pk))
    with pytest.raises(CommandError, match="introuvable"):
        call_command("run_tally", "00000000-0000-0000-0000-000000000000")
