# SPDX-License-Identifier: 0BSD
"""Duplicate registration attempts are flagged to the poll admin (R-5.9).

An attempt against a roll entry that already has a registration is refused,
logged, and shown on the dashboard until a poll admin marks it handled, which
is logged too. The attempter leaves nothing behind (§10).
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.test import Client

from apps.audit.models import Action, AuditEvent
from apps.core.models import PollRole, Role, User
from apps.elections.models import Poll
from apps.registrations import services
from apps.registrations.models import DuplicateAttempt, Registration
from tests.conftest import force_open

FORM = {
    "last_name": "Dupont",
    "first_names": "Émile",
    "date_of_birth": "12/05/1970",
    "email": "emile.dupont@example.fr",
    "declared_on_honour": "on",
}


@pytest.fixture(autouse=True)
def _clear_rate_limit() -> None:
    cache.clear()


@pytest.fixture
def live_poll(open_window_poll: Poll) -> Poll:
    force_open(open_window_poll)
    return Poll.objects.get(pk=open_window_poll.pk)


def _user(poll: Poll, username: str, role: Role) -> User:
    user = User.objects.create_user(username=username, password="x", full_name=username)
    PollRole.objects.create(poll=poll, user=user, role=role)
    return user


def _attempt(poll: Poll) -> DuplicateAttempt:
    """Émile Dupont registers; then someone tries again with his identity."""
    services.register(poll, FORM, language="fr")
    with pytest.raises(services.RegistrationRefused):
        services.register(poll, {**FORM, "email": "autre@example.fr"}, language="fr")
    return DuplicateAttempt.objects.get(poll=poll)


def _dashboard(client: Client, poll: Poll) -> str:
    return client.get(f"/fr/mairie/scrutin/{poll.pk}/").content.decode()


def test_the_attempt_leaves_a_flag_and_nothing_about_the_attempter(live_poll: Poll) -> None:
    attempt = _attempt(live_poll)
    assert attempt.acknowledged_at is None
    assert Registration.objects.filter(poll=live_poll).count() == 1  # no row for the attempter
    assert not Registration.objects.filter(email_canonical="autre@example.fr").exists()


def test_the_poll_admin_sees_the_flag_with_the_existing_registration(
    client: Client, live_poll: Poll
) -> None:
    attempt = _attempt(live_poll)
    client.force_login(_user(live_poll, "p.admin", Role.POLL_ADMIN))
    page = _dashboard(client, live_poll)
    assert "1 tentative de doublon d'inscription à examiner" in page
    assert "Dupont Émile" in page
    assert "n'a pas voté" in page
    ref = f"registration:{attempt.existing_registration_id}"
    assert f"/journal/?object={ref.replace(':', '%3A')}" in page
    assert "autre@example.fr" not in page


@pytest.mark.parametrize("role", [Role.AUDITOR, Role.ENTRY_OPERATOR])
def test_other_roles_do_not_see_it_and_cannot_handle_it(
    client: Client, live_poll: Poll, role: Role
) -> None:
    attempt = _attempt(live_poll)
    client.force_login(_user(live_poll, "someone", role))
    assert "tentative de doublon" not in _dashboard(client, live_poll)
    url = f"/fr/mairie/scrutin/{live_poll.pk}/doublons/traiter/"
    assert client.post(url, {"attempt": str(attempt.pk)}).status_code == 403
    attempt.refresh_from_db()
    assert attempt.acknowledged_at is None


def test_marking_it_handled_takes_it_off_and_is_logged_once(
    client: Client, live_poll: Poll
) -> None:
    attempt = _attempt(live_poll)
    admin = _user(live_poll, "p.admin", Role.POLL_ADMIN)
    client.force_login(admin)
    url = f"/fr/mairie/scrutin/{live_poll.pk}/doublons/traiter/"
    response = client.post(url, {"attempt": str(attempt.pk)})
    assert response.status_code == 302 and response["Location"].endswith("#doublons")
    attempt.refresh_from_db()
    assert attempt.acknowledged_at is not None
    assert "tentative de doublon" not in _dashboard(client, live_poll)

    client.post(url, {"attempt": str(attempt.pk)})  # a second click changes nothing
    (event,) = AuditEvent.objects.filter(action=Action.DUPLICATE_ATTEMPT_ACKNOWLEDGED)
    assert event.actor == admin
    assert event.object_ref == f"registration:{attempt.existing_registration_id}"
    assert (event.before, event.after) == (
        {"duplicate_attempt": "open"},
        {"duplicate_attempt": "acknowledged"},
    )


def test_another_polls_flag_is_not_reachable(
    client: Client, live_poll: Poll, open_paper_poll: Poll
) -> None:
    attempt = _attempt(live_poll)
    client.force_login(_user(open_paper_poll, "other.admin", Role.POLL_ADMIN))
    url = f"/fr/mairie/scrutin/{open_paper_poll.pk}/doublons/traiter/"
    assert client.post(url, {"attempt": str(attempt.pk)}).status_code == 404
    attempt.refresh_from_db()
    assert attempt.acknowledged_at is None
