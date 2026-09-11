# SPDX-License-Identifier: 0BSD
"""Screen "Nouveau scrutin" — the create step behind screen 2 (§6.5.2, R-3.1, R-3.7).

Commune-level like screens 10 and 12 (``require_commune_admin``, not a
per-poll role, since a poll being created has no ``poll_admin`` yet). What it
must get right: the created poll is a real, valid ``draft`` (options, dates,
languages all present, R-3.1); ``is_sandbox`` is set here and only here
(R-3.7); creating writes ``POLL_CREATED`` (§10); and the commune admin who
creates a poll gains no role on it by doing so (§3.7) — the same split
``test_backoffice_accounts.py`` pins for role assignment.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.audit.models import Action, AuditEvent
from apps.backoffice.access import has_poll_role
from apps.core.models import Role, User
from apps.elections.models import Poll, PollState

URL = "/fr/mairie/nouveau/"


@pytest.fixture
def commune_admin(db: None) -> User:
    return User.objects.create_user(
        username="c.admin", password="x", full_name="C. Admin", is_commune_admin=True
    )


@pytest.fixture
def plain_operator(db: None) -> User:
    return User.objects.create_user(username="m.durand", password="x", full_name="M. Durand")


@pytest.fixture
def admin_client(client: Client, commune_admin: User) -> Client:
    client.force_login(commune_admin)
    return client


def _dt(value: object) -> str:
    return timezone.localtime(value).strftime("%Y-%m-%dT%H:%M")  # type: ignore[arg-type]


def _payload(**overrides: object) -> dict[str, object]:
    now = timezone.now()
    data: dict[str, object] = {
        "opens_at": _dt(now + timedelta(days=1)),
        "closes_at": _dt(now + timedelta(days=8)),
        "paper_entry_deadline": _dt(now + timedelta(days=8)),
        "timezone": "Europe/Paris",
        "tally_method": "schulze",
        "tally_method_version": "1",
        "tiebreak_rule": "computed",
        "eligible_list_types": ["principale"],
        "default_language": "fr",
        "extra_languages": [],
        "title_fr": "Aménagement de la place",
        "description_fr": "Deux propositions.",
        "opt-TOTAL_FORMS": "2",
        "opt-INITIAL_FORMS": "0",
        "opt-MIN_NUM_FORMS": "0",
        "opt-MAX_NUM_FORMS": "1000",
        "opt-0-option_id": "a",
        "opt-0-label_fr": "Option A",
        "opt-1-option_id": "b",
        "opt-1-label_fr": "Option B",
    }
    data.update(overrides)
    return data


# --- the gate (§3.7) -------------------------------------------------------


def test_anonymous_is_sent_to_the_login_page(client: Client, db: None) -> None:
    response = client.get(URL)
    assert response.status_code == 302
    assert "/mairie/connexion/" in response["Location"]


def test_a_plain_operator_is_refused(client: Client, plain_operator: User) -> None:
    client.force_login(plain_operator)
    assert client.get(URL).status_code == 403


def test_a_superuser_flag_is_not_consulted(client: Client, db: None) -> None:
    stray = User.objects.create_user(username="root", password="x")
    stray.is_superuser = True
    stray.is_staff = True
    stray.save(update_fields=["is_superuser", "is_staff"])
    client.force_login(stray)
    assert client.get(URL).status_code == 403


def test_a_commune_admin_reaches_the_screen(admin_client: Client) -> None:
    assert admin_client.get(URL).status_code == 200


# --- creation (R-3.1, R-3.7, §10) ------------------------------------------


def test_creating_a_poll_persists_a_valid_draft(admin_client: Client) -> None:
    response = admin_client.post(URL, _payload(), follow=False)
    assert response.status_code == 302

    poll = Poll.objects.get(title_i18n__fr="Aménagement de la place")
    assert poll.state == PollState.DRAFT
    assert poll.is_sandbox is False
    assert poll.languages == ["fr"]
    assert [o.option_id for o in poll.options.order_by("position")] == ["a", "b"]
    assert poll.missing_translations() == []

    event = AuditEvent.objects.get(action=Action.POLL_CREATED, poll=poll)
    assert event.object_ref == f"poll:{poll.pk}"
    assert event.actor is not None


def test_the_sandbox_flag_is_set_at_creation(admin_client: Client) -> None:
    admin_client.post(URL, _payload(is_sandbox="on"))
    poll = Poll.objects.get(title_i18n__fr="Aménagement de la place")
    assert poll.is_sandbox is True


def test_creating_grants_no_role_on_the_new_poll(admin_client: Client, commune_admin: User) -> None:
    """§3.7's split, at creation as much as at grant time (see
    test_backoffice_accounts.test_granting_a_role_is_still_not_access_for_the_commune_admin):
    creating a poll is not a way into its screens."""
    admin_client.post(URL, _payload())
    poll = Poll.objects.get(title_i18n__fr="Aménagement de la place")
    assert not has_poll_role(commune_admin, poll, Role.POLL_ADMIN)
    assert admin_client.get(f"/fr/mairie/scrutin/{poll.pk}/").status_code == 403


def test_creating_redirects_to_role_assignment_for_the_new_poll(admin_client: Client) -> None:
    response = admin_client.post(URL, _payload())
    poll = Poll.objects.get(title_i18n__fr="Aménagement de la place")
    assert response["Location"] == f"/fr/mairie/comptes/roles/?scrutin={poll.pk}"


def test_fewer_than_two_propositions_is_refused(admin_client: Client) -> None:
    """§3.1: an ordered list of at least two options."""
    data = _payload()
    data["opt-1-option_id"] = ""
    data["opt-1-label_fr"] = ""
    response = admin_client.post(URL, data)

    assert response.status_code == 200
    assert "au moins deux propositions" in response.content.decode()
    assert not Poll.objects.filter(title_i18n__fr="Aménagement de la place").exists()
    assert not AuditEvent.objects.filter(action=Action.POLL_CREATED).exists()


def test_a_mostly_blank_submission_reports_every_failing_tab(admin_client: Client) -> None:
    """A poll created with almost every field left empty fails validation on
    several of the tabbed panels at once (§6.5.2): too few propositions and
    missing calendar dates. static/js/tabs.js only ever opens the first
    failing tab, so every field-level error the server renders here must
    actually reach the page — the survivor otherwise sits in a tab nothing
    ever points the operator at. The container also carries the label
    tabs.js flags the other failing tabs with, so that marking degrades
    gracefully rather than silently doing nothing without it.
    """
    data = _payload()
    del data["opens_at"], data["closes_at"], data["paper_entry_deadline"]
    data["opt-1-option_id"] = ""
    data["opt-1-label_fr"] = ""
    response = admin_client.post(URL, data)

    assert response.status_code == 200
    content = response.content.decode()
    assert "au moins deux propositions" in content
    assert content.count("Ce champ est obligatoire") >= 3
    assert "data-tabs-error-label=" in content
    assert not Poll.objects.filter(title_i18n__fr="Aménagement de la place").exists()


def test_a_closing_instant_before_the_opening_one_is_refused(admin_client: Client) -> None:
    now = timezone.now()
    data = _payload(closes_at=_dt(now))
    response = admin_client.post(URL, data)

    assert response.status_code == 200
    assert not Poll.objects.filter(title_i18n__fr="Aménagement de la place").exists()
