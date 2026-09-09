# SPDX-License-Identifier: 0BSD
"""The registration pages, screen 4, and the two jobs around them.

Where ``test_registration_flow`` pins the service layer, this pins what a
browser and an operator actually see — including the parts of §6.3 that apply
the moment a token appears in a URL (T-21).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.core import mail as django_mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from apps.audit.models import Action, AuditEvent
from apps.core.models import PollRole, Role, User
from apps.elections.models import Poll
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


@pytest.fixture
def live_poll(open_window_poll: Poll) -> Poll:
    open_poll(open_window_poll)
    return Poll.objects.get(pk=open_window_poll.pk)


@pytest.fixture(autouse=True)
def _clear_rate_limit() -> None:
    """The limiter counts in the cache, which outlives a test otherwise."""
    cache.clear()


@pytest.fixture
def admin_user(db: None) -> User:
    return User.objects.create_user(username="p.martin", password="x", full_name="P. Martin")


# --- The voter's three pages -------------------------------------------------


def test_the_form_states_the_privacy_notice_and_the_name_help(
    client: Client, live_poll: Poll
) -> None:
    """R-13.2 at the point of collection, and §6.2 step 1's help text: either
    the birth surname or the name in use is accepted (R-5.3)."""
    body = client.get(f"/fr/inscription/{live_poll.pk}/").content.decode()
    assert "carte électorale" in body
    assert "nom d&#x27;usage" in body
    assert "deux mois après la clôture" in body


def test_a_matched_registration_is_told_to_check_its_mail(
    client: Client, live_poll: Poll, django_capture_on_commit_callbacks: Callable[..., Any]
) -> None:
    """The send is deferred to ``on_commit`` so a rolled-back registration
    cannot produce a delivered mail; the fixture is what runs the callback
    inside the test's own transaction."""
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(f"/fr/inscription/{live_poll.pk}/", FORM, follow=True)
    assert response.status_code == 200
    assert "Vérifiez votre boîte aux lettres" in response.content.decode()
    assert len(django_mail.outbox) == 1


def test_a_divergent_name_is_told_a_human_will_look(client: Client, live_poll: Poll) -> None:
    response = client.post(
        f"/fr/inscription/{live_poll.pk}/", {**FORM, "last_name": "Dupond"}, follow=True
    )
    assert "sera examinée" in response.content.decode()
    assert django_mail.outbox == [], "no token before a human has looked"


def test_t61_an_ineligible_list_type_is_told_so_plainly(
    client: Client, open_window_poll: Poll
) -> None:
    """R-4.7: found on the roll, but on a list that confers no standing here."""
    from apps.elections.models import WorkingRollEntry
    from apps.elections.transitions import open_poll

    WorkingRollEntry.objects.all().delete()
    WorkingRollEntry.objects.create(
        birth_name="Zampieri",
        first_names="Églantine",
        date_of_birth="08/01/1983",
        date_of_birth_parsed="1983-01-08",
        list_types=["complementaire_europeenne"],
    )
    open_poll(open_window_poll)

    response = client.post(
        f"/fr/inscription/{open_window_poll.pk}/",
        {
            "last_name": "Zampieri",
            "first_names": "Églantine",
            "date_of_birth": "08/01/1983",
            "email": "eglantine@example.fr",
            "declared_on_honour": "on",
        },
        follow=True,
    )
    assert "pas concerné par cette consultation" in response.content.decode()
    assert django_mail.outbox == []


def test_a_duplicate_sees_the_neutral_message_and_no_detail(
    client: Client, live_poll: Poll
) -> None:
    """T-2, T-17: the page must not disclose that a registration exists, whose
    it is, or which field collided."""
    client.post(f"/fr/inscription/{live_poll.pk}/", FORM)
    body = client.post(
        f"/fr/inscription/{live_poll.pk}/", {**FORM, "email": "autre@example.fr"}
    ).content.decode()

    assert "adresser à la mairie" in body
    assert "Dupont" not in body.split("<form")[0]
    assert "emile.dupont@example.fr" not in body


def test_the_honour_declaration_is_required(client: Client, live_poll: Poll) -> None:
    """R-5.2."""
    payload = {k: v for k, v in FORM.items() if k != "declared_on_honour"}
    client.post(f"/fr/inscription/{live_poll.pk}/", payload)
    assert Registration.objects.count() == 0


def test_t15_a_sandbox_poll_is_not_reachable(client: Client, live_poll: Poll) -> None:
    """INV-8. ``is_sandbox`` is frozen configuration, so this poll is built with
    it rather than switched."""
    now = timezone.now()
    sandbox = Poll.objects.create(
        title_i18n={"fr": "Essai"},
        description_i18n={"fr": "Essai"},
        languages=["fr"],
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
        is_sandbox=True,
    )
    assert client.get(f"/fr/inscription/{sandbox.pk}/").status_code == 404


# --- §6.3's token rules, which apply here (T-21) -----------------------------


