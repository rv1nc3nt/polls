# SPDX-License-Identifier: 0BSD
"""The manual, served from ``docs/manuel/`` (apps.core.manual, §6.6, §6.5).

Public pages need no account; the mairie-area ones need any working
operator account and no particular role (``require_operator``,
``apps.backoffice.access``) — reading documentation is not itself an access
to a poll's data, unlike every screen ``test_backoffice_access.py`` covers.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.utils.html import escape

from apps.core.models import User


@pytest.fixture
def operator(db: None) -> User:
    return User.objects.create_user(username="m.durand", password="x", full_name="M. Durand")


# --- Public site -------------------------------------------------------


def test_the_help_index_lists_the_three_public_documents(client: Client, db: None) -> None:
    body = client.get("/fr/aide/").content.decode()
    assert escape("Guide de l'électeur") in body
    assert "Vérifier un résultat par vous-même" in body
    assert "Foire aux questions" in body


@pytest.mark.parametrize("slug", ["electeur", "verifier", "faq"])
def test_each_public_document_renders_in_french(client: Client, db: None, slug: str) -> None:
    response = client.get(f"/fr/aide/{slug}/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "<h2 id=" in body or "<h3 id=" in body


@pytest.mark.parametrize("slug", ["electeur", "verifier", "faq"])
def test_each_public_document_renders_in_english(client: Client, db: None, slug: str) -> None:
    response = client.get(f"/en/aide/{slug}/")
    assert response.status_code == 200


def test_the_public_faq_shows_only_the_electeur_section(client: Client, db: None) -> None:
    body = client.get("/fr/aide/faq/").content.decode()
    assert "Mon vote est-il vraiment secret" in body
    assert "Espace mairie" not in body
    assert escape("Administrateur d'instance") not in body


def test_a_link_from_verifier_to_the_voter_guide_resolves_to_a_real_url(
    client: Client, db: None
) -> None:
    body = client.get("/fr/aide/verifier/").content.decode()
    assert 'href="/fr/aide/electeur/#8-v' in body


def test_an_unknown_public_slug_is_a_404(client: Client, db: None) -> None:
    assert client.get("/fr/aide/nonexistent/").status_code == 404


def test_a_screenshot_referenced_by_the_voter_guide_is_served(client: Client, db: None) -> None:
    response = client.get("/fr/aide/images/01-site-public-liste.png")
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"


def test_an_unknown_public_image_is_a_404(client: Client, db: None) -> None:
    assert client.get("/fr/aide/images/../settings.py").status_code == 404
    assert client.get("/fr/aide/images/nonexistent.png").status_code == 404


# --- Mairie area ---------------------------------------------------------


def test_anonymous_is_sent_to_the_login_page(client: Client, db: None) -> None:
    response = client.get("/fr/mairie/aide/")
    assert response.status_code == 302
    assert "/mairie/connexion/" in response["Location"]


def test_any_signed_in_operator_reaches_the_index_with_no_role_at_all(
    client: Client, operator: User
) -> None:
    client.force_login(operator)
    body = client.get("/fr/mairie/aide/").content.decode()
    assert escape("Guide de l'espace mairie") in body
    assert "Foire aux questions" in body


def test_the_mairie_area_document_renders(client: Client, operator: User) -> None:
    client.force_login(operator)
    response = client.get("/fr/mairie/aide/espace-mairie/")
    assert response.status_code == 200
    assert "commune_admin" in response.content.decode()


def test_the_mairie_area_faq_shows_only_the_espace_mairie_section(
    client: Client, operator: User
) -> None:
    client.force_login(operator)
    body = client.get("/fr/mairie/aide/faq/").content.decode()
    assert "Peut-on revenir de" in body
    assert "Mon vote est-il vraiment secret" not in body
    assert "Puis-je faire tourner plusieurs communes" not in body


def test_a_mairie_area_screenshot_is_served_once_signed_in(client: Client, operator: User) -> None:
    client.force_login(operator)
    response = client.get("/fr/mairie/aide/images/06-mairie-connexion.png")
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"


def test_a_mairie_area_screenshot_requires_sign_in(client: Client, db: None) -> None:
    response = client.get("/fr/mairie/aide/images/06-mairie-connexion.png")
    assert response.status_code == 302
    assert "/mairie/connexion/" in response["Location"]
