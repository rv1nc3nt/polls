# SPDX-License-Identifier: 0BSD
"""One elector listed twice on the roll, and the double vote that makes possible.

The import collapses rows that normalise to the same name and date of birth
(R-4.6). It cannot collapse Claire Moreau, whose birth name is on one row and
whose married name, Blanc, is on another: two snapshot entries, two channel
indicators, and nothing on either that stops a paper ballot on the second after
an online vote on the first. No software can decide from the record alone that
they are one person (R-8.3); what the screens must do is say so to the person
who can ask. Screen 5 warns and holds the ballot until the operator confirms
the identity with the elector present; screen 4 shows, beside each entry an
applicant could be bound to, whether it has already voted.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.audit.models import Action, AuditEvent, Reason
from apps.backoffice import paper, review
from apps.ballots import services as ballots
from apps.ballots.models import Ballot
from apps.core.models import PollRole, Role, User
from apps.elections.models import Poll, PollOption, RollEntry, WorkingRollEntry
from apps.registrations import services as registrations
from apps.registrations.models import Channel, Registration, RegistrationState
from tests.conftest import force_open

STRICT = {"order": "a,b,c", "rank_a": "1", "rank_b": "2", "rank_c": "3"}


def _roll_entry(birth_name: str, first_names: str, dob: str) -> None:
    day, month, year = dob.split("/")
    WorkingRollEntry.objects.create(
        birth_name=birth_name,
        first_names=first_names,
        date_of_birth=dob,
        date_of_birth_parsed=f"{year}-{month}-{day}",
        list_types=["principale"],
    )


@pytest.fixture
def poll(db: None) -> Poll:
    now = timezone.now()
    poll = Poll.objects.create(
        title_i18n={"fr": "Aménagement"},
        description_i18n={"fr": "Propositions."},
        languages=["fr"],
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
    )
    for position, option_id in enumerate(["a", "b", "c"]):
        PollOption.objects.create(
            poll=poll, option_id=option_id, label_i18n={"fr": option_id.upper()}, position=position
        )
    _roll_entry("Moreau", "Claire", "02/02/1980")
    _roll_entry("Blanc", "Claire Anne", "02/02/1980")  # the same woman, listed again
    _roll_entry("Moreau", "Julie", "02/02/1980")  # her twin: a different person
    force_open(poll)
    return Poll.objects.get(pk=poll.pk)


@pytest.fixture
def operator(poll: Poll) -> User:
    user = User.objects.create_user(username="op", password="x", full_name="Op")
    PollRole.objects.create(poll=poll, user=user, role=Role.ENTRY_OPERATOR)
    PollRole.objects.create(poll=poll, user=user, role=Role.POLL_ADMIN)
    return user


def _entry(poll: Poll, birth_name: str, first_names: str) -> RollEntry:
    return RollEntry.objects.get(poll=poll, birth_name=birth_name, first_names=first_names)


def _votes_online_as_moreau(poll: Poll) -> None:
    registration, token = registrations.register(
        poll,
        {
            "last_name": "Moreau",
            "first_names": "Claire",
            "date_of_birth": "02/02/1980",
            "email": "claire@example.fr",
            "declared_on_honour": "on",
        },
        language="fr",
    )
    assert token is not None
    assert registration.roll_entry == _entry(poll, "Moreau", "Claire")
    registrations.confirm_mailbox(registration)
    ballots.cast_online(poll, token, [["a"], ["b"], ["c"]])


def _key(client: Client, poll: Poll, entry: RollEntry, **extra: str) -> str:
    response = client.post(
        f"/fr/mairie/scrutin/{poll.pk}/bulletin-papier/",
        {"roll_entry": str(entry.pk), "action": "record", **STRICT, **extra},
    )
    return response.content.decode() if response.status_code == 200 else response["Location"]


def test_the_look_alike_of_an_online_voter_is_flagged_and_the_twin_is_not(poll: Poll) -> None:
    _votes_online_as_moreau(poll)
    flagged = paper.voted_look_alikes(poll, _entry(poll, "Blanc", "Claire Anne"))
    assert [(a.entry.birth_name, a.channel) for a in flagged] == [("Moreau", Channel.ONLINE)]
    # A shared date of birth alone is not enough: a twin has her own forename.
    assert paper.voted_look_alikes(poll, _entry(poll, "Moreau", "Julie")) == []


def test_screen_5_holds_the_second_ballot_until_identity_is_confirmed(
    poll: Poll, operator: User
) -> None:
    _votes_online_as_moreau(poll)
    client = Client()
    client.force_login(operator)
    blanc = _entry(poll, "Blanc", "Claire Anne")

    shown = client.post(
        f"/fr/mairie/scrutin/{poll.pk}/bulletin-papier/", {"roll_entry": str(blanc.pk)}
    ).content.decode()
    assert "Une entrée très proche a déjà voté" in shown
    assert "a voté en ligne" in shown

    refused = _key(client, poll, blanc)
    assert "confirmation d&#x27;identité" in refused or "confirmation d'identité" in refused
    assert not Ballot.objects.filter(poll=poll, source="paper").exists()

    # Two different people after all, settled at the counter (R-8.3): recorded,
    # and the log says the identity was confirmed in person.
    recorded = _key(client, poll, blanc, identity_confirmed="1")
    assert "/recu/" in recorded
    event = AuditEvent.objects.get(poll=poll, action=Action.PAPER_BALLOT_CREATED)
    assert event.reason == Reason.IDENTITY_CONFIRMED_AT_MAIRIE


def test_screen_5_does_not_stop_the_twin(poll: Poll, operator: User) -> None:
    _votes_online_as_moreau(poll)
    client = Client()
    client.force_login(operator)
    assert "/recu/" in _key(client, poll, _entry(poll, "Moreau", "Julie"))


def test_screen_4_shows_which_candidate_entries_have_voted(poll: Poll, operator: User) -> None:
    """She registers again under her married name with a mistyped forename, so
    no single match is found and a poll admin picks the entry (R-5.4). The entry
    she already voted on is marked; approval onto the look-alike would give her
    a second vote, and the admin now sees that before choosing."""
    _votes_online_as_moreau(poll)
    applicant, token = registrations.register(
        poll,
        {
            "last_name": "Blanc",
            "first_names": "Clara",
            "date_of_birth": "02/02/1980",
            "email": "c.blanc@example.fr",
            "declared_on_honour": "on",
        },
        language="fr",
    )
    assert token is None and applicant.state == RegistrationState.PENDING_REVIEW

    marked = {
        m.entry.birth_name + " " + m.entry.first_names: m.channel
        for m in review.near_matches(applicant)
    }
    assert marked["Moreau Claire"] == Channel.ONLINE
    assert marked["Blanc Claire Anne"] is None

    client = Client()
    client.force_login(operator)
    page = client.get(f"/fr/mairie/scrutin/{poll.pk}/inscriptions/").content.decode()
    assert "a voté en ligne" in page


def test_screen_4_does_not_mark_a_cleared_paper_shell(poll: Poll, operator: User) -> None:
    """The shell a deleted paper ballot leaves is no elector's registration; an
    approval takes it over (decision log #27), so it is not shown as taken."""
    julie = _entry(poll, "Moreau", "Julie")
    ballot = ballots.enter_paper(poll, str(julie.pk), [["a"], ["b"], ["c"]], str(operator.pk), "fr")
    ballots.delete_paper(ballot, str(operator.pk), Reason.KEYING_ERROR, "")
    shell = Registration.objects.get(poll=poll, roll_entry=julie)
    assert shell.channel == Channel.NONE and shell.email_canonical == ""
    assert paper.channels_by_entry(poll, [julie]) == {}