def test_t21_the_token_is_exchanged_for_a_session_and_leaves_the_url(
    client: Client, live_poll: Poll
) -> None:
    """§6.3, all of it that is code: the redirect to a token-free URL, and the
    two headers. Without them §7's claim that the token never reaches a log is
    false from the first click."""
    _registration, token = services.register(live_poll, FORM, language="fr")
    assert token is not None

    response = client.get(f"/fr/inscription/{live_poll.pk}/confirmation/{token.reveal()}/")
    assert response.status_code == 302
    assert token.reveal() not in response["Location"]
    assert response["Referrer-Policy"] == "no-referrer"
    assert response["Cache-Control"] == "no-store"

    landing = client.get(response["Location"])
    assert landing.status_code == 200
    assert "confirmée" in landing.content.decode()
    assert landing["Referrer-Policy"] == "no-referrer"


def test_the_confirmation_link_activates_the_registration(client: Client, live_poll: Poll) -> None:
    registration, token = services.register(live_poll, FORM, language="fr")
    assert token is not None
    client.get(f"/fr/inscription/{live_poll.pk}/confirmation/{token.reveal()}/")

    registration.refresh_from_db()
    assert registration.state == RegistrationState.ACTIVE
    assert registration.confirmed_at is not None


def test_the_session_holds_a_registration_id_and_never_the_token(
    client: Client, live_poll: Poll
) -> None:
    """§7: the plaintext token is never persisted, and Django's session backend
    is a database table."""
    registration, token = services.register(live_poll, FORM, language="fr")
    assert token is not None
    client.get(f"/fr/inscription/{live_poll.pk}/confirmation/{token.reveal()}/")

    stored = dict(client.session.items())
    assert str(registration.pk) in str(stored)
    assert token.reveal() not in str(stored)


def test_an_invalid_token_says_so_without_a_stack_trace(client: Client, live_poll: Poll) -> None:
    response = client.get(f"/fr/inscription/{live_poll.pk}/confirmation/NOTATOKEN/")
    assert response.status_code == 404
    # Autoescaped, so the apostrophe is not the thing to assert on.
    assert "Lien non valide" in response.content.decode()


# --- R-5.8: rate limiting -----------------------------------------------------


def test_r58_the_registration_endpoint_is_rate_limited(
    client: Client, live_poll: Poll, settings: pytest.FixtureRequest
) -> None:
    """Step 9. The refusal is the same neutral message, so being throttled
    teaches an attacker nothing either."""
    from django.test import override_settings

    with override_settings(RATE_LIMIT_REGISTRATION="2/1h"):
        for index in range(2):
            client.post(
                f"/fr/inscription/{live_poll.pk}/",
                {**FORM, "last_name": f"Nom{index}", "email": f"{index}@example.fr"},
            )
        blocked = client.post(
            f"/fr/inscription/{live_poll.pk}/",
            {**FORM, "last_name": "Autre", "email": "third@example.fr"},
        )

    assert "adresser à la mairie" in blocked.content.decode()
    assert Registration.objects.count() == 2


def test_the_limiter_stores_no_address(client: Client, live_poll: Poll) -> None:
    """R-13.5: addresses are kept only as long as rate-limiting requires, so
    the counter is keyed on a salted digest and nothing can reverse it."""
    from apps.core import ratelimit

    request = client.request().wsgi_request
    request.META["REMOTE_ADDR"] = "203.0.113.7"
    digest = ratelimit.client_digest(request)
    assert "203.0.113" not in digest
    assert len(digest) == 32


# --- Screen 4 (§6.5.4) --------------------------------------------------------


def _grant_admin(poll: Poll, user: User) -> None:
    PollRole.objects.create(poll=poll, user=user, role=Role.POLL_ADMIN)


def test_the_queue_shows_pending_registrations_with_near_matches(
    client: Client, live_poll: Poll, admin_user: User
) -> None:
    services.register(live_poll, {**FORM, "last_name": "Dupond"}, language="fr")
    _grant_admin(live_poll, admin_user)
    client.force_login(admin_user)

    body = client.get(f"/fr/mairie/scrutin/{live_poll.pk}/inscriptions/").content.decode()
    assert "Dupond" in body, "the declaration"
    assert "Dupont" in body, "the roll entry to compare it against"
    assert "date identique" in body


def test_approving_from_the_queue_mails_the_link_and_logs_the_decision(
    client: Client,
    live_poll: Poll,
    admin_user: User,
    django_capture_on_commit_callbacks: Callable[..., Any],
) -> None:
    """T-18: ``pending_review → pending_email``, never straight to ``active``."""
    from apps.elections.models import RollEntry

    registration, _ = services.register(live_poll, {**FORM, "last_name": "Dupond"}, language="fr")
    entry = RollEntry.objects.get(poll=live_poll, birth_name="Dupont")
    _grant_admin(live_poll, admin_user)
    client.force_login(admin_user)

    with django_capture_on_commit_callbacks(execute=True):
        client.post(
            f"/fr/mairie/scrutin/{live_poll.pk}/inscriptions/decision/",
            {
                "registration": str(registration.pk),
                "roll_entry": str(entry.pk),
                "decision": "approve",
                "approve_reason": "identity_confirmed_at_mairie",
                "note": "vu au guichet",
            },
            follow=True,
        )

    registration.refresh_from_db()
    assert registration.state == RegistrationState.PENDING_EMAIL
    assert len(django_mail.outbox) == 1
    event = AuditEvent.objects.get(action=Action.REGISTRATION_REVIEWED)
    assert event.actor == admin_user
    assert "guichet" not in str(event.after), "prose belongs on the row, not the event"


