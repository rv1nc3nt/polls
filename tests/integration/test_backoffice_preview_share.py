# SPDX-License-Identifier: 0BSD
"""Screen 2's *partager cet aperçu* (R-3.10 bis).

Generating, regenerating and revoking the unguessable draft-preview link —
POLL_ADMIN only, each action logged without the token itself ever reaching
the audit row (INV-3). The link's own behaviour (mutability, redirect once
the poll leaves ``draft``) is covered in ``test_publicsite.py``'s T-84/T-85;
this file is the back-office side that mints and manages it.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.audit.models import Action, AuditEvent
from apps.core.models import PollRole, Role, User
from apps.elections.models import Poll


@pytest.fixture
def admin_user(db: None) -> User:
    return User.objects.create_user(username="p.martin", password="x", full_name="P. Martin")


@pytest.fixture
def auditor_user(db: None) -> User:
    return User.objects.create_user(username="p.audit", password="x", full_name="P. Audit")


def _grant(poll: Poll, user: User, role: Role) -> None:
    PollRole.objects.create(poll=poll, user=user, role=role)


def _url(poll: Poll) -> str:
    return f"/fr/mairie/scrutin/{poll.pk}/apercu/"


def test_no_link_by_default_and_the_form_offers_to_generate_one(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    body = client.get(_url(open_window_poll)).content.decode()
    assert 'value="generate_preview_link"' in body
    assert 'value="revoke_preview_link"' not in body
    assert not open_window_poll.preview_token


def test_generating_sets_a_token_shows_the_url_and_is_audited(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    response = client.post(_url(open_window_poll), {"action": "generate_preview_link"})
    assert response.status_code == 302
    open_window_poll.refresh_from_db()
    assert open_window_poll.preview_token

    event = AuditEvent.objects.get(action=Action.PREVIEW_LINK_GENERATED, poll=open_window_poll)
    assert open_window_poll.preview_token not in str(event.before)
    assert open_window_poll.preview_token not in str(event.after)

    body = client.get(_url(open_window_poll)).content.decode()
    assert f"/apercu/{open_window_poll.preview_token}/" in body
    assert 'value="revoke_preview_link"' in body


def test_regenerating_replaces_the_token_invalidating_the_old_one(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    client.post(_url(open_window_poll), {"action": "generate_preview_link"})
    open_window_poll.refresh_from_db()
    old_token = open_window_poll.preview_token
    old_share_url = f"/fr/scrutin/{open_window_poll.pk}/apercu/{old_token}/"
    assert client.get(old_share_url).status_code == 200

    client.post(_url(open_window_poll), {"action": "generate_preview_link"})
    open_window_poll.refresh_from_db()
    assert open_window_poll.preview_token != old_token
    assert client.get(old_share_url).status_code == 404
    new_share_url = f"/fr/scrutin/{open_window_poll.pk}/apercu/{open_window_poll.preview_token}/"
    assert client.get(new_share_url).status_code == 200

    assert AuditEvent.objects.filter(action=Action.PREVIEW_LINK_GENERATED).count() == 2


def test_revoking_clears_the_token_and_is_audited(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    client.post(_url(open_window_poll), {"action": "generate_preview_link"})
    open_window_poll.refresh_from_db()
    share_url = f"/fr/scrutin/{open_window_poll.pk}/apercu/{open_window_poll.preview_token}/"

    response = client.post(_url(open_window_poll), {"action": "revoke_preview_link"})
    assert response.status_code == 302
    open_window_poll.refresh_from_db()
    assert open_window_poll.preview_token == ""
    assert client.get(share_url).status_code == 404
    assert AuditEvent.objects.filter(
        action=Action.PREVIEW_LINK_REVOKED, poll=open_window_poll
    ).exists()

    body = client.get(_url(open_window_poll)).content.decode()
    assert 'value="generate_preview_link"' in body
    assert 'value="revoke_preview_link"' not in body


def test_an_auditor_cannot_generate_or_revoke_but_reads_an_existing_link(
    client: Client, open_window_poll: Poll, admin_user: User, auditor_user: User
) -> None:
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    _grant(open_window_poll, auditor_user, Role.AUDITOR)
    client.force_login(admin_user)
    client.post(_url(open_window_poll), {"action": "generate_preview_link"})
    open_window_poll.refresh_from_db()
    token = open_window_poll.preview_token

    client.force_login(auditor_user)
    response = client.post(_url(open_window_poll), {"action": "generate_preview_link"})
    assert response.status_code == 403
    response = client.post(_url(open_window_poll), {"action": "revoke_preview_link"})
    assert response.status_code == 403
    open_window_poll.refresh_from_db()
    assert open_window_poll.preview_token == token

    body = client.get(_url(open_window_poll)).content.decode()
    assert f"/apercu/{token}/" in body
    assert 'value="generate_preview_link"' not in body
    assert 'value="revoke_preview_link"' not in body
