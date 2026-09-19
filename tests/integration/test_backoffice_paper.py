# SPDX-License-Identifier: 0BSD
"""Screens 5–7 of §6.5 over HTTP — saisie, rectification, contreseing.

The services are tested in ``test_ballot_services``; here it is the screens:
that the gate holds, that the R-9.3 interstitial blocks until it is confirmed,
that a correction and a deletion post through, and that the countersign queue
appears only where the poll is configured for it.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.ballots import services as ballots
from apps.ballots.models import Ballot, BallotStatus, PaperBallotLink
from apps.core.models import PollRole, Role, User
from apps.elections.models import Poll, PollOption, RollEntry, WorkingRollEntry
from apps.registrations.models import Channel, Registration, RegistrationState
from tests.conftest import force_open

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


@pytest.fixture
def bilingual_paper_poll(db: None) -> Poll:
    """A poll enabling French and English, open for paper entry — the
    ``receipt_language`` selector only renders where there is a real choice
    (§3.8)."""
    now = timezone.now()
    poll = Poll.objects.create(
        title_i18n={"fr": "Aménagement", "en": "Development"},
        description_i18n={"fr": "Propositions.", "en": "Options."},
        languages=["fr", "en"],
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
    )
    for position, option_id in enumerate(["a", "b", "c"]):
        PollOption.objects.create(
            poll=poll,
            option_id=option_id,
            label_i18n={"fr": option_id.upper(), "en": option_id.upper()},
            position=position,
        )
    WorkingRollEntry.objects.create(
        birth_name="Dupont",
        first_names="Émile",
        date_of_birth="12/05/1970",
        date_of_birth_parsed="1970-05-12",
        list_types=["principale"],
    )
    force_open(poll)
    return Poll.objects.get(pk=poll.pk)


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


def test_the_receipt_language_is_the_operators_choice_not_their_browsing_locale(
    client: Client, bilingual_paper_poll: Poll, op: User
) -> None:
    """§3.8: "the receipt for a paper ballot uses the language selected by
    the operator at entry" — not ``request.LANGUAGE_CODE``, which answers a
    different question (which translation of *this screen* the operator
    sees). Requesting the French screen while choosing an English receipt
    must store English, proving the two are no longer tied together."""
    _grant(bilingual_paper_poll, op)
    client.force_login(op)
    entry = _entry(bilingual_paper_poll)

    body = client.post(
        f"{_base(bilingual_paper_poll)}/bulletin-papier/",
        {"roll_entry": str(entry.pk), "q": "Dupont"},
    ).content.decode()
    assert 'name="receipt_language"' in body
    assert '<option value="fr" selected>' in body

    client.post(
        f"{_base(bilingual_paper_poll)}/bulletin-papier/",
        {
            "roll_entry": str(entry.pk),
            "action": "record",
            "receipt_language": "en",
            **STRICT,
        },
        follow=True,
    )
    link = PaperBallotLink.objects.get(poll=bilingual_paper_poll)
    assert link.language == "en"


def test_the_receipt_language_defaults_to_the_polls_default_language(
    client: Client, bilingual_paper_poll: Poll, op: User
) -> None:
    """Omitting the field (or an unexpected value, e.g. a language this poll
    never enabled) falls back to the poll's own default — never to whatever
    the operator's browser happens to be showing."""
    _grant(bilingual_paper_poll, op)
    client.force_login(op)
    entry = _entry(bilingual_paper_poll)

    client.post(
        f"{_base(bilingual_paper_poll)}/bulletin-papier/",
        {"roll_entry": str(entry.pk), "action": "record", **STRICT},
        follow=True,
    )
    link = PaperBallotLink.objects.get(poll=bilingual_paper_poll)
    assert link.language == bilingual_paper_poll.default_language == "fr"


def test_no_language_selector_where_the_poll_has_only_one(
    client: Client, open_paper_poll: Poll, op: User
) -> None:
    _grant(open_paper_poll, op)
    client.force_login(op)
    entry = _entry(open_paper_poll)
    body = client.post(
        f"{_base(open_paper_poll)}/bulletin-papier/",
        {"roll_entry": str(entry.pk), "q": "Dupont"},
    ).content.decode()
    assert 'name="receipt_language"' not in body


def test_the_auditor_role_cannot_reach_the_entry_screen(
    client: Client, open_paper_poll: Poll, op: User
) -> None:
    _grant(open_paper_poll, op, Role.AUDITOR)
    client.force_login(op)
    assert client.get(f"{_base(open_paper_poll)}/bulletin-papier/").status_code == 403


def test_an_online_ballot_makes_the_entry_screen_a_dead_end(
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
    body = shown.content.decode()
    assert "déjà voté en ligne" in body
    assert 'name="action" value="record"' not in body  # no way through

    # Even a hand-crafted POST is refused server-side, nothing written.
    forced = client.post(
        f"{_base(open_paper_poll)}/bulletin-papier/",
        {"roll_entry": str(entry.pk), "action": "record", **STRICT},
    )
    assert "déjà voté en ligne" in forced.content.decode()
    assert not Ballot.objects.filter(poll=open_paper_poll).exists()


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
