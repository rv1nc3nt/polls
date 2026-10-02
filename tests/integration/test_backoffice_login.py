# SPDX-License-Identifier: 0BSD
"""Back-office sign-in under repeated failure (review A-7, decision log #43).

Operator accounts open the screens that show who has voted and every paper
ballot beside its elector, and Django's sign-in view counts nothing. Failures
are now counted by caller and by account named; past either limit the form is
refused without the password being checked at all.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from django.core.cache import cache
from django.test import Client, override_settings

from apps.core.models import User

URL = "/fr/mairie/connexion/"
PASSWORD = "corrège-cheval-agrafe-42"


@pytest.fixture(autouse=True)
def _fresh_counters() -> Iterator[None]:
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def operator(db: None) -> User:
    return User.objects.create_user(username="m.durand", password=PASSWORD)


def _sign_in(
    client: Client, password: str, *, address: str = "203.0.113.7", user: str = "m.durand"
) -> int:
    response = client.post(URL, {"username": user, "password": password}, REMOTE_ADDR=address)
    return response.status_code


@override_settings(RATE_LIMIT_LOGIN_ADDRESS="3/15m", RATE_LIMIT_LOGIN_ACCOUNT="100/1h")
def test_one_address_is_stopped_after_its_failures(client: Client, operator: User) -> None:
    assert [_sign_in(client, "wrong") for _ in range(3)] == [200, 200, 200]
    # Even the right password is not checked any more from this address.
    assert _sign_in(client, PASSWORD) == 429
    assert "_auth_user_id" not in client.session
    # Another address is not held to this one's failures.
    assert _sign_in(Client(), PASSWORD, address="198.51.100.4") == 302


@override_settings(RATE_LIMIT_LOGIN_ADDRESS="100/15m", RATE_LIMIT_LOGIN_ACCOUNT="3/1h")
def test_one_account_is_protected_from_guesses_spread_over_addresses(
    client: Client, operator: User
) -> None:
    for k in range(3):
        assert _sign_in(client, "wrong", address=f"198.51.100.{k}") == 200
    assert _sign_in(Client(), PASSWORD, address="192.0.2.99") == 429
    # Case does not make it another account.
    assert _sign_in(Client(), PASSWORD, address="192.0.2.98", user="M.Durand") == 429


@override_settings(RATE_LIMIT_LOGIN_ADDRESS="100/15m", RATE_LIMIT_LOGIN_ACCOUNT="3/1h")
def test_a_correct_sign_in_clears_the_accounts_failures(client: Client, operator: User) -> None:
    assert _sign_in(client, "wrong") == 200
    assert _sign_in(client, "wrong") == 200
    assert _sign_in(client, PASSWORD) == 302
    client.logout()
    assert _sign_in(client, "wrong") == 200
    assert _sign_in(client, "wrong") == 200
    assert _sign_in(client, PASSWORD) == 302


def test_a_failure_is_logged_without_the_name_typed(
    client: Client, operator: User, caplog: pytest.LogCaptureFixture
) -> None:
    """The name field sometimes holds a password typed in the wrong place."""
    with caplog.at_level(logging.WARNING, logger="polls.auth"):
        _sign_in(client, "wrong", user="hunter2-typed-here")
    messages = [r.getMessage() for r in caplog.records if r.name == "polls.auth"]
    assert messages and all("hunter2" not in m for m in messages)
