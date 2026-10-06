# SPDX-License-Identifier: 0BSD
"""Sending a decided registration back to review, and who the journal names
(R-5.4, R-12.2).

A refusal can be reconsidered, and an acceptance withdrawn while no ballot has
been cast; either way the registration returns to the review queue. The audit
journal shows the registrant's declared name beside each registration event,
read from the live row, so the retention purge removes it with the row (INV-3).
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta
from typing import Any

import pytest
from django.core import mail as django_mail
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from apps.audit.models import Action, AuditEvent, Reason
from apps.ballots import services as ballots
from apps.core.models import PollRole, Role, User
from apps.core.types import Token
from apps.elections.models import Poll, RollEntry
from apps.elections.retention import RETENTION, purge
from apps.elections.transitions import close_poll
from apps.elections.windows import WindowClosed
from apps.registrations import services
from apps.registrations.models import Channel, Registration, RegistrationState
from tests.conftest import force_open

CaptureOnCommit = Callable[..., AbstractContextManager[list[Callable[[], Any]]]]

FORM = {
    "last_name": "Dupont",
    "first_names": "Émile",
    "date_of_birth": "12/05/1970",
    "email": "emile.dupont@example.fr",
    "declared_on_honour": "on",
}
ABC = [["a"], ["b"], ["c"]]


@pytest.fixture(autouse=True)
def _clear_rate_limit() -> None:
    cache.clear()


@pytest.fixture
def live_poll(open_window_poll: Poll) -> Poll:
    force_open(open_window_poll)
    return Poll.objects.get(pk=open_window_poll.pk)


@pytest.fixture
def admin(live_poll: Poll) -> User:
    user = User.objects.create_user(username="p.martin", password="x", full_name="P. Martin")
    PollRole.objects.create(poll=live_poll, user=user, role=Role.POLL_ADMIN)
    return user


def _accepted(poll: Poll) -> tuple[Registration, Token]:
    """Matched on the roll: accepted automatically, a link minted."""
    registration, token = services.register(poll, FORM, language="fr")
    assert token is not None and registration.state == RegistrationState.PENDING_EMAIL
    return registration, token


def _refused(poll: Poll, admin: User) -> Registration:
    """Sent to review by a misspelt name, then refused there."""
    registration, _ = services.register(poll, {**FORM, "last_name": "Dupond"}, language="fr")
    assert registration.state == RegistrationState.PENDING_REVIEW
    return services.reject(registration, Reason.NO_ROLL_MATCH, actor=admin, note="introuvable")


# --- the service --------------------------------------------------------------


def test_a_refusal_goes_back_to_review_with_its_reason_logged(live_poll: Poll, admin: User) -> None:
    registration = _refused(live_poll, admin)
    reopened, was_accepted = services.reopen_review(
        registration, Reason.NEW_INFORMATION, actor=admin, note="nom d'usage retrouvé"
    )
    assert not was_accepted
    assert reopened.state == RegistrationState.PENDING_REVIEW
    assert reopened.review_reason == "nom d'usage retrouvé"
    event = AuditEvent.objects.get(action=Action.REGISTRATION_REVIEW_REOPENED)
    assert (event.before, event.after) == ({"state": "rejected"}, {"state": "pending_review"})
    assert (event.reason, event.actor, event.object_ref) == (
        Reason.NEW_INFORMATION,
        admin,
        f"registration:{registration.pk}",
    )
    # The note is prose: it stays on the row the purge deletes (§10).
    assert "nom d'usage" not in str(event.before) + str(event.after) + event.reason


@pytest.mark.parametrize("confirmed", [False, True], ids=["unconfirmed", "confirmed"])
def test_an_acceptance_withdrawn_before_any_ballot_kills_the_link(
    live_poll: Poll, admin: User, confirmed: bool
) -> None:
    registration, token = _accepted(live_poll)
    if confirmed:
        assert services.arrive(live_poll, token) is not None  # the mailbox is proven
        registration.refresh_from_db()
        assert registration.state == RegistrationState.ACTIVE

    reopened, was_accepted = services.reopen_review(
        registration, Reason.DECISION_ERROR, actor=admin
    )
    assert was_accepted
    assert reopened.state == RegistrationState.PENDING_REVIEW
    assert reopened.voter_hash is None
    assert reopened.roll_entry is None  # INV-4 frees the entry for the next decision
    assert services.arrive(live_poll, token) is None  # the link opens nothing now

    # Accepted again in review: a new link, the old one still dead.
    entry = RollEntry.objects.get(poll=live_poll)
    again, new_token = services.approve(
        reopened, entry, Reason.IDENTITY_CONFIRMED_AT_MAIRIE, actor=admin
    )
    assert again.state == RegistrationState.PENDING_EMAIL
    assert services.arrive(live_poll, new_token) is not None
    assert services.arrive(live_poll, token) is None


@pytest.mark.parametrize("channel", [Channel.ONLINE, Channel.PAPER])
def test_an_acceptance_stands_once_a_ballot_is_cast(
    live_poll: Poll, admin: User, channel: str
) -> None:
    registration, token = _accepted(live_poll)
    services.arrive(live_poll, token)
    if channel == Channel.ONLINE:
        ballots.cast_online(live_poll, token, ABC)
    else:
        Registration.objects.filter(pk=registration.pk).update(channel=Channel.PAPER)
    registration.refresh_from_db()
    assert not services.can_reopen(registration)
    with pytest.raises(services.RegistrationRefused):
        services.reopen_review(registration, Reason.DECISION_ERROR, actor=admin)
    registration.refresh_from_db()
    assert registration.state == RegistrationState.ACTIVE
    assert not AuditEvent.objects.filter(action=Action.REGISTRATION_REVIEW_REOPENED).exists()


def test_a_ballot_cast_between_the_check_and_the_write_keeps_the_acceptance(
    live_poll: Poll, admin: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The withdrawal is a compare-and-set on ``channel = 'none'``, like
    ``mark_voted``: a vote landing after the check refuses it (INV-5)."""
    registration, token = _accepted(live_poll)
    services.arrive(live_poll, token)
    ballots.cast_online(live_poll, token, ABC)
    monkeypatch.setattr(services, "can_reopen", lambda r: True)  # the check saw no ballot
    with pytest.raises(services.RegistrationRefused):
        services.reopen_review(registration, Reason.DECISION_ERROR, actor=admin)
    registration.refresh_from_db()
    assert (registration.state, registration.channel) == (RegistrationState.ACTIVE, "online")
    assert registration.voter_hash is not None


