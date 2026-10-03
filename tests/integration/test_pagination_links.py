# SPDX-License-Identifier: 0BSD
"""Turning the page keeps the search exactly as typed (review A-15).

The links used to append ``&q=`` and the raw search to the URL, so a search
holding ``&``, ``#``, ``+`` or ``%`` came back changed on page 2, or brought
extra parameters with it. ``{% querystring %}`` encodes them.
"""

from __future__ import annotations

import re
from datetime import timedelta
from html import unescape
from urllib.parse import parse_qs, urlsplit

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import Action, AuditEvent
from apps.core.models import PollRole, Role, User
from apps.elections.models import Poll, PollOption, WorkingRollEntry
from tests.conftest import force_open

#: Every character the concatenated link mangled, and a space.
TRICKY = "a&b#c+d%e f"
ROWS = 51  # one more than a page on every screen here


@pytest.fixture
def admin(db: None) -> User:
    user = User.objects.create_user(username="c.admin", password="x", is_commune_admin=True)
    return user


def _next_link(body: str) -> str:
    match = re.search(r'<a href="([^"]*)">Page suivante</a>', body)
    assert match, "no next-page link"
    return unescape(match.group(1))


def _follow_and_check(client: Client, url: str, params: dict[str, str]) -> None:
    first = client.get(url, params)
    assert first.status_code == 200
    link = _next_link(first.content.decode())
    query = {k: v[0] for k, v in parse_qs(urlsplit(link).query, keep_blank_values=True).items()}
    assert query == {**params, "page": "2"}
    second = client.get(url + link)
    assert second.status_code == 200
    assert "Page 2 sur 2" in second.content.decode()


def _working_roll(count: int) -> None:
    WorkingRollEntry.objects.bulk_create(
        WorkingRollEntry(
            birth_name=f"Nom {TRICKY} {i:02d}",
            first_names="Prénom",
            date_of_birth="01/01/1970",
            date_of_birth_parsed="1970-01-01",
            list_types=["principale"],
        )
        for i in range(count)
    )


def _poll(title: str = "Scrutin") -> Poll:
    now = timezone.now()
    poll = Poll.objects.create(
        title_i18n={"fr": title},
        description_i18n={"fr": "…"},
        languages=["fr"],
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
    )
    for position, option_id in enumerate("ab"):
        PollOption.objects.create(
            poll=poll, option_id=option_id, label_i18n={"fr": option_id}, position=position
        )
    return poll


def test_the_working_roll_search(client: Client, admin: User) -> None:
    _working_roll(ROWS)
    client.force_login(admin)
    _follow_and_check(client, reverse("backoffice:roll_import"), {"q": TRICKY})


def test_a_polls_frozen_roll_search(client: Client, admin: User) -> None:
    _working_roll(ROWS)
    poll = force_open(_poll())
    PollRole.objects.create(poll=poll, user=admin, role=Role.POLL_ADMIN)
    client.force_login(admin)
    _follow_and_check(client, reverse("backoffice:roll_status", args=[poll.pk]), {"q": TRICKY})


def test_the_role_screens_poll_search(client: Client, admin: User) -> None:
    for i in range(ROWS):
        _poll(f"Scrutin {TRICKY} {i:02d}")
    client.force_login(admin)
    _follow_and_check(client, reverse("backoffice:role_admin"), {"q": TRICKY, "etat": "draft"})


def test_the_audit_logs_filters(client: Client, admin: User) -> None:
    poll = _poll()
    AuditEvent.objects.bulk_create(
        AuditEvent(poll=poll, action=Action.POLL_CREATED, object_ref=f"x:{TRICKY}:{i}")
        for i in range(ROWS)
    )
    PollRole.objects.create(poll=poll, user=admin, role=Role.AUDITOR)
    client.force_login(admin)
    today = timezone.localdate().isoformat()
    _follow_and_check(
        client,
        reverse("backoffice:audit_log", args=[poll.pk]),
        {"object": TRICKY, "date_from": today, "date_to": today},
    )
