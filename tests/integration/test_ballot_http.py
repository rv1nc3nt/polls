# SPDX-License-Identifier: 0BSD
"""The voter-facing online ballot flow (§6.3).

One link from the confirmation mail confirms the mailbox and opens the ballot;
casting flips ``Registration.channel`` and never a ballot count (INV-5); the
token is in the URL for the cast interaction only and never in the session (§7);
following the modification link lands token-free with only a ``ballot_hash`` to
work from (T-21).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.core import mail as django_mail
from django.test import Client
from django.utils import timezone

from apps.ballots import services as ballot_services
from apps.ballots.models import Ballot, BallotSource, BallotStatus
from apps.core.codes import format_tracking_code
from apps.core.models import User
from apps.core.types import Token, TrackingCode
from apps.elections.models import Poll, PollOption, RollEntry, WorkingRollEntry
from apps.elections.transitions import open_poll
from apps.registrations import services
from apps.registrations.models import Channel, Registration, RegistrationState

FORM = {
    "last_name": "Dupont",
    "first_names": "Émile",
    "date_of_birth": "12/05/1970",
    "email": "emile.dupont@example.fr",
    "declared_on_honour": "on",
}
STRICT = {"order": "a,b,c", "rank_a": "1", "rank_b": "2", "rank_c": "3"}


@pytest.fixture
def live_poll(open_window_poll: Poll) -> Poll:
    open_poll(open_window_poll)
    return Poll.objects.get(pk=open_window_poll.pk)


@pytest.fixture
def no_modify_poll(db: None) -> Poll:
    """``allow_ballot_modification`` is frozen at creation (INV-6), so this is
    built rather than derived from ``live_poll``."""
    now = timezone.now()
    poll = Poll.objects.create(
        title_i18n={"fr": "Scrutin sans modification"},
        description_i18n={"fr": "Deux propositions."},
        languages=["fr"],
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
        allow_ballot_modification=False,
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
    open_poll(poll)
    return Poll.objects.get(pk=poll.pk)


def _register(poll: Poll, **over: str) -> tuple[Registration, Token]:
    registration, token = services.register(poll, {**FORM, **over}, language="fr")
    assert token is not None
    return registration, token


def _access_url(poll: Poll, token: Token) -> str:
    return f"/fr/bulletin/{poll.pk}/acces/{token.reveal()}/"


# --- Arrival and the token rules -------------------------------------------


def test_the_link_confirms_the_mailbox_and_serves_the_ballot(
    client: Client, live_poll: Poll
) -> None:
    registration, token = _register(live_poll)
    assert registration.state == RegistrationState.PENDING_EMAIL

    response = client.get(_access_url(live_poll, token))

    assert response.status_code == 200
    assert response["Referrer-Policy"] == "no-referrer"
    assert response["Cache-Control"] == "no-store"
    body = response.content.decode()
    assert "Valider mon bulletin" in body
    registration.refresh_from_db()
    assert registration.state == RegistrationState.ACTIVE


def test_an_invalid_token_is_a_dead_end_without_a_stack_trace(
    client: Client, live_poll: Poll
) -> None:
    response = client.get(f"/fr/bulletin/{live_poll.pk}/acces/NOTATOKEN/")
    assert response.status_code == 404
    assert "Lien non valide" in response.content.decode()


def test_the_session_never_holds_the_token(client: Client, live_poll: Poll) -> None:
    """§7: the plaintext token is never persisted, and the session backend is a
    database table. Nothing that identifies the voter is stored either."""
    _registration, token = _register(live_poll)
    client.get(_access_url(live_poll, token))
    client.post(_access_url(live_poll, token), STRICT)

    stored = str(dict(client.session.items()))
    assert token.reveal() not in stored


def test_t21_the_modification_link_lands_token_free_with_only_a_ballot_hash(
    client: Client, live_poll: Poll
) -> None:
    _registration, token = _register(live_poll)
    client.get(_access_url(live_poll, token))
    client.post(_access_url(live_poll, token), STRICT)

    # A second visit: the elector has voted and the poll permits modification.
    response = client.get(_access_url(live_poll, token))
    assert response.status_code == 302
    assert token.reveal() not in response["Location"]
    assert response["Referrer-Policy"] == "no-referrer"

    stored = str(dict(client.session.items()))
    assert token.reveal() not in stored
    # Exactly one identifier survives the redirect: the ballot hash, hex, with
    # no voter reference beside it.
    live = Ballot.live.get(poll=live_poll)
    assert live.ballot_hash is not None
    assert live.ballot_hash.hex() in stored

    assert client.get(response["Location"]).status_code == 200


# --- Casting -------------------------------------------------------------------


def test_casting_writes_one_live_ballot_and_flips_the_channel(
    client: Client,
    live_poll: Poll,
    django_capture_on_commit_callbacks: Callable[..., Any],
) -> None:
    registration, token = _register(live_poll)
    client.get(_access_url(live_poll, token))

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(_access_url(live_poll, token), STRICT)

    assert response.status_code == 302
    ballots = Ballot.objects.filter(poll=live_poll)
    assert ballots.count() == 1
    ballot = ballots.get()
    assert ballot.status == BallotStatus.LIVE
    assert ballot.source == BallotSource.ONLINE
    assert ballot.ranking == [["a"], ["b"], ["c"]]
    assert ballot.ballot_hash is not None  # modification is on

    registration.refresh_from_db()
    assert registration.channel == Channel.ONLINE

    receipt = client.get(response["Location"])
    assert "enregistré" in receipt.content.decode()
    assert len(django_mail.outbox) == 1
    assert registration.email in django_mail.outbox[0].to


def test_t29_a_ranking_that_breaks_the_constraints_is_refused_server_side(
    client: Client, live_poll: Poll
) -> None:
    """``live_poll`` requires a complete ranking; an incomplete one posted
    straight to the endpoint is rejected and no ballot is written."""
    _registration, token = _register(live_poll)
    client.get(_access_url(live_poll, token))

    response = client.post(_access_url(live_poll, token), {"order": "a,b,c", "rank_a": "1"})
    assert response.status_code == 200
    assert Ballot.objects.filter(poll=live_poll).count() == 0


# --- Modification ------------------------------------------------------------


def _modify(client: Client, poll: Poll, token: Token, data: dict[str, str]) -> Any:
    client.get(_access_url(poll, token))  # sets the ballot_hash session entry
    return client.post(f"/fr/bulletin/{poll.pk}/modifier/", data)


def test_t1_cast_then_modified_three_times_keeps_one_live_and_the_code(
    client: Client, live_poll: Poll
) -> None:
    _registration, token = _register(live_poll)
    client.get(_access_url(live_poll, token))
    client.post(_access_url(live_poll, token), STRICT)
    code = Ballot.live.get(poll=live_poll).tracking_code

    for ranks in (
        {"order": "a,b,c", "rank_a": "2", "rank_b": "1", "rank_c": "3"},
        {"order": "a,b,c", "rank_a": "3", "rank_b": "2", "rank_c": "1"},
        {"order": "a,b,c", "rank_a": "1", "rank_b": "3", "rank_c": "2"},
    ):
        assert _modify(client, live_poll, token, ranks).status_code == 302

    chain = Ballot.objects.filter(poll=live_poll).order_by("version")
    assert chain.count() == 4
    assert [b.version for b in chain] == [1, 2, 3, 4]
    assert {b.tracking_code for b in chain} == {code}
    assert Ballot.live.filter(poll=live_poll).count() == 1
    assert Ballot.live.get(poll=live_poll).ranking == [["a"], ["c"], ["b"]]


def test_the_modify_form_is_prefilled_with_the_current_ranking(
    client: Client, live_poll: Poll
) -> None:
    _registration, token = _register(live_poll)
    client.get(_access_url(live_poll, token))
    client.post(
        _access_url(live_poll, token),
        {"order": "a,b,c", "rank_a": "3", "rank_b": "1", "rank_c": "2"},
    )
    client.get(_access_url(live_poll, token))

    body = client.get(f"/fr/bulletin/{live_poll.pk}/modifier/").content.decode()
    # The select for option A has "3" selected, matching the ballot just cast.
    assert '<option value="3" selected>3</option>' in body


def test_modifying_sends_no_mail(
    client: Client,
    live_poll: Poll,
    django_capture_on_commit_callbacks: Callable[..., Any],
) -> None:
    """R-7.4 forbids a ballot → registration path, so a modification cannot mail
    a receipt — recorded in docs/spec-divergences.md."""
    _registration, token = _register(live_poll)
    client.get(_access_url(live_poll, token))
    with django_capture_on_commit_callbacks(execute=True):
        client.post(_access_url(live_poll, token), STRICT)
    assert len(django_mail.outbox) == 1

    with django_capture_on_commit_callbacks(execute=True):
        _modify(
            client,
            live_poll,
            token,
            {"order": "a,b,c", "rank_a": "1", "rank_b": "3", "rank_c": "2"},
        )
    assert len(django_mail.outbox) == 1  # unchanged


# --- No-modification poll (R-7.1, R-7.4 bis, T-48) --------------------------


def test_t48_no_modification_means_no_ballot_hash_and_a_spent_link(
    client: Client, no_modify_poll: Poll
) -> None:
    _registration, token = _register(no_modify_poll)
    client.get(_access_url(no_modify_poll, token))
    client.post(_access_url(no_modify_poll, token), STRICT)

    ballots = Ballot.objects.filter(poll=no_modify_poll)
    assert ballots.count() == 1
    assert ballots.get().ballot_hash is None
    assert not Ballot.objects.filter(poll=no_modify_poll, ballot_hash__isnull=False).exists()

    # The link is now spent: a later visit is a dead end, not a form.
    again = client.get(_access_url(no_modify_poll, token))
    assert again.status_code == 302
    assert "/info/enregistre/" in again["Location"]
    assert "déjà enregistré" in client.get(again["Location"]).content.decode()


# --- A paper voter attempting to vote online (R-9.2, T-7) ------------------


def test_t7_a_paper_voter_is_directed_to_the_mairie(client: Client, live_poll: Poll) -> None:
    registration, token = _register(live_poll)
    client.get(_access_url(live_poll, token))  # activate

    operator = User.objects.create_user(username="op", password="x", full_name="Op")
    entry = RollEntry.objects.get(poll=live_poll)
    ballot_services.enter_paper(
        live_poll, str(entry.pk), [["a"], ["b"], ["c"]], str(operator.pk), "fr"
    )
    registration.refresh_from_db()
    assert registration.channel == Channel.PAPER

    response = client.get(_access_url(live_poll, token))
    assert response.status_code == 302
    assert "/info/mairie/" in response["Location"]
    assert Ballot.objects.filter(poll=live_poll, source=BallotSource.ONLINE).count() == 0


# --- Per-voter display order (R-6.2, T-30) --------------------------------------


def test_t30_the_option_order_is_shuffled_per_voter(live_poll: Poll) -> None:
    from apps.ballots.forms import RankingForm

    seen = {tuple(RankingForm(poll=live_poll, language="fr")._display_order) for _ in range(20)}
    assert len(seen) > 1, "20 renders should not all share one order"


# --- Keyboard / screen-reader completability (R-6.3, R-14.1, T-13) -------------


def test_t13_the_ballot_is_completable_by_keyboard_and_screen_reader_alone(
    client: Client,
    live_poll: Poll,
    django_capture_on_commit_callbacks: Callable[..., Any],
) -> None:
    """T-13: the automatable half. The ranking is native ``<select>`` controls,
    one per proposition, each with its own ``<label>``; the ballot content
    carries no script and no drag affordance, so a keyboard or screen-reader
    user depends on neither. A plain POST of the values the page offers writes
    the ballot. The assistive-technology pass itself stays a manual step (§12).

    "No script" is asserted over the document body, not the whole page: the
    shared ``<head>`` loads the cosmetic theme-toggle asset (§14 permits minimal
    vanilla JavaScript), which the ballot neither uses nor degrades without.
    Anything enhancing the ranking would live in the body and still fail this.
    """
    _registration, token = _register(live_poll)
    page = client.get(_access_url(live_poll, token)).content.decode()
    body = page.split("<main", 1)[1]

    # No pointer-only affordance and no scripting to depend on.
    assert "<script" not in body
    assert "draggable" not in page
    assert 'type="range"' not in page

    # One labelled native select per option, plus the pinned-order hidden field.
    select_names = sorted(re.findall(r'<select[^>]*\bname="(rank_[a-z]+)"', page))
    assert select_names == ["rank_a", "rank_b", "rank_c"]
    for name in select_names:
        field_id = f"id_{name}"
        assert f'<label for="{field_id}">' in page
        assert f'id="{field_id}"' in page
    assert re.search(r'<input[^>]*type="hidden"[^>]*name="order"', page) is not None

    # Complete it using only what the page presents: the shuffled display order
    # from the hidden field, each option ranked by its position in it.
    order_match = re.search(r'name="order"[^>]*\bvalue="([^"]*)"', page)
    assert order_match is not None
    display_order = order_match.group(1).split(",")
    assert sorted(display_order) == ["a", "b", "c"]
    data = {"order": ",".join(display_order)}
    for rank, option_id in enumerate(display_order, start=1):
        data[f"rank_{option_id}"] = str(rank)

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(_access_url(live_poll, token), data)
    assert response.status_code == 302

    ballot = Ballot.live.get(poll=live_poll)
    assert ballot.ranking == [[option_id] for option_id in display_order]

    receipt = client.get(response["Location"]).content.decode()
    assert "enregistré" in receipt
    assert format_tracking_code(TrackingCode(ballot.tracking_code)) in receipt
    assert "<script" not in receipt.split("<main", 1)[1]
