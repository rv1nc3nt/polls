# SPDX-License-Identifier: 0BSD
"""The public poll page and results page (§6.6, §9).

What they must get right: a draft or sandbox poll is invisible (INV-8, §6.6); a
running count appears only where ``show_live_participation`` is set and nowhere
otherwise (R-11.5, T-20); an extension of the closing date shows on the page
(R-3.4, T-5); and the published results — page, CSV and JSON — are exactly the
live ballot set and the §9 document, so the closure hash recomputes from the
CSV alone (R-11.2, R-11.4).
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.audit.models import Reason
from apps.ballots.models import Ballot, BallotSource
from apps.core.canonical import closure_hash
from apps.core.codes import new_tracking_code
from apps.core.models import User
from apps.elections.closure import live_ballots
from apps.elections.models import Poll, PollOption, WorkingRollEntry
from apps.elections.transitions import close_poll, extend_closes_at, open_poll, publish_poll
from apps.registrations.models import Channel, Registration, RegistrationState


def _make_poll(*, show_live: bool = False, sandbox: bool = False) -> Poll:
    now = timezone.now()
    poll = Poll.objects.create(
        title_i18n={"fr": "Aménagement de la place"},
        description_i18n={"fr": "Trois propositions au choix."},
        languages=["fr"],
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
        show_live_participation=show_live,
        is_sandbox=sandbox,
    )
    for position, option_id in enumerate(["a", "b", "c"]):
        PollOption.objects.create(
            poll=poll, option_id=option_id, label_i18n={"fr": option_id.upper()}, position=position
        )
    WorkingRollEntry.objects.create(
        birth_name="Dupont",
        first_names="Émile",
        date_of_birth="12/05/1970",
        date_of_birth_parsed="1970-05-12",
        list_types=["principale"],
    )
    return poll


def _register(poll: Poll, tag: str, *, channel: str = Channel.NONE) -> None:
    Registration.objects.create(
        poll=poll,
        declared_last_name="Dupont",
        declared_first_names="Émile",
        declared_dob="12/05/1970",
        email=f"{tag}@example.fr",
        email_canonical=f"{tag}@example.fr",
        state=RegistrationState.ACTIVE,
        channel=channel,
    )


def _cast(poll: Poll, rankings: list[list[list[str]]]) -> None:
    for ranking in rankings:
        Ballot.objects.create(
            poll=poll,
            tracking_code=new_tracking_code(),
            ranking=ranking,
            source=BallotSource.ONLINE,
        )


@pytest.fixture
def open_poll_fixture(db: None) -> Poll:
    poll = _make_poll()
    open_poll(poll)
    return Poll.objects.get(pk=poll.pk)


@pytest.fixture
def published_poll(db: None) -> Poll:
    poll = _make_poll()
    open_poll(poll)
    _register(poll, "voter1", channel=Channel.ONLINE)
    _cast(poll, [[["a"], ["b"], ["c"]], [["a"], ["b"], ["c"]]])
    close_poll(poll)
    publish_poll(poll, User.objects.create_user(username="p.admin", password="x"))
    return Poll.objects.get(pk=poll.pk)


# --- the poll page: visibility (§6.6, INV-8) ----------------------------


def test_a_draft_poll_is_not_public(client: Client, db: None) -> None:
    poll = _make_poll()  # never opened
    assert client.get(f"/fr/scrutin/{poll.pk}/").status_code == 404


def test_a_sandbox_poll_is_not_public(client: Client, db: None) -> None:
    poll = _make_poll(sandbox=True)
    open_poll(poll)
    assert client.get(f"/fr/scrutin/{poll.pk}/").status_code == 404
    assert poll.pk  # sanity


def test_the_open_poll_page_shows_the_propositions_and_calendar(
    client: Client, open_poll_fixture: Poll
) -> None:
    body = client.get(f"/fr/scrutin/{open_poll_fixture.pk}/").content.decode()
    assert "Aménagement de la place" in body
    assert "A" in body and "B" in body and "C" in body
    assert "Clôture du vote en ligne" in body
    # R-1.4: the consultative-status statement with the CGCT article reference.
    assert "L1112-15" in body
    # An open poll points the reader at registration.
    assert f"/fr/inscription/{open_poll_fixture.pk}/" in body


def test_a_closed_unpublished_poll_says_the_tally_is_under_way(client: Client, db: None) -> None:
    poll = _make_poll()
    open_poll(poll)
    close_poll(poll)
    body = client.get(f"/fr/scrutin/{poll.pk}/").content.decode()
    assert "dépouillement" in body.lower()
    assert f"/fr/scrutin/{poll.pk}/resultats/" not in body


def test_a_published_poll_page_links_to_the_results(client: Client, published_poll: Poll) -> None:
    body = client.get(f"/fr/scrutin/{published_poll.pk}/").content.decode()
    assert f"/fr/scrutin/{published_poll.pk}/resultats/" in body


# --- participation: shown only where configured (R-11.5, T-20) ---------


def test_turnout_is_absent_by_default(client: Client, open_poll_fixture: Poll) -> None:
    _register(open_poll_fixture, "v1", channel=Channel.ONLINE)
    _register(open_poll_fixture, "v2", channel=Channel.PAPER)
    _register(open_poll_fixture, "v3")
    body = client.get(f"/fr/scrutin/{open_poll_fixture.pk}/").content.decode()
    assert "Participation" not in body
    assert "Bulletins déposés" not in body


def test_turnout_is_shown_when_the_flag_is_set(client: Client, db: None) -> None:
    poll = _make_poll(show_live=True)
    open_poll(poll)
    _register(poll, "v1", channel=Channel.ONLINE)
    _register(poll, "v2", channel=Channel.ONLINE)
    _register(poll, "v3", channel=Channel.PAPER)
    _register(poll, "v4")
    body = client.get(f"/fr/scrutin/{poll.pk}/").content.decode()
    assert "Participation" in body
    assert "Bulletins déposés" in body


def test_no_running_count_leaks_once_the_poll_is_closed(client: Client, db: None) -> None:
    """R-11.5 / §9: after closure the figures belong to the publication, not
    this page — which for a closed-but-unpublished poll means nothing here."""
    poll = _make_poll(show_live=True)
    open_poll(poll)
    _register(poll, "v1", channel=Channel.ONLINE)
    close_poll(poll)
    body = client.get(f"/fr/scrutin/{poll.pk}/").content.decode()
    assert "Bulletins déposés" not in body


# --- extension of the closing date (R-3.4, T-5) -----------------------


def test_a_logged_extension_appears_on_the_page(client: Client, db: None) -> None:
    poll = _make_poll()
    open_poll(poll)
    actor = User.objects.create_user(username="p.admin", password="x", full_name="P. Admin")
    extend_closes_at(
        Poll.objects.get(pk=poll.pk),
        timezone.now() + timedelta(days=5),
        actor,
        Reason.ADMINISTRATIVE_DECISION,
    )
    body = client.get(f"/fr/scrutin/{poll.pk}/").content.decode()
    assert "Report de la clôture" in body
    assert "Clôture repoussée" in body
    assert str(Reason.ADMINISTRATIVE_DECISION.label) in body
    # R-3.4 is about the fact and the reason, not the operator.
    assert "P. Admin" not in body


# --- the results page (§9, R-11.2/4) ----------------------------------


def test_results_are_404_until_published(client: Client, db: None) -> None:
    poll = _make_poll()
    open_poll(poll)
    close_poll(poll)
    assert client.get(f"/fr/scrutin/{poll.pk}/resultats/").status_code == 404


def test_a_sandbox_published_poll_has_no_public_results(client: Client, db: None) -> None:
    poll = _make_poll(sandbox=True)
    open_poll(poll)
    _cast(poll, [[["a"], ["b"], ["c"]]])
    close_poll(poll)
    publish_poll(poll, User.objects.create_user(username="p.admin", password="x"))
    assert client.get(f"/fr/scrutin/{poll.pk}/resultats/").status_code == 404


def test_the_results_page_shows_the_derivation_and_hash(
    client: Client, published_poll: Poll
) -> None:
    body = client.get(f"/fr/scrutin/{published_poll.pk}/resultats/").content.decode()
    assert published_poll.closure_hash is not None
    assert bytes(published_poll.closure_hash).hex() in body
    assert "Matrice des préférences" in body
    assert "Participation, figée à la clôture" in body
    assert "?format=csv" in body
    assert "?format=json" in body
    assert "L1112-15" in body


def test_the_published_csv_is_the_live_set_and_recomputes_the_hash(
    client: Client, published_poll: Poll
) -> None:
    response = client.get(f"/fr/scrutin/{published_poll.pk}/resultats/?format=csv")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert published_poll.closure_hash is not None
    assert bytes(published_poll.closure_hash) == closure_hash(live_ballots(published_poll))


def test_the_published_json_is_the_publication_document(
    client: Client, published_poll: Poll
) -> None:
    response = client.get(f"/fr/scrutin/{published_poll.pk}/resultats/?format=json")
    document = json.loads(response.content)
    assert published_poll.closure_hash is not None
    assert document["closure_hash"] == bytes(published_poll.closure_hash).hex()
    assert document["winner"] == "a"


def test_an_unknown_format_is_404(client: Client, published_poll: Poll) -> None:
    assert client.get(f"/fr/scrutin/{published_poll.pk}/resultats/?format=pdf").status_code == 404
