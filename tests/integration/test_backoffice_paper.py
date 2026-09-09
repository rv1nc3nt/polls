# SPDX-License-Identifier: 0BSD
"""Screens 5–7 of §6.5 over HTTP — saisie, rectification, contreseing.

The services are tested in ``test_ballot_services``; here it is the screens:
that the gate holds, that the R-9.3 interstitial blocks until it is confirmed,
that a correction and a deletion post through, and that the countersign queue
appears only where the poll is configured for it.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.ballots import services as ballots
from apps.ballots.models import Ballot, BallotStatus
from apps.core.models import PollRole, Role, User
from apps.elections.models import Poll, RollEntry
from apps.registrations.models import Channel, Registration, RegistrationState

STRICT = {"order": "a,b,c", "rank_a": "1", "rank_b": "2", "rank_c": "3"}


@pytest.fixture
def op(db: None) -> User:
    return User.objects.create_user(username="op.paper", password="x", full_name="Op Papier")


@pytest.fixture
def op2(db: None) -> User:
    return User.objects.create_user(username="op.two", password="x", full_name="Op Deux")


def _grant(poll: Poll, user: User, role: Role = Role.ENTRY_OPERATOR) -> None:
    PollRole.objects.create(poll=poll, user=user, role=role)


def _base(poll: Poll) -> str:
    return f"/fr/mairie/scrutin/{poll.pk}"


def _entry(poll: Poll) -> RollEntry:
    return RollEntry.objects.get(poll=poll)


# --- Screen 5: saisie ----------------------------------------------------


def test_entry_operator_keys_a_paper_ballot_and_lands_on_the_receipt(
    client: Client, open_paper_poll: Poll, op: User
) -> None:
    _grant(open_paper_poll, op)
    client.force_login(op)
    entry = _entry(open_paper_poll)

    found = client.get(f"{_base(open_paper_poll)}/bulletin-papier/", {"q": "Dupont"})
    assert entry.birth_name in found.content.decode()

    done = client.post(
        f"{_base(open_paper_poll)}/bulletin-papier/",
        {"roll_entry": str(entry.pk), "action": "record", **STRICT},
        follow=True,
    )
    assert done.status_code == 200
    ballot = Ballot.objects.get(poll=open_paper_poll)
    assert ballot.status == BallotStatus.LIVE
    assert ballot.ranking == [["a"], ["b"], ["c"]]
    body = done.content.decode()
    assert "Code de suivi" in body
    assert "reste associé à votre identité" in body  # R-8.2 bis, no signed form
    assert Registration.objects.get(poll=open_paper_poll).channel == Channel.PAPER


def test_the_auditor_role_cannot_reach_the_entry_screen(
    client: Client, open_paper_poll: Poll, op: User
) -> None:
    _grant(open_paper_poll, op, Role.AUDITOR)
    client.force_login(op)
    assert client.get(f"{_base(open_paper_poll)}/bulletin-papier/").status_code == 403


def test_the_collision_interstitial_blocks_until_confirmed(
    client: Client, open_paper_poll: Poll, op: User
) -> None:
    _grant(open_paper_poll, op)
    client.force_login(op)
    entry = _entry(open_paper_poll)
    Registration.objects.create(
        poll=open_paper_poll,
        roll_entry=entry,
        state=RegistrationState.ACTIVE,
        channel=Channel.ONLINE,
        declared_last_name="Dupont",
        declared_first_names="Émile",
        email="e@example.fr",
        email_canonical="e@example.fr",
    )

    shown = client.post(f"{_base(open_paper_poll)}/bulletin-papier/", {"roll_entry": str(entry.pk)})
    assert "déjà voté en ligne" in shown.content.decode()

    # Ranking valid but no confirmation box / reason → refused, nothing written.
    blocked = client.post(
        f"{_base(open_paper_poll)}/bulletin-papier/",
        {"roll_entry": str(entry.pk), "action": "record", **STRICT},
    )
    assert "Confirmez" in blocked.content.decode()
    assert not Ballot.objects.filter(poll=open_paper_poll).exists()

    # With the box and a reason it goes through, not counted.
    client.post(
        f"{_base(open_paper_poll)}/bulletin-papier/",
        {
            "roll_entry": str(entry.pk),
            "action": "record",
            "collision_ack": "1",
            "collision_reason": "voted_online_already",
            **STRICT,
        },
        follow=True,
    )
    ballot = Ballot.objects.get(poll=open_paper_poll)
    assert ballot.status == BallotStatus.NOT_IN_FORCE_COLLISION
    assert not Ballot.live.filter(poll=open_paper_poll).exists()


def test_entry_screen_hands_off_to_screen_6_when_a_paper_ballot_exists(
    client: Client, open_paper_poll: Poll, op: User
) -> None:
    _grant(open_paper_poll, op)
    client.force_login(op)
    entry = _entry(open_paper_poll)
    ballot = ballots.enter_paper(
        open_paper_poll, str(entry.pk), [["a"], ["b"], ["c"]], str(op.pk), "fr"
    )

    landing = client.post(
        f"{_base(open_paper_poll)}/bulletin-papier/", {"roll_entry": str(entry.pk)}
    )
    assert landing.status_code == 302
    assert str(ballot.pk) in landing["Location"]


# --- Screen 6: rectification et suppression -----------------------------


def test_correction_and_deletion_post_through(
    client: Client, open_paper_poll: Poll, op: User
) -> None:
    _grant(open_paper_poll, op)
    client.force_login(op)
    entry = _entry(open_paper_poll)
    ballot = ballots.enter_paper(
        open_paper_poll, str(entry.pk), [["a"], ["b"], ["c"]], str(op.pk), "fr"
    )
    url = f"{_base(open_paper_poll)}/bulletin-papier/{ballot.pk}/"

    corrected = client.post(
        url,
        {
            "action": "correct",
            "reason": "keying_error",
            "order": "a,b,c",
            "rank_a": "2",
            "rank_b": "1",
            "rank_c": "3",
        },
        follow=True,
    )
    assert corrected.status_code == 200
    live = Ballot.live.get(poll=open_paper_poll)
    assert live.version == 2
    assert live.ranking == [["b"], ["a"], ["c"]]

    deleted = client.post(
        f"{_base(open_paper_poll)}/bulletin-papier/{live.pk}/",
        {"action": "delete", "reason": "voter_request"},
        follow=True,
    )
    assert deleted.status_code == 200
    assert not Ballot.live.filter(poll=open_paper_poll).exists()
    assert Registration.objects.get(poll=open_paper_poll).channel == Channel.NONE


def test_a_missing_reason_is_refused(client: Client, open_paper_poll: Poll, op: User) -> None:
    _grant(open_paper_poll, op)
    client.force_login(op)
    entry = _entry(open_paper_poll)
    ballot = ballots.enter_paper(
        open_paper_poll, str(entry.pk), [["a"], ["b"], ["c"]], str(op.pk), "fr"
    )
    response = client.post(
        f"{_base(open_paper_poll)}/bulletin-papier/{ballot.pk}/",
        {"action": "delete", "reason": ""},
    )
    assert "motif est obligatoire" in response.content.decode()
    ballot.refresh_from_db()
    assert ballot.status == BallotStatus.LIVE


# --- Screen 7: contreseing --------------------------------------------


def test_countersign_queue_is_absent_without_the_configuration(
    client: Client, open_paper_poll: Poll, op: User
) -> None:
    _grant(open_paper_poll, op)
    client.force_login(op)
    assert client.get(f"{_base(open_paper_poll)}/contreseing/").status_code == 404


def test_a_second_operator_countersigns_from_the_queue(
    client: Client, paper_poll_countersign: Poll, op: User, op2: User
) -> None:
    _grant(paper_poll_countersign, op)
    _grant(paper_poll_countersign, op2)
    entry = _entry(paper_poll_countersign)
    ballot = ballots.enter_paper(
        paper_poll_countersign, str(entry.pk), [["a"], ["b"], ["c"]], str(op.pk), "fr"
    )

    client.force_login(op2)
    queue = client.get(f"{_base(paper_poll_countersign)}/contreseing/")
    assert ballot.tracking_code in queue.content.decode()

    client.post(
        f"{_base(paper_poll_countersign)}/contreseing/", {"ballot": str(ballot.pk)}, follow=True
    )
    ballot.refresh_from_db()
    assert ballot.status == BallotStatus.LIVE


def test_the_keyer_cannot_countersign_their_own_entry(
    client: Client, paper_poll_countersign: Poll, op: User
) -> None:
    _grant(paper_poll_countersign, op)
    entry = _entry(paper_poll_countersign)
    ballot = ballots.enter_paper(
        paper_poll_countersign, str(entry.pk), [["a"], ["b"], ["c"]], str(op.pk), "fr"
    )
    client.force_login(op)
    response = client.post(
        f"{_base(paper_poll_countersign)}/contreseing/", {"ballot": str(ballot.pk)}, follow=True
    )
    assert "second opérateur" in response.content.decode()
    ballot.refresh_from_db()
    assert ballot.status == BallotStatus.PENDING_COUNTERSIGN
