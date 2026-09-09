# SPDX-License-Identifier: 0BSD
"""Screen 11 of §6.5 — première installation, the first-run wizard.

It exists so an adopting commune goes from a fresh database to a usable
instance without ``createsuperuser`` (§6.5.11, §14). The things it must get
right: it is reachable only while no account exists, it creates the commune
record and the initial ``commune_admin`` together, and — unlike every other
back-office screen — it is behind neither a per-poll role nor the commune-admin
flag, because it runs before either can exist.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction
from django.test import Client

from apps.audit.models import AuditEvent
from apps.core.models import Commune, PollRole, User

WIZARD_URL = "/fr/mairie/installation/"
LOGIN_URL = "/fr/mairie/connexion/"
INDEX_URL = "/fr/mairie/"

VALID = {
    "commune_name": "Sainte-Marie-du-Mont",
    "data_protection_referent": "Secrétariat de mairie",
    "data_protection_contact": "rgpd@sainte-marie-du-mont.example.fr",
    "username": "m.maire",
    "full_name": "M. le Maire",
    "raw_password": "corrège-cheval-agrafe-42",
    "raw_password_confirm": "corrège-cheval-agrafe-42",
}


# --- the gate: open only on a fresh instance ----------------------------


def test_a_fresh_instance_serves_the_wizard(client: Client, db: None) -> None:
    response = client.get(WIZARD_URL)
    assert response.status_code == 200
    assert "Première installation" in response.content.decode()


def test_the_login_page_redirects_to_the_wizard_on_a_fresh_instance(
    client: Client, db: None
) -> None:
    """A sign-in form nobody can pass is worse than a pointer to the thing that
    creates the first account."""
    response = client.get(LOGIN_URL)
    assert response.status_code == 302
    assert response["Location"] == WIZARD_URL


def test_the_poll_index_leads_to_the_wizard_on_a_fresh_instance(client: Client, db: None) -> None:
    response = client.get(INDEX_URL, follow=True)
    assert response.status_code == 200
    assert response.request["PATH_INFO"] == WIZARD_URL


def test_the_wizard_closes_once_an_account_exists(client: Client, db: None) -> None:
    User.objects.create_user(username="someone", password="x")
    assert client.get(WIZARD_URL).status_code == 302
    assert client.get(WIZARD_URL)["Location"] == LOGIN_URL


def test_a_closed_wizard_writes_nothing_on_post(client: Client, db: None) -> None:
    User.objects.create_user(username="someone", password="x")
    client.post(WIZARD_URL, VALID)
    assert Commune.current() is None
    assert User.objects.count() == 1


# --- a successful install ---------------------------------------------


def test_the_wizard_creates_the_commune_and_the_administrator(client: Client, db: None) -> None:
    response = client.post(WIZARD_URL, VALID, follow=True)
    assert response.status_code == 200
    assert response.request["PATH_INFO"] == INDEX_URL

    commune = Commune.current()
    assert commune is not None
    assert commune.name == "Sainte-Marie-du-Mont"
    assert commune.data_protection_referent == "Secrétariat de mairie"

    admin = User.objects.get(username="m.maire")
    assert admin.is_commune_admin
    assert admin.is_active
    assert not admin.is_superuser
    assert admin.full_name == "M. le Maire"
    assert admin.check_password("corrège-cheval-agrafe-42")


def test_the_wizard_signs_the_new_administrator_in(client: Client, db: None) -> None:
    client.post(WIZARD_URL, VALID)
    body = client.get(INDEX_URL).content.decode()
    assert body.count("M. le Maire")  # the account name shown on the shell (R-2.2)


def test_the_new_administrator_holds_no_per_poll_role(client: Client, db: None) -> None:
    """§3.7: the commune-admin flag creates polls and assigns their roles; it
    is not itself a role on any poll."""
    client.post(WIZARD_URL, VALID)
    assert not PollRole.objects.filter(user__username="m.maire").exists()


def test_the_wizard_writes_no_audit_event(client: Client, db: None) -> None:
    """Consistent with ``accounts.create_account``: there is no operator yet
    and no ``Action`` code for installing the instance (§10)."""
    client.post(WIZARD_URL, VALID)
    assert AuditEvent.objects.count() == 0


# --- shape validation, all-or-nothing --------------------------------


def test_a_weak_password_is_refused_and_nothing_is_written(client: Client, db: None) -> None:
    payload = VALID | {"raw_password": "court", "raw_password_confirm": "court"}
    response = client.post(WIZARD_URL, payload)
    assert response.status_code == 200
    assert Commune.current() is None
    assert not User.objects.exists()


def test_a_mismatched_confirmation_is_refused(client: Client, db: None) -> None:
    payload = VALID | {"raw_password_confirm": "autre-chose-entièrement"}
    response = client.post(WIZARD_URL, payload)
    assert response.status_code == 200
    assert "diffèrent" in response.content.decode()
    assert not User.objects.exists()


def test_a_missing_referent_is_refused(client: Client, db: None) -> None:
    """R-13.2: the notice must name a referent, so the wizard makes it a
    required field rather than storing an empty one."""
    payload = VALID | {"data_protection_referent": ""}
    client.post(WIZARD_URL, payload)
    assert Commune.current() is None
    assert not User.objects.exists()


# --- the commune record is a singleton -------------------------------


def test_the_commune_record_cannot_be_duplicated(client: Client, db: None) -> None:
    client.post(WIZARD_URL, VALID)
    with pytest.raises(IntegrityError), transaction.atomic():
        Commune.objects.create(
            id=2, name="Ailleurs", data_protection_referent="x", data_protection_contact="y"
        )
