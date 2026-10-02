# SPDX-License-Identifier: 0BSD
"""A poll's own time zone, for what the back office reads and writes (review
A-8, decision log #45).

A poll stores its zone (§3.1) and the public page shows its dates in it; the
back office parsed what an operator typed in the server's zone instead, so a
commune whose poll was not in Europe/Paris typed one hour and was shown
another on the page confirming it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.test import Client
from django.utils import timezone

from apps.audit.models import Reason
from apps.core.models import PollRole, Role, User
from apps.elections.models import Poll
from tests.conftest import force_open
from tests.integration.test_backoffice_config import _payload

CAYENNE = ZoneInfo("America/Cayenne")  # UTC−3, no clock changes
PARIS = ZoneInfo("Europe/Paris")


@pytest.fixture
def admin(open_window_poll: Poll) -> User:
    user = User.objects.create_user(username="tz.admin", password="x")
    PollRole.objects.create(poll=open_window_poll, user=user, role=Role.POLL_ADMIN)
    return user


def _url(poll: Poll, screen: str = "configuration/") -> str:
    return f"/fr/mairie/scrutin/{poll.pk}/{screen}"


def _with_dates(poll: Poll, zone: str, opens: str, closes: str) -> dict[str, object]:
    return {
        **_payload(poll),
        "timezone": zone,
        "opens_at": opens,
        "closes_at": closes,
        "paper_entry_deadline": closes,
    }


def test_dates_typed_on_a_poll_are_read_in_its_zone_and_shown_back_in_it(
    client: Client, open_window_poll: Poll, admin: User
) -> None:
    Poll.objects.filter(pk=open_window_poll.pk).update(timezone="America/Cayenne")
    poll = Poll.objects.get(pk=open_window_poll.pk)
    client.force_login(admin)

    response = client.post(
        _url(poll), _with_dates(poll, "America/Cayenne", "2027-01-15T20:00", "2027-01-22T20:00")
    )
    assert response.status_code == 302, response.content.decode()[:500]
    poll.refresh_from_db()
    assert poll.opens_at == datetime(2027, 1, 15, 20, 0, tzinfo=CAYENNE)

    form = client.get(_url(poll)).content.decode()
    assert 'value="2027-01-15T20:00"' in form
    dashboard = client.get(_url(poll, "")).content.decode()
    assert "15 janvier 2027 20:00" in dashboard


def test_a_zone_changed_in_the_same_submission_governs_its_dates(
    client: Client, open_window_poll: Poll, admin: User
) -> None:
    """The operator who switches the poll to Cayenne and types 20:00 means
    20:00 in Cayenne, not in the zone the poll had a moment before."""
    client.force_login(admin)
    assert open_window_poll.timezone == "Europe/Paris"
    response = client.post(
        _url(open_window_poll),
        _with_dates(open_window_poll, "America/Cayenne", "2027-01-15T20:00", "2027-01-22T20:00"),
    )
    assert response.status_code == 302
    open_window_poll.refresh_from_db()
    assert open_window_poll.opens_at == datetime(2027, 1, 15, 20, 0, tzinfo=CAYENNE)


def test_a_time_the_clock_change_skips_is_refused(
    client: Client, open_window_poll: Poll, admin: User
) -> None:
    """02:30 on 28 March 2027 does not exist in Paris: refused, not guessed."""
    client.force_login(admin)
    before = Poll.objects.get(pk=open_window_poll.pk).opens_at
    response = client.post(
        _url(open_window_poll),
        _with_dates(open_window_poll, "Europe/Paris", "2027-03-28T02:30", "2027-04-04T20:00"),
    )
    assert response.status_code == 200
    assert Poll.objects.get(pk=open_window_poll.pk).opens_at == before


def test_an_extension_is_read_in_the_polls_zone(
    client: Client, open_window_poll: Poll, admin: User
) -> None:
    Poll.objects.filter(pk=open_window_poll.pk).update(timezone="America/Cayenne")
    poll = force_open(Poll.objects.get(pk=open_window_poll.pk))
    client.force_login(admin)
    target = timezone.localtime(poll.closes_at + timedelta(days=3), CAYENNE).replace(
        hour=21, minute=0, second=0, microsecond=0
    )
    data = {
        "new_closes_at": target.strftime("%Y-%m-%dT%H:%M"),
        "reason": Reason.ADMINISTRATIVE_DECISION,
    }
    confirm = client.post(_url(poll), data).content.decode()
    assert target.strftime("%H:%M") in confirm  # the confirmation shows what was typed
    assert client.post(_url(poll), {**data, "confirmed": "1"}).status_code == 302
    poll.refresh_from_db()
    assert poll.closes_at == target


def test_the_poll_list_shows_each_poll_in_its_own_zone(
    client: Client, open_window_poll: Poll, admin: User
) -> None:
    closes = datetime(2027, 1, 22, 20, 0, tzinfo=CAYENNE)
    Poll.objects.filter(pk=open_window_poll.pk).update(
        timezone="America/Cayenne", closes_at=closes, paper_entry_deadline=closes
    )
    admin.is_commune_admin = True
    admin.save(update_fields=["is_commune_admin"])
    client.force_login(admin)
    body = client.get("/fr/mairie/").content.decode()
    assert "22 janvier 2027 20:00" in body
    assert closes.astimezone(PARIS).strftime("%H:%M") == "00:00"  # what it used to show
