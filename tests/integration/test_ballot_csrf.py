# SPDX-License-Identifier: 0BSD
"""The ballot routes' CSRF check under their own referrer policy (decision log
#50).

``Referrer-Policy: no-referrer`` makes a browser send ``Origin: null`` with the
ballot form's POST; Django's test client sends no ``Origin`` unless told to,
which is how the HTTP tests missed that no ballot could be cast in a browser.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.test import Client

from apps.ballots.models import Ballot
from apps.core.models import User
from apps.elections.models import Poll
from tests.integration.test_ballot_http import STRICT, _access_url, _register


@pytest.fixture
def live_poll(open_window_poll: Poll) -> Poll:
    from tests.conftest import force_open

    return force_open(open_window_poll)


def _cast(poll: Poll, origin: str) -> Any:
    client = Client(enforce_csrf_checks=True)
    _registration, token = _register(poll)
    url = _access_url(poll, token)
    client.get(url)
    token_value = client.cookies["csrftoken"].value
    return client.post(url, {**STRICT, "csrfmiddlewaretoken": token_value}, HTTP_ORIGIN=origin)


def test_a_cast_with_the_origin_a_browser_sends_is_accepted(
    live_poll: Poll, django_capture_on_commit_callbacks: Callable[..., Any]
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        response = _cast(live_poll, "null")
    assert response.status_code == 302
    assert Ballot.objects.filter(poll=live_poll).count() == 1


def test_another_sites_origin_is_still_refused(live_poll: Poll) -> None:
    assert _cast(live_poll, "https://ailleurs.example").status_code == 403
    assert not Ballot.objects.filter(poll=live_poll).exists()


def test_null_is_refused_off_the_ballot_routes(db: None) -> None:
    """Only the ballot routes send no referrer, so only they get the exception."""
    User.objects.create_user(username="j.mercier", password="x")  # else: the wizard
    client = Client(enforce_csrf_checks=True)
    client.get("/fr/mairie/connexion/")
    token = client.cookies["csrftoken"].value
    response = client.post(
        "/fr/mairie/connexion/",
        {"username": "j.mercier", "password": "x", "csrfmiddlewaretoken": token},
        HTTP_ORIGIN="null",
    )
    assert response.status_code == 403


def test_a_ballot_page_offers_languages_as_links_not_a_form(live_poll: Poll) -> None:
    """Decision log #51: set_language's form would post with Origin: null from
    a page that sends no referrer, and be refused off the ballot routes."""
    _registration, token = _register(live_poll)
    body = Client().get(_access_url(live_poll, token)).content.decode()
    assert "/i18n/setlang/" not in body
    english = _access_url(live_poll, token).replace("/fr/", "/en/", 1)
    assert f'href="{english}"' in body


def test_every_other_page_keeps_the_form(live_poll: Poll) -> None:
    body = Client().get(f"/fr/scrutin/{live_poll.pk}/").content.decode()
    assert 'action="/i18n/setlang/"' in body
