# SPDX-License-Identifier: 0BSD
"""The trend screen over HTTP (R-11.5 bis): offered only on a poll configured
for it, to the poll admin and the auditor, never with the day in progress
while the poll is open, and never with a count per option."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.ballots.models import Ballot, BallotSource, BallotStatus
from apps.core.codes import new_tracking_code
from apps.core.models import PollRole, Role, User
from apps.elections.models import Poll, PollState
from tests.conftest import force_open


@pytest.fixture
def poll(open_window_poll: Poll) -> Poll:
    # Backdated ballots must still fall inside the window the triggers check.
    Poll.objects.filter(pk=open_window_poll.pk).update(opens_at=timezone.now() - timedelta(days=10))
    open_window_poll.refresh_from_db()
    return force_open(open_window_poll)


@pytest.fixture
def admin(poll: Poll) -> User:
    user = User.objects.create_user(username="p.admin", password="x", full_name="P. Admin")
    PollRole.objects.create(poll=poll, user=user, role=Role.POLL_ADMIN)
    return user


def _url(poll: Poll) -> str:
    return f"/fr/mairie/scrutin/{poll.pk}/tendance/"


def _cast(poll: Poll, ranking: list[list[str]], n: int, *, days_ago: int) -> None:
    for _ in range(n):
        ballot = Ballot.objects.create(
            poll=poll,
            tracking_code=new_tracking_code(),
            ranking=ranking,
            source=BallotSource.ONLINE,
        )
        Ballot.objects.filter(pk=ballot.pk).update(
            created_at=timezone.now() - timedelta(days=days_ago)
        )


def _three_points(poll: Poll) -> None:
    """40 ballots: points at 10, 20 and 30 are shown, 40 waits for the 45th."""
    _cast(poll, [["a"], ["b"], ["c"]], 10, days_ago=3)
    _cast(poll, [["b"], ["c"], ["a"]], 20, days_ago=2)
    _cast(poll, [["c"], ["a"], ["b"]], 10, days_ago=1)


def _enabled(poll: Poll) -> override_settings:
    return override_settings(TREND_POLL_IDS=frozenset({poll.pk}))


def test_a_poll_not_configured_for_it_has_no_trend(client: Client, poll: Poll, admin: User) -> None:
    """R-11.5: elsewhere no interface discloses a running count."""
    client.force_login(admin)
    assert client.get(_url(poll)).status_code == 404
    assert "/tendance/" not in client.get(f"/fr/mairie/scrutin/{poll.pk}/").content.decode()


def test_the_admin_sees_the_standing_as_of_the_last_point_shown(
    client: Client, poll: Poll, admin: User
) -> None:
    """Today's ballots count like any others; point 40 waits for five more
    ballots, so the 10 cast last are not in any point yet."""
    _cast(poll, [["a"], ["b"], ["c"]], 10, days_ago=3)
    _cast(poll, [["b"], ["c"], ["a"]], 20, days_ago=2)
    _cast(poll, [["c"], ["a"], ["b"]], 10, days_ago=0)
    client.force_login(admin)
    with _enabled(poll):
        response = client.get(_url(poll))
        dashboard = client.get(f"/fr/mairie/scrutin/{poll.pk}/").content.decode()
    assert response.status_code == 200
    rows = response.context["rows"]  # newest first
    assert [r["count"] for r in rows] == [30, 20, 10]
    assert [c["rank"] for c in rows[0]["cells"]] == [3, 1, 2]
    assert response.context["curves"] is not None

    # b beats c 30–0 and a 20–10: its tightest duel is a, by 10 of 30 ballots.
    summary = response.context["summary"]
    assert summary["leaders"] == ["B"]
    assert summary["condorcet"] == "B"
    assert summary["lead"]["rival"] == "A"
    assert summary["lead"]["ballots"] == 10

    duels = {(d["left"]["label"], d["right"]["label"]): d for d in response.context["duels"]}
    assert duels[("B", "C")]["left"]["count"] == 30
    assert duels[("B", "C")]["right"]["count"] == 0
    assert duels[("B", "A")]["margin_ballots"] == 10
    # The duels involving the leader come first.
    assert {response.context["duels"][0]["left"]["label"]} == {"B"}
    assert _url(poll) in dashboard


def test_too_few_ballots_show_a_notice(client: Client, poll: Poll, admin: User) -> None:
    _cast(poll, [["a"], ["b"], ["c"]], 9, days_ago=1)
    client.force_login(admin)
    with _enabled(poll):
        response = client.get(_url(poll))
    assert response.context["has_points"] is False
    assert "Pas encore assez de bulletins" in response.content.decode()


def test_the_auditor_reads_it_and_the_entry_operator_does_not(client: Client, poll: Poll) -> None:
    auditor = User.objects.create_user(username="aud", password="x", full_name="Aud")
    operator = User.objects.create_user(username="op", password="x", full_name="Op")
    PollRole.objects.create(poll=poll, user=auditor, role=Role.AUDITOR)
    PollRole.objects.create(poll=poll, user=operator, role=Role.ENTRY_OPERATOR)
    with _enabled(poll):
        client.force_login(auditor)
        assert client.get(_url(poll)).status_code == 200
        client.force_login(operator)
        assert client.get(_url(poll)).status_code == 403


def test_a_withdrawn_poll_has_no_trend(client: Client, poll: Poll, admin: User) -> None:
    """R-3.11 takes every figure of a withdrawn poll off view."""
    Poll.objects.filter(pk=poll.pk).update(state=PollState.WITHDRAWN)
    client.force_login(admin)
    with _enabled(poll):
        assert client.get(_url(poll)).status_code == 404


def test_chart_coordinates_survive_the_french_locale(
    client: Client, poll: Poll, admin: User
) -> None:
    """A float rendered under ``fr`` takes a decimal comma, which SVG would
    read as a coordinate separator."""
    _three_points(poll)
    client.force_login(admin)
    with _enabled(poll):
        body = client.get(_url(poll)).content.decode()
    # The curves and every duel's sparkline: all the SVG the screen draws.
    drawn = body.split("data-trend-chart")[1]
    coordinates = re.findall(r'\s(?:cx|cy|x|y|x1|x2|y1|y2|width|height)="([^"]*)"', drawn)
    paths = " ".join(re.findall(r'\sd="([^"]*)"', drawn))
    numbers = re.sub(r"[MLZ,]", " ", paths).split()
    assert coordinates and numbers
    assert all(v.lstrip("-").isdigit() for v in coordinates + numbers)


def test_the_matrix_shows_the_latest_point_or_the_one_asked_for(
    client: Client, poll: Poll, admin: User
) -> None:
    _three_points(poll)
    client.force_login(admin)
    with _enabled(poll):
        latest = client.get(_url(poll)).context
        assert [p.arrivals for p in latest["matrix_points"]] == [30, 20, 10]
        earlier = client.get(_url(poll), {"point": "10"}).context
        bogus = client.get(_url(poll), {"point": "40"}).context
    # Row b, column a: 20 of 30 ballots rank b above a.
    assert latest["matrix"][1]["cells"][0] == {
        "self": False,
        "count": 20,
        "pct": pytest.approx(66.67, abs=0.01),
        "outcome": "win",
    }
    assert latest["matrix_point"].ballot_count == 30
    assert earlier["matrix_point"].ballot_count == 10
    assert earlier["matrix"][1]["cells"][0]["outcome"] == "loss"
    # A point not shown — 40 is still waiting — falls back to the latest.
    assert bogus["matrix_point"].ballot_count == 30


def test_ballots_per_ranking_follow_the_chosen_point(
    client: Client, poll: Poll, admin: User
) -> None:
    _three_points(poll)
    client.force_login(admin)
    with _enabled(poll):
        latest = client.get(_url(poll)).context["ballot_types"]
        earlier = client.get(_url(poll), {"point": "10"}).context["ballot_types"]
    assert [(r["count"], [[o["label"] for o in g] for g in r["groups"]]) for r in latest] == [
        (20, [["B"], ["C"], ["A"]]),
        (10, [["A"], ["B"], ["C"]]),
    ]
    assert [r["count"] for r in earlier] == [10]


def test_a_modified_ballot_leaves_the_points_already_shown_alone(
    client: Client, poll: Poll, admin: User
) -> None:
    """The leak this guards against: recomputing past points from the live set
    would drop a modified ballot's old version from them, and the difference
    between two views would be that one old ranking."""
    _three_points(poll)
    client.force_login(admin)
    with _enabled(poll):
        before = [r["cells"] for r in client.get(_url(poll)).context["rows"]]
        old = Ballot.objects.filter(poll=poll).order_by("created_at").first()
        assert old is not None
        Ballot.objects.filter(pk=old.pk).update(status=BallotStatus.SUPERSEDED)
        Ballot.objects.create(
            poll=poll,
            tracking_code=old.tracking_code,
            version=2,
            ranking=[["c"], ["b"], ["a"]],
            source=BallotSource.ONLINE,
        )
        after = [r["cells"] for r in client.get(_url(poll)).context["rows"]]
    assert after == before


def test_duel_intervals_are_shown_while_open_and_gone_once_closed(
    client: Client, poll: Poll, admin: User
) -> None:
    """They describe the ballots still to come; the final result has none."""
    _three_points(poll)
    client.force_login(admin)
    with _enabled(poll):
        response = client.get(_url(poll))
        duel = next(d for d in response.context["duels"] if d["left"]["label"] == "B")
        assert duel["interval"] is not None
        assert duel["spark"]["band"].endswith("Z")
        assert response.context["summary"]["lead"]["interval"] is not None
        assert "à 95 %" in response.content.decode()
        Poll.objects.filter(pk=poll.pk).update(state=PollState.CLOSED)
        response = client.get(_url(poll))
    assert all(d["interval"] is None for d in response.context["duels"])
    assert all(d["spark"]["band"] is None for d in response.context["duels"])
    assert response.context["summary"]["lead"]["interval"] is None
    assert "à 95 %" not in response.content.decode()


def test_the_curves_band_the_leader_and_its_rival_and_the_tooltip_has_every_interval(
    client: Client, poll: Poll, admin: User
) -> None:
    """Every band at once would bury the lines: only the pair the lead is
    about gets one, the rest are read by hovering a point."""
    _three_points(poll)
    client.force_login(admin)
    with _enabled(poll):
        curves = client.get(_url(poll)).context["curves"]
        banded = {s["label"] for s in curves["series"] if s["band"]}
        assert banded == {"B", "A"}
        assert all(r["interval"] is not None for c in curves["columns"] for r in c["rows"])
        Poll.objects.filter(pk=poll.pk).update(state=PollState.CLOSED)
        curves = client.get(_url(poll)).context["curves"]
    assert not curves["banded"]
    assert all(s["band"] is None for s in curves["series"])
    assert all(r["interval"] is None for c in curves["columns"] for r in c["rows"])
