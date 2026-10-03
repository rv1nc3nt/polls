# SPDX-License-Identifier: 0BSD
"""The error pages Django would otherwise show in English (review A-14)."""

from __future__ import annotations

from typing import Any

import pytest
from django.http import HttpRequest
from django.template import loader
from django.test import Client
from django.urls import reverse
from django.utils import translation
from django.views import defaults
from django.views.csrf import csrf_failure

from apps.core.models import User


def test_the_server_error_page_is_french_and_queries_nothing(
    django_assert_num_queries: Any, db: None
) -> None:
    """Rendered as Django renders it, without the request: the database may
    be what failed."""
    with translation.override("fr"), django_assert_num_queries(0):
        body = loader.get_template("500.html").render()
    assert "Erreur du serveur" in body
    assert "Server Error" not in body


def test_an_unhandled_exception_shows_the_french_page(rf: Any, db: None) -> None:
    request: HttpRequest = rf.get("/fr/")
    with translation.override("fr"):
        response = defaults.server_error(request)
    assert response.status_code == 500
    assert "Erreur du serveur" in response.content.decode()


def test_a_bad_request_shows_the_french_page(rf: Any, db: None) -> None:
    request: HttpRequest = rf.get("/fr/")
    with translation.override("fr"):
        response = defaults.bad_request(request, Exception())
    assert response.status_code == 400
    assert "Requête incorrecte" in response.content.decode()


@pytest.fixture
def operator(db: None) -> User:
    return User.objects.create_user(username="j.mercier", password="un mot de passe sûr")


def test_a_form_posted_without_its_csrf_token_gets_the_french_page(operator: User) -> None:
    client = Client(enforce_csrf_checks=True)
    response = client.post(reverse("backoffice:login"), {"username": "j.mercier", "password": "x"})
    assert response.status_code == 403
    body = response.content.decode()
    assert "Formulaire non envoyé" in body
    assert "CSRF verification failed" not in body


def test_the_csrf_page_never_shows_djangos_technical_reason(rf: Any, db: None) -> None:
    request: HttpRequest = rf.post("/fr/mairie/connexion/")
    with translation.override("fr"):
        response = csrf_failure(request, reason="CSRF cookie not set.")
    assert "CSRF cookie not set" not in response.content.decode()


def test_the_server_error_page_follows_the_active_language(db: None) -> None:
    with translation.override("en"):
        body = loader.get_template("500.html").render()
    assert "Server error" in body
    assert 'lang="en"' in body
