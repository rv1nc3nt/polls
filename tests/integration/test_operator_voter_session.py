# SPDX-License-Identifier: 0BSD
"""An operator is also an elector: their session never holds a ballot.

A signed-in session holds the operator's account id; a ballot route stores a
ballot hash or a receipt. In one session the two would tie a named person to
their ballot (INV-1), so they never meet, whichever comes first
(``core/operatorsession.py``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.sessions.models import Session
from django.test import Client
from django.urls import reverse

from apps.core.models import User
from apps.core.sessions import SessionStore
from apps.elections.models import Poll
from tests.conftest import force_open
from tests.integration.test_ballot_http import STRICT, _access_url, _register

PASSWORD = "un mot de passe sûr"


@pytest.fixture
def live_poll(open_window_poll: Poll) -> Poll:
    force_open(open_window_poll)
    return Poll.objects.get(pk=open_window_poll.pk)


@pytest.fixture
def operator(db: None) -> User:
    return User.objects.create_user(username="e.dupont", password=PASSWORD)


def _joined_sessions() -> list[dict[str, Any]]:
    """Every stored session holding an account id beside ballot data."""
    joined = []
    for row in Session.objects.all():
        data = SessionStore().decode(row.session_data)
        if "_auth_user_id" in data and any(key.startswith(("ballot:", "receipt:")) for key in data):
            joined.append(data)
    return joined


def test_casting_from_a_signed_in_browser_signs_the_operator_out_first(
    client: Client,
    live_poll: Poll,
    operator: User,
    django_capture_on_commit_callbacks: Callable[..., Any],
) -> None:
    _registration, token = _register(live_poll)
    client.force_login(operator)

    page = client.get(_access_url(live_poll, token))
    assert "déconnecté de l&#x27;espace mairie" in page.content.decode()
    assert "_auth_user_id" not in client.session

    with django_capture_on_commit_callbacks(execute=True):
        cast = client.post(_access_url(live_poll, token), STRICT)
    assert cast.status_code == 302
    assert client.get(cast["Location"]).status_code == 200  # the receipt
    assert any(key.startswith("receipt:") for key in client.session.keys())
    assert _joined_sessions() == []


def test_the_modification_link_signs_the_operator_out_too(
    client: Client,
    live_poll: Poll,
    operator: User,
    django_capture_on_commit_callbacks: Callable[..., Any],
) -> None:
    _registration, token = _register(live_poll)
    client.get(_access_url(live_poll, token))
    with django_capture_on_commit_callbacks(execute=True):
        client.post(_access_url(live_poll, token), STRICT)

    client.force_login(operator)
    client.get(_access_url(live_poll, token))  # now the modification link
    assert "_auth_user_id" not in client.session
    assert any(key.startswith("ballot:") for key in client.session.keys())
    assert _joined_sessions() == []


def test_signing_in_after_voting_drops_the_ballot_keys(
    client: Client,
    live_poll: Poll,
    operator: User,
    django_capture_on_commit_callbacks: Callable[..., Any],
) -> None:
    """Django's ``login`` keeps the session's data across sign-in."""
    _registration, token = _register(live_poll)
    client.get(_access_url(live_poll, token))
    with django_capture_on_commit_callbacks(execute=True):
        client.post(_access_url(live_poll, token), STRICT)
    assert any(key.startswith("receipt:") for key in client.session.keys())

    response = client.post(
        reverse("backoffice:login"), {"username": "e.dupont", "password": PASSWORD}
    )
    assert response.status_code == 302
    assert "_auth_user_id" in client.session
    assert not any(key.startswith(("ballot:", "receipt:")) for key in client.session.keys())
    assert _joined_sessions() == []


def test_the_rest_of_the_public_site_keeps_the_operator_signed_in(
    client: Client, live_poll: Poll, operator: User
) -> None:
    """Only the ballot routes store ballot data, so only they sign out."""
    client.force_login(operator)
    assert client.get(f"/fr/scrutin/{live_poll.pk}/").status_code == 200
    assert "_auth_user_id" in client.session
