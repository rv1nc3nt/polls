# SPDX-License-Identifier: 0BSD
"""Every page names the software's licence and links to its source.

In the footer of ``base.html``, outside the ``footer_tools`` block the espace
mairie empties, so the back office carries it too. The link names GitHub and
shows its mark only when it points there (``apps.core.context.software``).
"""

from __future__ import annotations

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from apps.core.models import User

LICENCE = 'href="https://spdx.org/licenses/0BSD.html"'
MARK = '<use href="#pub-ico-github"/>'


@pytest.mark.django_db
def test_the_public_site_names_the_licence_and_links_to_github(client: Client) -> None:
    body = client.get("/fr/").content.decode()
    assert "Logiciel libre sous licence" in body
    assert LICENCE in body
    assert 'href="https://github.com/rv1nc3nt/polls"' in body
    assert MARK in body
    assert "Code source sur GitHub" in body


@pytest.mark.django_db
def test_the_espace_mairie_carries_it_too(client: Client) -> None:
    # With no account at all, the login page redirects to the first run.
    User.objects.create_user(username="op", password="x")
    response = client.get(reverse("backoffice:login"))
    assert response.status_code == 200
    body = response.content.decode()
    assert LICENCE in body
    assert MARK in body


@pytest.mark.django_db
def test_it_is_translated(client: Client) -> None:
    body = client.get("/en/").content.decode()
    assert "Free software, licensed under" in body
    assert "Source code on GitHub" in body


@pytest.mark.django_db
@override_settings(SOURCE_CODE_URL="https://git.example.fr/mairie/polls")
def test_a_fork_elsewhere_is_not_labelled_github(client: Client) -> None:
    body = client.get("/fr/").content.decode()
    assert 'href="https://git.example.fr/mairie/polls"' in body
    assert "Code source" in body
    assert "GitHub" not in body.split('class="software"')[1]
    assert MARK not in body