def test_rejecting_without_a_reason_is_refused(
    client: Client, live_poll: Poll, admin_user: User
) -> None:
    """§6.5.4 makes the reason mandatory, and §10 makes it a code."""
    registration, _ = services.register(live_poll, {**FORM, "last_name": "Dupond"}, language="fr")
    _grant_admin(live_poll, admin_user)
    client.force_login(admin_user)

    client.post(
        f"/fr/mairie/scrutin/{live_poll.pk}/inscriptions/decision/",
        {"registration": str(registration.pk), "decision": "reject", "reject_reason": ""},
        follow=True,
    )
    registration.refresh_from_db()
    assert registration.state == RegistrationState.PENDING_REVIEW

    client.post(
        f"/fr/mairie/scrutin/{live_poll.pk}/inscriptions/decision/",
        {
            "registration": str(registration.pk),
            "decision": "reject",
            "reject_reason": "name_divergence_refused",
        },
        follow=True,
    )
    registration.refresh_from_db()
    assert registration.state == RegistrationState.REJECTED


def test_an_entry_operator_cannot_reach_the_queue(
    client: Client, live_poll: Poll, admin_user: User
) -> None:
    PollRole.objects.create(poll=live_poll, user=admin_user, role=Role.ENTRY_OPERATOR)
    client.force_login(admin_user)
    assert client.get(f"/fr/mairie/scrutin/{live_poll.pk}/inscriptions/").status_code == 403


def test_the_queue_of_another_poll_is_not_reachable(
    client: Client, live_poll: Poll, admin_user: User
) -> None:
    """A decision must not be postable across polls."""
    registration, _ = services.register(live_poll, {**FORM, "last_name": "Dupond"}, language="fr")
    now = timezone.now()
    other = Poll.objects.create(
        title_i18n={"fr": "Autre"},
        description_i18n={"fr": "Autre"},
        languages=["fr"],
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
    )
    _grant_admin(other, admin_user)
    client.force_login(admin_user)

    response = client.post(
        f"/fr/mairie/scrutin/{other.pk}/inscriptions/decision/",
        {
            "registration": str(registration.pk),
            "decision": "approve",
            "approve_reason": "administrative_decision",
        },
    )
    assert response.status_code == 404
    registration.refresh_from_db()
    assert registration.state == RegistrationState.PENDING_REVIEW


# --- Step 8: the reminder job (R-5.7) ----------------------------------------


def test_t37_reminders_go_once_to_active_non_voters_only(live_poll: Poll) -> None:
    def make(tag: str, state: str, channel: str) -> Registration:
        return Registration.objects.create(
            poll=live_poll,
            declared_last_name="D",
            declared_first_names="E",
            declared_dob="01/01/1970",
            email=f"{tag}@example.fr",
            email_canonical=f"{tag}@example.fr",
            state=state,
            channel=channel,
        )

    due = make("one", RegistrationState.ACTIVE, Channel.NONE)
    make("two", RegistrationState.ACTIVE, Channel.ONLINE)
    make("three", RegistrationState.PENDING_EMAIL, Channel.NONE)

    call_command("send_reminders")
    assert [message.to for message in django_mail.outbox] == [[due.email]]

    # T-49: a second run sends nothing, because the first stamped the row.
    call_command("send_reminders")
    assert len(django_mail.outbox) == 1
    due.refresh_from_db()
    assert due.reminder_sent_at is not None


def test_a_reason_from_the_wrong_vocabulary_is_refused(
    client: Client, live_poll: Poll, admin_user: User
) -> None:
    """§10: the code logged has to be one that was true. "bulletin en double"
    is a valid ``Reason`` and a false record of a registration decision."""
    registration, _ = services.register(live_poll, {**FORM, "last_name": "Dupond"}, language="fr")
    _grant_admin(live_poll, admin_user)
    client.force_login(admin_user)

    client.post(
        f"/fr/mairie/scrutin/{live_poll.pk}/inscriptions/decision/",
        {
            "registration": str(registration.pk),
            "decision": "reject",
            "reject_reason": "duplicate_ballot",
        },
        follow=True,
    )
    registration.refresh_from_db()
    assert registration.state == RegistrationState.PENDING_REVIEW
    assert not AuditEvent.objects.filter(action=Action.REGISTRATION_REVIEWED).exists()
