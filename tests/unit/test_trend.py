# SPDX-License-Identifier: 0BSD
"""The back-office trend (R-11.5 bis), as pure functions: when a point falls
due and when it may be shown, how a point is stored, and what it shows — ranks,
Condorcet winner, Smith set, duels and their intervals. Where points actually
fall as ballots are written is ``tests/integration/test_trend_points.py``."""

from __future__ import annotations

from datetime import date

import pytest

from apps.core.types import OptionId
from apps.tally.methods import Method, Ranking, pairwise_matrix
from apps.tally.trend import (
    TrendPoint,
    decode,
    due,
    encode,
    orderings,
    shown,
    smith_set,
    standing,
)

A, B, C = OptionId("a"), OptionId("b"), OptionId("c")
OPTIONS = [A, B, C]
DAY = date(2026, 9, 1)

ABC: Ranking = [[A], [B], [C]]
BCA: Ranking = [[B], [C], [A]]
CAB: Ranking = [[C], [A], [B]]


def _point(*groups: tuple[Ranking, int], method: Method = Method.SCHULZE) -> TrendPoint:
    ballots = [ranking for ranking, n in groups for _ in range(n)]
    return standing(DAY, 1, ballots, OPTIONS, method)


def test_a_point_falls_due_at_each_further_multiple_of_ten() -> None:
    assert not due(9, 0)
    assert due(10, 0)
    assert not due(10, 1)  # already taken
    assert not due(19, 1)
    assert due(20, 1)
    # A paper deletion lowered the count after point 2: no second point 2.
    assert not due(19, 2)


def test_a_point_is_shown_once_five_ballots_cast_after_it_are_counted() -> None:
    """Epochs count the points taken before each ballot was first cast: a
    ballot of epoch 1 came after point 1."""
    assert not shown(1, [0] * 10 + [1] * 4)
    assert shown(1, [0] * 10 + [1] * 5)
    assert shown(1, [0] * 10 + [1] * 3 + [2] * 2)
    assert not shown(2, [0] * 10 + [1] * 10 + [2] * 4)


def test_a_stored_table_stands_for_the_same_ballots() -> None:
    ballots: list[Ranking] = [ABC, ABC, [[B, A], [C]], [[C]]]
    table = orderings(ballots, OPTIONS)
    stored = encode(table)
    assert orderings(decode(stored), OPTIONS) == table
    assert encode(orderings(decode(stored), OPTIONS)) == stored
    assert sum(row["count"] for row in stored) == 4  # type: ignore[misc]


def test_points_are_cumulative_and_track_the_schulze_order() -> None:
    first = _point((ABC, 10))
    second = _point((ABC, 10), (BCA, 20))
    assert first.ranks == {A: 1, B: 2, C: 3}
    assert first.condorcet_winner == A
    assert first.smith_set == (A,)
    assert second.ballot_count == 30
    # b > c 30–0; b > a 20–10; c > a 20–10.
    assert second.ranks == {B: 1, C: 2, A: 3}
    assert second.condorcet_winner == B


def test_a_cycle_has_no_condorcet_winner_and_a_full_smith_set() -> None:
    point = _point((ABC, 10), (BCA, 10), (CAB, 10))
    assert point.condorcet_winner is None
    assert point.smith_set == (A, B, C)
    assert point.ranks == {A: 1, B: 1, C: 1}


def test_plurality_ranks_by_first_preferences() -> None:
    point = _point((ABC, 6), (BCA, 4), (CAB, 4), method=Method.PLURALITY)
    assert point.ranks == {A: 1, B: 2, C: 2}


def test_smith_set_excludes_options_beaten_by_the_whole_top_cycle() -> None:
    d = OptionId("d")
    options = [A, B, C, d]
    ballots = [[[A], [B], [C], [d]], [[B], [C], [A], [d]], [[C], [A], [B], [d]]]
    assert smith_set(pairwise_matrix(ballots, options), options) == (A, B, C)


def test_a_point_carries_the_duels_and_each_options_tightest_one() -> None:
    point = _point((ABC, 6), (BCA, 4))
    assert point.pairwise[A][B] == 6
    assert point.pairwise[B][A] == 4
    assert point.margin(A, B) == 2
    # a beats b 6–4 and c 6–4: both margins 2, the first in the poll's order.
    assert point.tightest_duel(A) == (B, 2)
    # c loses to b 0–10 and to a 4–6: its worst is b, by 10.
    assert point.tightest_duel(C) == (B, -10)
    assert point.leaders == (A,)
    assert point.counts is None


def test_plurality_points_carry_the_count_per_option() -> None:
    point = _point((ABC, 6), (BCA, 4), method=Method.PLURALITY)
    assert point.counts == {A: 6, B: 4, C: 0}


def test_orderings_count_ballots_per_ranking_ignoring_order_within_a_tie() -> None:
    point = _point((ABC, 3), ([[B, A], [C]], 1), ([[A, B], [C]], 1), ([[C]], 2))
    assert point.orderings == {((A,), (B,), (C,)): 3, ((A, B), (C,)): 2, ((C,),): 2}


def test_the_margin_interval_is_wilsons_on_the_ballots_that_separate_the_two() -> None:
    """30 against 20 is a share of 0.6 on 50; Wilson's 95 % interval on it is
    [0.4618, 0.7239], so the margin lies in [−3.8, +22.4] ballots. Ballots
    preferring neither play no part."""
    neither: Ranking = [[C]]
    point = _point((ABC, 30), (BCA, 20), (neither, 7))
    lo, hi = point.margin_interval(A, B)
    assert (round(lo, 1), round(hi, 1)) == (-3.8, 22.4)
    assert point.margin_interval(B, A) == pytest.approx((-hi, -lo))


def test_the_margin_interval_narrows_as_ballots_accumulate() -> None:
    def width(n: int) -> float:
        lo, hi = _point((ABC, 3 * n), (BCA, 2 * n)).margin_interval(A, B)
        return (hi - lo) / (5 * n)

    assert width(10) > width(40) > width(160)


def test_no_ballot_separating_two_options_gives_an_empty_interval() -> None:
    point = _point(([[A, B], [C]], 12))
    assert point.margin_interval(A, B) == (0.0, 0.0)
