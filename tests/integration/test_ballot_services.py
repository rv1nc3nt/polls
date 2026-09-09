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
from apps.core.types import Token
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


# --- enter_paper: an online ballot blocks paper entry ---------------------


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


def test_an_online_ballot_refuses_a_paper_entry(open_paper_poll: Poll, operator: User) -> None:
    """§7 makes the online ballot unlocatable, so it can neither be replaced nor
    counted beside a paper one — the entry is refused outright (divergence from
    R-9.3 / T-8, docs/spec-divergences.md)."""
    entry = _entry(open_paper_poll)
    registration = _voted_online(open_paper_poll, entry)

    with pytest.raises(BallotRefused, match="déjà voté en ligne"):
        services.enter_paper(open_paper_poll, str(entry.pk), STRICT, str(operator.pk), "fr")

    assert not Ballot.objects.filter(poll=open_paper_poll).exists()
    assert not PaperBallotLink.objects.filter(poll=open_paper_poll).exists()
    registration.refresh_from_db()
    assert registration.channel == Channel.ONLINE  # untouched


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


# --- §6.3 online casting and modification -----------------------------------


def _voter(poll: Poll) -> tuple[str, Token]:
    """A confirmed, active registration on ``poll`` and its plaintext token."""
    from apps.registrations import services as registrations

    entry = _entry(poll)
    registration, token = registrations.register(
        poll,
        {
            "last_name": entry.birth_name,
            "first_names": entry.first_names,
            "date_of_birth": entry.date_of_birth,
            "email": "voter@example.fr",
            "declared_on_honour": "on",
        },
        language="fr",
    )
    assert token is not None
    registrations.confirm_mailbox(registration)
    return str(registration.pk), token


def test_cast_online_refuses_after_closes_at(open_paper_poll: Poll) -> None:
    """T-3: the write path checks the clock, not ``Poll.state``."""
    _registration_id, token = _voter(open_paper_poll)
    now = timezone.now()
    Poll.objects.filter(pk=open_paper_poll.pk).update(
        closes_at=now - timedelta(seconds=1), paper_entry_deadline=now - timedelta(seconds=1)
    )
    poll = Poll.objects.get(pk=open_paper_poll.pk)
    with pytest.raises(WindowClosed):
        services.cast_online(poll, token, STRICT)
    assert not Ballot.objects.filter(poll=poll).exists()


def test_cast_online_flips_the_channel_and_stores_a_ballot_hash(open_paper_poll: Poll) -> None:
    registration_id, token = _voter(open_paper_poll)
    result = services.cast_online(open_paper_poll, token, STRICT)

    assert result.ballot.status == BallotStatus.LIVE
    assert result.ballot.ballot_hash is not None
    registration = Registration.objects.get(pk=registration_id)
    assert registration.channel == Channel.ONLINE

    # T-25 at the value level: nothing is common to the two rows.
    voter_digest, ballot_digest = registration.voter_hash, result.ballot.ballot_hash
    assert voter_digest is not None and ballot_digest is not None
    assert bytes(voter_digest) != bytes(ballot_digest)
    assert result.ballot.tracking_code not in {
        registration.declared_last_name,
        str(registration.voter_hash),
    }


def test_a_spent_link_is_refused(open_paper_poll: Poll) -> None:
    """R-7.1: the token is spent on casting; ``channel`` is the guard."""
    _registration_id, token = _voter(open_paper_poll)
    services.cast_online(open_paper_poll, token, STRICT)
    with pytest.raises(BallotRefused):
        services.cast_online(open_paper_poll, token, STRICT)


def test_modify_supersedes_and_keeps_one_live_version(open_paper_poll: Poll) -> None:
    """T-1, T-35 invariant: every modification leaves exactly one live row."""
    _registration_id, token = _voter(open_paper_poll)
    cast = services.cast_online(open_paper_poll, token, STRICT)
    digest = services.online_ballot_hash(open_paper_poll, token)

    v2 = services.modify(open_paper_poll, digest, [["b"], ["a"], ["c"]])
    v3 = services.modify(open_paper_poll, digest, [["c"], ["b"], ["a"]])

    assert [v2.version, v3.version] == [2, 3]
    assert v3.tracking_code == cast.ballot.tracking_code
    assert Ballot.live.filter(poll=open_paper_poll).count() == 1
    assert Ballot.live.get(poll=open_paper_poll).ranking == [["c"], ["b"], ["a"]]
    assert Ballot.objects.filter(poll=open_paper_poll).count() == 3


def test_modify_is_refused_where_the_poll_forbids_it(open_window_poll: Poll) -> None:
    from apps.elections.transitions import open_poll

    Poll.objects.filter(pk=open_window_poll.pk).update(allow_ballot_modification=False)
    open_poll(open_window_poll)
    poll = Poll.objects.get(pk=open_window_poll.pk)

    _registration_id, token = _voter(poll)
    cast = services.cast_online(poll, token, STRICT)
    assert cast.ballot.ballot_hash is None
    with pytest.raises(BallotRefused):
        services.modify(poll, services.online_ballot_hash(poll, token), [["b"], ["a"], ["c"]])
