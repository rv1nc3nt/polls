# SPDX-License-Identifier: 0BSD
"""The public results page draws the published result as the trend screen
draws its last point (``elections.resultcards``).

Every figure comes from the publication document (R-10.2), and nothing of the
trend itself is published (R-11.5 bis): no curves, no dated history.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from apps.audit.models import Reason
from apps.ballots.models import Ballot, BallotSource
from apps.core.models import User
from apps.core.types import OptionId
from apps.elections import closure, resultcards
from apps.elections.models import Poll, PollOption, TiebreakRule
from apps.elections.transitions import close_poll, publish_poll
from apps.registrations.models import Channel, Registration, RegistrationState
from tests.conftest import force_open

T9_MATRIX = {"a": {"b": 2, "c": 1}, "b": {"a": 1, "c": 2}, "c": {"a": 2, "b": 1}}


def _base(name: str) -> dict[str, Any]:
    """The figures the cards read, as a publication document states them: the
    T-9 cycle (Schulze) and the plurality case "plurality counts the first
    group" of tests/vectors."""
    if name == "T-9 document":
        return {
            "options": {"a": {}, "b": {}, "c": {}},
            "tally_method": "schulze",
            "ballot_count": 3,
            "matrix": T9_MATRIX,
            "derivation": {"pairwise": T9_MATRIX},
            "orderings": {"a>b>c": 1, "b>c>a": 1, "c>a>b": 1},
        }
    return {
        "options": {"a": {}, "b": {}, "c": {}},
        "tally_method": "plurality",
        "ballot_count": 4,
        "matrix": {"a": {"b": 2, "c": 3}, "b": {"a": 1, "c": 2}, "c": {"a": 1, "b": 1}},
        "derivation": {"counts": {"a": 2, "b": 1, "c": 1}, "winners": ["a"]},
    }


# --- the point is the published one ----------------------------------------------


def test_the_point_holds_the_published_figures() -> None:
    """The T-9 vector: every duel won 2 to 1 round a cycle. The point carries
    the document's matrix and orderings, and the cycle's standing."""
    document = _base("T-9 document")
    point = resultcards.published_standing(document, date(2026, 10, 1))
    assert point.ballot_count == 3
    assert point.pairwise == document["matrix"]
    assert point.counts is None
    assert point.condorcet_winner is None
    assert point.smith_set == ("a", "b", "c")
    assert point.orderings == {
        (("a",), ("b",), ("c",)): 1,
        (("b",), ("c",), ("a",)): 1,
        (("c",), ("a",), ("b",)): 1,
    }


def test_a_ranking_tied_within_a_group_keeps_the_poll_order() -> None:
    """``orderings`` keys sort a group by code point; the point keys it in the
    poll's option order, as the trend does."""
    document = _base("T-9 document")
    document["options"] = {"c": {}, "a": {}, "b": {}}
    document["orderings"] = {"a=c>b": 3}
    point = resultcards.published_standing(document, date(2026, 10, 1))
    assert point.orderings == {(("c", "a"), ("b",)): 3}


def test_the_counts_are_the_published_ones() -> None:
    document = _base("plurality document")
    point = resultcards.published_standing(document, date(2026, 10, 1))
    assert point.counts == {"a": 2, "b": 1, "c": 1}
    rows = resultcards.vote_counts(point, [(OptionId(o), o.upper()) for o in "abc"])
    assert [(r["label"], r["count"], r["rank"]) for r in rows] == [
        ("A", 2, 1),
        ("B", 1, 2),
        ("C", 1, 2),
    ]


# --- the page ---------------------------------------------------------------------