def test_nothing_is_reopened_without_a_reason_or_outside_the_window(
    live_poll: Poll, admin: User
) -> None:
    registration = _refused(live_poll, admin)
    with pytest.raises(services.RegistrationRefused):
        services.reopen_review(registration, "", actor=admin)
    Poll.objects.filter(pk=live_poll.pk).update(closes_at=timezone.now() - timedelta(minutes=1))
    registration = Registration.objects.get(pk=registration.pk)
    with pytest.raises(WindowClosed):
        services.reopen_review(registration, Reason.NEW_INFORMATION, actor=admin)
    assert Registration.objects.get(pk=registration.pk).state == RegistrationState.REJECTED


def test_a_pending_review_or_a_paper_shell_is_not_reopenable(live_poll: Poll) -> None:
    pending, _ = services.register(live_poll, {**FORM, "last_name": "Dupond"}, language="fr")
    assert not services.can_reopen(pending)
    entry = RollEntry.objects.get(poll=live_poll)
    shell_id, _channel = services.ensure_paper_registration(live_poll, str(entry.pk))
    shell = Registration.objects.get(pk=shell_id)
    Registration.objects.filter(pk=shell.pk).update(channel=Channel.NONE)
    shell.refresh_from_db()
    assert shell.email_canonical == "" and not services.can_reopen(shell)


# --- screen 4 -------------------------------------------------------------------


def _url(poll: Poll, registration: Registration) -> str:
    return f"/fr/mairie/scrutin/{poll.pk}/inscriptions/{registration.pk}/reexamen/"


