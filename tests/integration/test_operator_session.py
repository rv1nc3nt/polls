# SPDX-License-Identifier: 0BSD
"""Back-office sessions end eight hours after sign-in (review A-16)."""

from __future__ import annotations

import time

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from apps.core.models import User
from apps.core.operatorsession import DEADLINE_KEY


@pytest.fixture
def operator(db: None) -> User:
    user = User.objects.create_user(username="j.mercier", password="un mot de passe sûr")
    user.is_commune_admin = True
    user.save(update_fields=["is_commune_admin"])
    return user


def _signed_in(client: Client) -> bool:
    response = client.get("/fr/mairie/")
    return response.status_code == 200


def test_signing_in_sets_an_eight_hour_cookie_and_deadline(client: Client, operator: User) -> None:
    before = int(time.time())
    response = client.post(
        reverse("backoffice:login"),
        {"username": "j.mercier", "password": "un mot de passe sûr"},
    )
    assert response.status_code == 302
    cookie = response.cookies[settings.SESSION_COOKIE_NAME]
    assert cookie["max-age"] == settings.OPERATOR_SESSION_AGE == 8 * 3600
    deadline = client.session[DEADLINE_KEY]
    assert before + 8 * 3600 <= deadline <= int(time.time()) + 8 * 3600
    assert _signed_in(client)


def test_a_session_past_its_deadline_is_signed_out(client: Client, operator: User) -> None:
    """Enforced on the server: the stored session row, rounded up to midnight
    for INV-1, would otherwise outlive the cookie."""
    client.force_login(operator)
    assert _signed_in(client)
    session = client.session
    session[DEADLINE_KEY] = int(time.time()) - 1
    session.save()

    response = client.get("/fr/mairie/")
    assert response.status_code == 302
    assert reverse("backoffice:login") in response["Location"]
    assert "_auth_user_id" not in client.session


def test_a_session_signed_in_before_the_limit_existed_is_signed_out(
    client: Client, operator: User
) -> None:
    client.force_login(operator)
    session = client.session
    del session[DEADLINE_KEY]
    session.save()
    assert not _signed_in(client)


def test_a_voter_session_keeps_the_default_age(client: Client, db: None) -> None:
    """Nobody signs in on the public site, so nothing shortens its sessions."""
    session = client.session
    session["anything"] = 1
    session.save()
    assert session.get_expiry_age() == settings.SESSION_COOKIE_AGE
    assert DEADLINE_KEY not in session


def test_a_form_posted_past_the_deadline_asks_to_sign_in_again(operator: User) -> None:
    """Signing out flushes the session but keeps the CSRF cookie, so the form
    an operator left open is answered with the sign-in page, not a CSRF
    refusal."""
    client = Client(enforce_csrf_checks=True)
    client.force_login(operator)
    client.get(reverse("backoffice:account_admin"))
    token = client.cookies[settings.CSRF_COOKIE_NAME].value
    session = client.session
    session[DEADLINE_KEY] = int(time.time()) - 1
    session.save()

    response = client.post(reverse("backoffice:account_admin"), {"csrfmiddlewaretoken": token})
    assert response.status_code == 302
    assert reverse("backoffice:login") in response["Location"]
