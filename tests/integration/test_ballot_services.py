# SPDX-License-Identifier: 0BSD
"""The §6.4 paper-ballot services: entry, correction, deletion, countersignature.

What matters here is the discipline the screens will lean on: turnout moves on
``Registration.channel`` and never a ballot count (INV-5), the R-9.3 override is
recorded but never counted (D4), a correction supersedes rather than overwrites
(R-7.2), and every write is refused outside the paper keying window (INV-2).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import Action, AuditEvent, Reason
from apps.ballots import services
from apps.ballots.models import Ballot, BallotStatus, PaperBallotLink
from apps.ballots.ranking import BallotRefused
from apps.core.models import User
from apps.elections.models import Poll, RollEntry
from apps.elections.windows import WindowClosed
from apps.registrations.models import Channel, Registration, RegistrationState

STRICT = [["a"], ["b"], ["c"]]


@pytest.fixture
def operator(db: None) -> User:
    return User.objects.create_user(username="op1", password="x", full_name="Op Un")


@pytest.fixture
def second_operator(db: None) -> User:
    return User.objects.create_user(username="op2", password="x", full_name="Op Deux")


def _entry(poll: Poll) -> RollEntry:
    return RollEntry.objects.get(poll=poll)


def _events(poll: Poll, action: str) -> list[AuditEvent]:
    return list(AuditEvent.objects.filter(poll=poll, action=action))


# --- enter_paper -------------------------------------------------------------


def test_enter_paper_for_an_offline_elector(open_paper_poll: Poll, operator: User) -> None:
    entry = _entry(open_paper_poll)
    ballot = services.enter_paper(open_paper_poll, str(entry.pk), STRICT, str(operator.pk), "fr")

    assert ballot.status == BallotStatus.LIVE
    assert ballot.ranking == STRICT
    link = PaperBallotLink.objects.get(ballot=ballot)
    assert link.roll_entry_id == entry.pk
    assert link.operator_id == operator.pk
    assert link.language == "fr"

    registration = Registration.objects.get(poll=open_paper_poll, roll_entry=entry)
    assert registration.channel == Channel.PAPER
    assert registration.state == RegistrationState.ACTIVE
    assert registration.has_voted

    (event,) = _events(open_paper_poll, Action.PAPER_BALLOT_CREATED)
    assert event.actor_id == operator.pk
    assert event.reason == ""


def test_enter_paper_logs_the_reason_when_identity_was_confirmed_in_person(
    open_paper_poll: Poll, operator: User
) -> None:
    entry = _entry(open_paper_poll)
    services.enter_paper(
        open_paper_poll, str(entry.pk), STRICT, str(operator.pk), "fr", identity_confirmed=True
    )
    (event,) = _events(open_paper_poll, Action.PAPER_BALLOT_CREATED)
    assert event.reason == Reason.IDENTITY_CONFIRMED_AT_MAIRIE


def test_enter_paper_writes_pending_when_the_poll_requires_countersign(
    paper_poll_countersign: Poll, operator: User
) -> None:
    entry = _entry(paper_poll_countersign)
    ballot = services.enter_paper(
        paper_poll_countersign, str(entry.pk), STRICT, str(operator.pk), "fr"
    )
    assert ballot.status == BallotStatus.PENDING_COUNTERSIGN
    assert not Ballot.live.filter(poll=paper_poll_countersign).exists()
    # D2: the channel indicator moves at entry, not at countersignature.
    assert Registration.objects.get(poll=paper_poll_countersign).channel == Channel.PAPER


def test_enter_paper_refuses_a_second_entry_for_the_same_elector(
    open_paper_poll: Poll, operator: User
) -> None:
    entry = _entry(open_paper_poll)
    services.enter_paper(open_paper_poll, str(entry.pk), STRICT, str(operator.pk), "fr")
    with pytest.raises(BallotRefused, match="rectification"):
        services.enter_paper(
            open_paper_poll, str(entry.pk), [["c"], ["b"], ["a"]], str(operator.pk), "fr"
        )


def test_enter_paper_validates_the_ranking_server_side(
    open_paper_poll: Poll, operator: User
) -> None:
    """T-29: a ranking the browser would not allow, posted straight through."""
    entry = _entry(open_paper_poll)
    with pytest.raises(BallotRefused):
        services.enter_paper(open_paper_poll, str(entry.pk), [["a"], ["b"]], str(operator.pk), "fr")


def test_enter_paper_is_refused_after_the_keying_deadline(
    open_paper_poll: Poll, operator: User
) -> None:
    entry = _entry(open_paper_poll)
    past = timezone.now() - timedelta(minutes=1)
    Poll.objects.filter(pk=open_paper_poll.pk).update(closes_at=past, paper_entry_deadline=past)
    with pytest.raises(WindowClosed):
        services.enter_paper(
            Poll.objects.get(pk=open_paper_poll.pk), str(entry.pk), STRICT, str(operator.pk), "fr"
        )


def test_enter_paper_still_works_after_online_voting_closes(
    open_paper_poll: Poll, operator: User
) -> None:
    """T-56: keying is transcription; the window runs to ``paper_entry_deadline``."""
    entry = _entry(open_paper_poll)
    now = timezone.now()
    Poll.objects.filter(pk=open_paper_poll.pk).update(
        closes_at=now - timedelta(hours=1), paper_entry_deadline=now + timedelta(days=1)
    )
    ballot = services.enter_paper(
        Poll.objects.get(pk=open_paper_poll.pk), str(entry.pk), STRICT, str(operator.pk), "fr"
    )
    assert ballot.status == BallotStatus.LIVE
    assert Registration.objects.get(poll=open_paper_poll).channel == Channel.PAPER


# --- enter_paper: the R-9.3 collision override ------------------------------


def _voted_online(poll: Poll, entry: RollEntry) -> Registration:
    return Registration.objects.create(
        poll=poll,
        roll_entry=entry,
        state=RegistrationState.ACTIVE,
        channel=Channel.ONLINE,
        declared_last_name="Dupont",
        declared_first_names="Émile",
        declared_dob="12/05/1970",
        email="e@example.fr",
        email_canonical="e@example.fr",
    )


def test_collision_override_is_refused_without_a_reason(
    open_paper_poll: Poll, operator: User
) -> None:
    entry = _entry(open_paper_poll)
    _voted_online(open_paper_poll, entry)
    with pytest.raises(BallotRefused, match="déjà voté en ligne"):
        services.enter_paper(open_paper_poll, str(entry.pk), STRICT, str(operator.pk), "fr")


def test_collision_override_records_but_does_not_count_the_paper_ballot(
    open_paper_poll: Poll, operator: User
) -> None:
    entry = _entry(open_paper_poll)
    registration = _voted_online(open_paper_poll, entry)

    ballot = services.enter_paper(
        open_paper_poll,
        str(entry.pk),
        STRICT,
        str(operator.pk),
        "fr",
        collision_reason=Reason.VOTED_ONLINE_ALREADY,
        note="électeur insistant, formulaire papier classé",
    )

    assert ballot.status == BallotStatus.NOT_IN_FORCE_COLLISION
    assert not Ballot.live.filter(poll=open_paper_poll).exists()
    registration.refresh_from_db()
    assert registration.channel == Channel.ONLINE  # the online ballot still stands

    (event,) = _events(open_paper_poll, Action.CHANNEL_COLLISION_OVERRIDE)
    assert event.reason == Reason.VOTED_ONLINE_ALREADY
    assert event.object_ref == f"ballot:{ballot.pk}"
    # §10: prose lives on the row the purge takes, not on the event.
    assert "insistant" not in str(event.before) + str(event.after)
    assert (
        PaperBallotLink.objects.get(ballot=ballot).note
        == "électeur insistant, formulaire papier classé"
    )


# --- correct_paper ---------------------------------------------------------


def _keyed(poll: Poll, operator: User) -> Ballot:
    return services.enter_paper(poll, str(_entry(poll).pk), STRICT, str(operator.pk), "fr")


def test_correct_paper_supersedes_and_logs_before_after(
    open_paper_poll: Poll, operator: User
) -> None:
    original = _keyed(open_paper_poll, operator)
    new = services.correct_paper(
        original, [["b"], ["a"], ["c"]], str(operator.pk), Reason.KEYING_ERROR, "inversion a/b"
    )

    original.refresh_from_db()
    assert original.status == BallotStatus.SUPERSEDED
    assert new.version == 2
    assert new.tracking_code == original.tracking_code
    assert Ballot.live.filter(poll=open_paper_poll).count() == 1

    (event,) = _events(open_paper_poll, Action.PAPER_BALLOT_CORRECTED)
    assert event.reason == Reason.KEYING_ERROR
    assert event.before["ranking"] == STRICT
    assert event.after["ranking"] == [["b"], ["a"], ["c"]]
    assert PaperBallotLink.objects.get(ballot=new).note == "inversion a/b"


def test_correct_paper_needs_a_reason(open_paper_poll: Poll, operator: User) -> None:
    ballot = _keyed(open_paper_poll, operator)
    with pytest.raises(BallotRefused, match="motif"):
        services.correct_paper(ballot, [["b"], ["a"], ["c"]], str(operator.pk), "", "")


def test_correct_paper_refuses_a_superseded_row(open_paper_poll: Poll, operator: User) -> None:
    ballot = _keyed(open_paper_poll, operator)
    v2 = services.correct_paper(
        ballot, [["b"], ["a"], ["c"]], str(operator.pk), Reason.KEYING_ERROR, ""
    )
    ballot.refresh_from_db()
    with pytest.raises(BallotRefused):
        services.correct_paper(ballot, STRICT, str(operator.pk), Reason.KEYING_ERROR, "")
    assert v2.status == BallotStatus.LIVE


def test_correction_is_idempotent_on_the_live_count(open_paper_poll: Poll, operator: User) -> None:
    """T-35, sequentially: two corrections, still exactly one live version."""
    ballot = _keyed(open_paper_poll, operator)
    v2 = services.correct_paper(
        ballot, [["b"], ["a"], ["c"]], str(operator.pk), Reason.KEYING_ERROR, ""
    )
    services.correct_paper(v2, [["c"], ["b"], ["a"]], str(operator.pk), Reason.KEYING_ERROR, "")
    live = Ballot.live.filter(poll=open_paper_poll)
    assert live.count() == 1
    assert live.get().version == 3


# --- delete_paper --------------------------------------------------------


def test_delete_paper_reopens_online_voting(open_paper_poll: Poll, operator: User) -> None:
    ballot = _keyed(open_paper_poll, operator)
    entry = _entry(open_paper_poll)
    assert Registration.objects.get(poll=open_paper_poll, roll_entry=entry).channel == Channel.PAPER

    deleted = services.delete_paper(ballot, str(operator.pk), Reason.VOTER_REQUEST, "à la demande")

    assert deleted.status == BallotStatus.DELETED
    assert not Ballot.live.filter(poll=open_paper_poll).exists()
    assert Registration.objects.get(poll=open_paper_poll, roll_entry=entry).channel == Channel.NONE

    (event,) = _events(open_paper_poll, Action.PAPER_BALLOT_DELETED)
    assert event.reason == Reason.VOTER_REQUEST
    assert event.before == {"status": BallotStatus.LIVE, "channel": "paper"}
    assert event.after == {"status": BallotStatus.DELETED, "channel": "none"}


def test_delete_paper_needs_a_reason(open_paper_poll: Poll, operator: User) -> None:
    ballot = _keyed(open_paper_poll, operator)
    with pytest.raises(BallotRefused, match="motif"):
        services.delete_paper(ballot, str(operator.pk), "", "")


# --- countersign -------------------------------------------------------


def test_countersign_makes_a_pending_entry_live(
    paper_poll_countersign: Poll, operator: User, second_operator: User
) -> None:
    ballot = services.enter_paper(
        paper_poll_countersign,
        str(_entry(paper_poll_countersign).pk),
        STRICT,
        str(operator.pk),
        "fr",
    )
    live = services.countersign(ballot, str(second_operator.pk))

    assert live.status == BallotStatus.LIVE
    assert Ballot.live.filter(poll=paper_poll_countersign).count() == 1
    assert PaperBallotLink.objects.get(ballot=live).countersigned_by_id == second_operator.pk
    (event,) = _events(paper_poll_countersign, Action.PAPER_BALLOT_COUNTERSIGNED)
    assert event.actor_id == second_operator.pk


def test_countersign_refuses_the_operator_who_keyed_it(
    paper_poll_countersign: Poll, operator: User
) -> None:
    ballot = services.enter_paper(
        paper_poll_countersign,
        str(_entry(paper_poll_countersign).pk),
        STRICT,
        str(operator.pk),
        "fr",
    )
    with pytest.raises(BallotRefused, match="second opérateur"):
        services.countersign(ballot, str(operator.pk))


def test_countersign_refuses_a_ballot_that_is_not_pending(
    open_paper_poll: Poll, operator: User, second_operator: User
) -> None:
    ballot = _keyed(open_paper_poll, operator)  # LIVE, no countersign required
    with pytest.raises(BallotRefused, match="attente de contreseing"):
        services.countersign(ballot, str(second_operator.pk))


def test_countersign_still_works_after_online_voting_closes(
    paper_poll_countersign: Poll, operator: User, second_operator: User
) -> None:
    """T-56: countersignature is a ballot write and gets the paper window."""
    ballot = services.enter_paper(
        paper_poll_countersign,
        str(_entry(paper_poll_countersign).pk),
        STRICT,
        str(operator.pk),
        "fr",
    )
    now = timezone.now()
    Poll.objects.filter(pk=paper_poll_countersign.pk).update(
        closes_at=now - timedelta(hours=1), paper_entry_deadline=now + timedelta(days=1)
    )
    live = services.countersign(Ballot.objects.get(pk=ballot.pk), str(second_operator.pk))
    assert live.status == BallotStatus.LIVE