def test_the_page_reopens_an_acceptance_and_mails_the_elector(
    client: Client,
    live_poll: Poll,
    admin: User,
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    registration, _ = _accepted(live_poll)
    client.force_login(admin)
    page = client.get(_url(live_poll, registration))
    assert page.status_code == 200
    assert "le lien de vote déjà envoyé cessera de fonctionner" in page.content.decode()

    django_mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(_url(live_poll, registration), {"reason": "decision_error"})
    assert response.status_code == 302
    assert response["Location"].endswith(f"#demande-{registration.pk}")
    registration.refresh_from_db()
    assert registration.state == RegistrationState.PENDING_REVIEW
    (sent,) = django_mail.outbox
    assert sent.to == [FORM["email"]]
    assert "réexaminée" in sent.subject
    assert "ne fonctionne plus" in str(sent.body)
    assert "decision_error" not in str(sent.body)  # the reason is the mairie's record


def test_reopening_a_refusal_sends_no_mail_and_a_bad_reason_changes_nothing(
    client: Client,
    live_poll: Poll,
    admin: User,
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    registration = _refused(live_poll, admin)
    client.force_login(admin)
    queue = client.get(f"/fr/mairie/scrutin/{live_poll.pk}/inscriptions/").content.decode()
    assert "Refusées" in queue and _url(live_poll, registration) in queue

    client.post(_url(live_poll, registration), {"reason": "duplicate_ballot"})  # wrong vocabulary
    assert Registration.objects.get(pk=registration.pk).state == RegistrationState.REJECTED

    django_mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        client.post(_url(live_poll, registration), {"reason": "new_information"})
    assert Registration.objects.get(pk=registration.pk).state == RegistrationState.PENDING_REVIEW
    assert not django_mail.outbox


def test_only_the_poll_admin_reopens(client: Client, live_poll: Poll, admin: User) -> None:
    registration = _refused(live_poll, admin)
    auditor = User.objects.create_user(username="a.klein", password="x", full_name="A. Klein")
    PollRole.objects.create(poll=live_poll, user=auditor, role=Role.AUDITOR)
    client.force_login(auditor)
    assert client.get(_url(live_poll, registration)).status_code == 403
    assert client.post(_url(live_poll, registration), {"reason": "other"}).status_code == 403
    assert Registration.objects.get(pk=registration.pk).state == RegistrationState.REJECTED


# --- the journal ----------------------------------------------------------------


def _journal(client: Client, poll: Poll) -> str:
    return client.get(f"/fr/mairie/scrutin/{poll.pk}/journal/").content.decode()


def test_the_journal_names_the_registrant_and_offers_the_review_to_the_admin(
    client: Client, live_poll: Poll, admin: User
) -> None:
    registration = _refused(live_poll, admin)
    client.force_login(admin)
    page = _journal(client, live_poll)
    assert f"registration:{registration.pk}" in page
    assert '<span class="journal-subject">Dupond Émile</span>' in page
    assert _url(live_poll, registration) in page

    auditor = User.objects.create_user(username="a.klein", password="x", full_name="A. Klein")
    PollRole.objects.create(poll=live_poll, user=auditor, role=Role.AUDITOR)
    client.force_login(auditor)
    page = _journal(client, live_poll)
    assert '<span class="journal-subject">Dupond Émile</span>' in page  # names for the auditor too
    assert _url(live_poll, registration) not in page  # but reopening is the admin's


def test_the_name_is_never_stored_and_goes_with_the_purge(
    client: Client, live_poll: Poll, admin: User
) -> None:
    registration = _refused(live_poll, admin)
    assert not AuditEvent.objects.filter(before__icontains="Dupond").exists()
    assert not AuditEvent.objects.filter(after__icontains="Dupond").exists()

    close_poll(live_poll, early_reason=Reason.ADMINISTRATIVE_DECISION)
    Poll.objects.filter(pk=live_poll.pk).update(
        closed_at=timezone.now() - RETENTION - timedelta(days=1)
    )
    purge(Poll.objects.get(pk=live_poll.pk))
    assert not Registration.objects.filter(pk=registration.pk).exists()

    client.force_login(admin)
    page = _journal(client, live_poll)
    assert f"registration:{registration.pk}" in page  # the reference stays (INV-3)
    assert "Dupond" not in page
    assert "objet supprimé (rétention)" in page