def _published(method: str, rankings: list[list[list[str]]], **config: object) -> Poll:
    now = timezone.now()
    poll = Poll.objects.create(
        title_i18n={"fr": "Place du marché"},
        description_i18n={"fr": "Trois propositions."},
        languages=["fr"],
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
        tally_method=method,
        allow_ties_in_ballot=True,
        **config,
    )
    for position, (option_id, label) in enumerate(
        [("a", "Fontaine"), ("b", "Kiosque"), ("c", "Pelouse")]
    ):
        PollOption.objects.create(
            poll=poll, option_id=option_id, label_i18n={"fr": label}, position=position
        )
    force_open(poll)
    for k, ranking in enumerate(rankings):
        Registration.objects.create(
            poll=poll,
            declared_last_name="X",
            declared_first_names="Y",
            email=f"v{k}@example.fr",
            email_canonical=f"v{k}@example.fr",
            state=RegistrationState.ACTIVE,
            channel=Channel.ONLINE,
        )
        Ballot.objects.create(
            poll=poll,
            tracking_code=f"AAAAAA{2222 + k}",
            ranking=ranking,
            source=BallotSource.ONLINE,
        )
    close_poll(poll, early_reason=Reason.ADMINISTRATIVE_DECISION)
    publish_poll(Poll.objects.get(pk=poll.pk), User.objects.create_user(username=f"p{poll.pk}"))
    return Poll.objects.get(pk=poll.pk)


def _page(poll: Poll) -> str:
    response = Client().get(f"/fr/scrutin/{poll.pk}/resultats/")
    assert response.status_code == 200
    return response.content.decode()


def _text(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


@pytest.mark.django_db
def test_a_schulze_result_has_its_duels_matrix_and_rankings() -> None:
    poll = _published(
        "schulze", [[["a"], ["b"], ["c"]], [["a"], ["c"], ["b"]], [["b"], ["a"], ["c"]]]
    )
    html = _page(poll)
    text = _text(html)
    assert "Proposition retenue Fontaine" in text
    assert "bat chacune des autres en duel" in text
    assert html.count('class="trend-duel"') == 3
    assert html.count("trend-matrix__cell--win") == 3
    assert html.count('class="trend-types__row"') == 3
    assert "Voix par proposition" not in text
    assert 'style="flex-grow: ' in html  # the bars are sized inline, as on the trend screen
    # The Smith set is explained where it is shown.
    assert "Le plus petit groupe de propositions dont chacune bat en duel" in text


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "first"), [("plurality", "Fontaine 2 voix"), ("approval", "Fontaine 3 voix")]
)
def test_a_counted_result_shows_its_votes_and_no_duels(method: str, first: str) -> None:
    poll = _published(method, [[["a"], ["b"]], [["a"]], [["b"], ["a"]]])
    html = _page(poll)
    text = _text(html)
    assert "Voix par proposition" in text
    assert "Ensemble de Smith" not in text
    assert first in text
    assert 'class="trend-duel"' not in html
    assert "trend-matrix__cell" in html  # the matrix is published for every method


@pytest.mark.django_db
def test_a_tie_broken_by_the_draw_says_so() -> None:
    poll = _published(
        "schulze",
        [[["a"], ["b"], ["c"]], [["b"], ["c"], ["a"]], [["c"], ["a"], ["b"]]],
        tiebreak_rule=TiebreakRule.COMPUTED,
    )
    text = _text(_page(poll))
    winner = closure.publication(poll)["winner"]
    label = {"a": "Fontaine", "b": "Kiosque", "c": "Pelouse"}[winner]
    assert f"Proposition retenue {label}" in text
    assert "après départage d’une égalité" in text
    assert "aucune ne bat toutes les autres" in text


@pytest.mark.django_db
def test_nothing_of_the_trend_itself_is_published() -> None:
    """R-11.5 bis: the trend is never published. The page has the final
    result's cards and none of the curves or the dated history."""
    poll = _published("schulze", [[["a"], ["b"], ["c"]], [["b"], ["a"], ["c"]]])
    html = _page(poll)
    for trend_only in (
        "data-trend-chart",
        "trend-spark",
        "trend-table",
        "Évolution",
        "trend-delta",
    ):
        assert trend_only not in html, trend_only
