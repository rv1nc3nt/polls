# SPDX-License-Identifier: 0BSD
"""The back-office trend (R-11.5 bis), as a pure function: binning, ranks,
Condorcet winner and Smith set."""

from __future__ import annotations

from datetime import date, timedelta

from apps.core.types import OptionId
from apps.tally.methods import Method, Ranking, pairwise_matrix
from apps.tally.trend import smith_set, trend

A, B, C = OptionId("a"), OptionId("b"), OptionId("c")
OPTIONS = [A, B, C]
DAY = date(2026, 9, 1)

ABC: Ranking = [[A], [B], [C]]
BCA: Ranking = [[B], [C], [A]]
CAB: Ranking = [[C], [A], [B]]


def _on(day: int, ranking: Ranking, n: int) -> list[tuple[date, Ranking]]:
    return [(DAY + timedelta(days=day), ranking)] * n


def test_days_merge_until_a_bin_holds_the_minimum() -> None:
    ballots = _on(0, ABC, 4) + _on(1, ABC, 4) + _on(2, ABC, 4) + _on(3, BCA, 3)
    points = trend(ballots, OPTIONS, Method.SCHULZE, last_day=date.max, final=False, min_bin=10)
    # 4 + 4 + 4 closes one bin on day 2; the 3 of day 3 wait for more.
    assert [(p.through, p.ballot_count) for p in points] == [(DAY + timedelta(days=2), 12)]


def test_once_final_the_remainder_folds_into_the_last_bin() -> None:
    ballots = _on(0, ABC, 10) + _on(1, ABC, 10) + _on(2, BCA, 3)
    points = trend(ballots, OPTIONS, Method.SCHULZE, last_day=date.max, final=True, min_bin=10)
    assert [(p.through, p.ballot_count) for p in points] == [
        (DAY, 10),
        (DAY + timedelta(days=2), 23),
    ]


def test_too_few_ballots_show_nothing_even_once_final() -> None:
    points = trend(_on(0, ABC, 9), OPTIONS, Method.SCHULZE, last_day=date.max, final=True)
    assert points == []


def test_days_after_last_day_are_ignored() -> None:
    """The day in progress is left out while the poll is open."""
    ballots = _on(0, ABC, 10) + _on(1, BCA, 30)
    points = trend(ballots, OPTIONS, Method.SCHULZE, last_day=DAY, final=False)
    assert [(p.through, p.ballot_count) for p in points] == [(DAY, 10)]


def test_points_are_cumulative_and_track_the_schulze_order() -> None:
    ballots = _on(0, ABC, 10) + _on(1, BCA, 20)
    first, second = trend(ballots, OPTIONS, Method.SCHULZE, last_day=date.max, final=True)
    assert first.ranks == {A: 1, B: 2, C: 3}
    assert first.condorcet_winner == A
    assert first.smith_set == (A,)
    assert second.ballot_count == 30
    # b > c 30–0; b > a 20–10; c > a 20–10.
    assert second.ranks == {B: 1, C: 2, A: 3}
    assert second.condorcet_winner == B


def test_a_cycle_has_no_condorcet_winner_and_a_full_smith_set() -> None:
    ballots = _on(0, ABC, 10) + _on(0, BCA, 10) + _on(0, CAB, 10)
    (point,) = trend(ballots, OPTIONS, Method.SCHULZE, last_day=date.max, final=True)
    assert point.condorcet_winner is None
    assert point.smith_set == (A, B, C)
    assert point.ranks == {A: 1, B: 1, C: 1}


def test_plurality_ranks_by_first_preferences() -> None:
    ballots = _on(0, ABC, 6) + _on(0, BCA, 4) + _on(0, CAB, 4)
    (point,) = trend(ballots, OPTIONS, Method.PLURALITY, last_day=date.max, final=True)
    assert point.ranks == {A: 1, B: 2, C: 2}


def test_smith_set_excludes_options_beaten_by_the_whole_top_cycle() -> None:
    d = OptionId("d")
    options = [A, B, C, d]
    ballots = [[[A], [B], [C], [d]], [[B], [C], [A], [d]], [[C], [A], [B], [d]]]
    assert smith_set(pairwise_matrix(ballots, options), options) == (A, B, C)


def test_a_point_carries_the_duels_and_each_options_tightest_one() -> None:
    ballots = _on(0, ABC, 6) + _on(0, BCA, 4)
    (point,) = trend(ballots, OPTIONS, Method.SCHULZE, last_day=date.max, final=True)
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
    ballots = _on(0, ABC, 6) + _on(0, BCA, 4)
    (point,) = trend(ballots, OPTIONS, Method.PLURALITY, last_day=date.max, final=True)
    assert point.counts == {A: 6, B: 4, C: 0}


def test_orderings_count_ballots_per_ranking_ignoring_order_within_a_tie() -> None:
    ballots = (
        _on(0, ABC, 3) + _on(0, [[B, A], [C]], 1) + _on(0, [[A, B], [C]], 1) + _on(0, [[C]], 2)
    )
    (point,) = trend(ballots, OPTIONS, Method.SCHULZE, last_day=date.max, final=True, min_bin=1)
    assert point.orderings == {((A,), (B,), (C,)): 3, ((A, B), (C,)): 2, ((C,),): 2}
