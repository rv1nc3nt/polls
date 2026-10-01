# SPDX-License-Identifier: 0BSD
"""The back-office trend (R-11.5 bis), as a pure function: where points fall,
which version of each ballot they count, ranks, Condorcet winner and Smith set."""

from __future__ import annotations

import itertools
from datetime import UTC, date, datetime, timedelta

import pytest

from apps.core.types import OptionId
from apps.tally.methods import Method, Ranking, pairwise_matrix
from apps.tally.trend import Version, smith_set, trend

A, B, C = OptionId("a"), OptionId("b"), OptionId("c")
OPTIONS = [A, B, C]
DAY = date(2026, 9, 1)

ABC: Ranking = [[A], [B], [C]]
BCA: Ranking = [[B], [C], [A]]
CAB: Ranking = [[C], [A], [B]]


_clock = itertools.count()


def _on(day: int, ranking: Ranking | None, n: int, *, ballot: str = "") -> list[Version]:
    """``n`` arrivals on ``day``, each later than every arrival made before
    it; ``ballot`` reuses one tracking code (a modification) where given."""
    out = []
    for _ in range(n):
        tick = next(_clock)
        at = datetime(2026, 9, 1, tzinfo=UTC) + timedelta(days=day, seconds=tick)
        out.append(Version(at, DAY + timedelta(days=day), ballot or f"T{tick}", ranking))
    return out


def test_a_point_every_step_ballots_shown_once_lag_more_follow() -> None:
    """While the poll is open, the newest point waits for ``lag`` more
    ballots after it, so nothing after the last point shown is ever fewer
    than ``lag`` ballots: 10 appears at the 15th ballot, 20 at the 25th, 30 at
    the 35th."""
    for cast, shown in ((15, [10]), (24, [10]), (25, [10, 20]), (34, [10, 20]), (35, [10, 20, 30])):
        points = trend(_on(0, ABC, cast), OPTIONS, Method.SCHULZE, final=False)
        assert [p.ballot_count for p in points] == shown, cast


def test_a_modification_does_not_move_a_point_off_its_multiple() -> None:
    """Points count 10, 20, 30… ballots: a modification is an arrival but adds
    no ballot, so point 20 waits for the 20th ballot, here the 21st arrival."""
    ballots = _on(0, ABC, 1, ballot="X") + _on(0, ABC, 14) + _on(0, BCA, 1, ballot="X")
    ballots += _on(0, ABC, 9)
    points = trend(ballots, OPTIONS, Method.SCHULZE, final=False)
    assert [(p.ballot_count, p.arrivals) for p in points] == [(10, 10)]
    points = trend(ballots + _on(0, ABC, 5), OPTIONS, Method.SCHULZE, final=False)
    assert [(p.ballot_count, p.arrivals) for p in points] == [(10, 10), (20, 21)]


def test_one_elector_modifying_again_and_again_neither_cuts_nor_shows_a_point() -> None:
    """R-7.1 allows any number of modifications. Were arrivals the measure,
    ten by one elector would be the whole difference between two points, and
    five the whole tail before the published result."""
    again = [v for r in (BCA, CAB) * 5 for v in _on(0, r, 1, ballot="X")]
    ballots = _on(0, ABC, 1, ballot="X") + _on(0, ABC, 14) + again
    points = trend(ballots, OPTIONS, Method.SCHULZE, final=False)
    assert [p.ballot_count for p in points] == [10]
    ballots = _on(0, ABC, 1, ballot="X") + _on(0, ABC, 19) + again
    points = trend(ballots, OPTIONS, Method.SCHULZE, final=False)
    assert [p.ballot_count for p in points] == [10]


def test_points_fall_within_a_day_and_need_no_day_boundary() -> None:
    ballots = _on(0, ABC, 15) + _on(1, BCA, 25)
    points = trend(ballots, OPTIONS, Method.SCHULZE, final=False)
    assert [(p.arrivals, p.through) for p in points] == [
        (10, DAY),
        (20, DAY + timedelta(days=1)),
        (30, DAY + timedelta(days=1)),
    ]


def test_once_final_the_last_point_is_the_whole_live_set() -> None:
    ballots = _on(0, ABC, 23)
    points = trend(ballots, OPTIONS, Method.SCHULZE, final=True)
    # 20 has only 3 arrivals after it, fewer than the lag: never shown, since
    # the published result minus it would be those 3 ballots.
    assert [(p.arrivals, p.ballot_count) for p in points] == [(10, 10), (23, 23)]


def test_too_few_ballots_show_nothing_while_open() -> None:
    assert trend(_on(0, ABC, 14), OPTIONS, Method.SCHULZE, final=False) == []


def test_a_shown_point_does_not_change_when_a_ballot_in_it_is_modified() -> None:
    """Recomputing from the current live set would drop the old version from
    every past point, and the difference would be that one ballot."""
    first = _on(0, ABC, 1, ballot="X") + _on(0, ABC, 19)
    before = trend(first, OPTIONS, Method.SCHULZE, final=False)
    after = trend(first + _on(1, BCA, 1, ballot="X"), OPTIONS, Method.SCHULZE, final=False)
    assert before[0] == after[0]
    assert before[0].pairwise[A][B] == 10


def test_a_modification_replaces_the_ballot_from_its_arrival_on() -> None:
    ballots = _on(0, ABC, 1, ballot="X") + _on(0, ABC, 9) + _on(1, BCA, 1, ballot="X")
    (final,) = trend(ballots, OPTIONS, Method.SCHULZE, final=True)[-1:]
    assert final.ballot_count == 10
    assert final.arrivals == 11
    assert final.pairwise[A][B] == 9


def test_a_version_that_does_not_count_withdraws_the_ballot() -> None:
    """A paper correction awaiting countersignature, or a deleted entry."""
    ballots = _on(0, ABC, 1, ballot="P") + _on(0, ABC, 9) + _on(0, None, 1, ballot="P")
    (final,) = trend(ballots, OPTIONS, Method.SCHULZE, final=True)[-1:]
    assert final.ballot_count == 9


def test_points_are_cumulative_and_track_the_schulze_order() -> None:
    ballots = _on(0, ABC, 10) + _on(1, BCA, 20)
    points = trend(ballots, OPTIONS, Method.SCHULZE, final=True)
    first, second = points[0], points[-1]
    assert first.ranks == {A: 1, B: 2, C: 3}
    assert first.condorcet_winner == A
    assert first.smith_set == (A,)
    assert second.ballot_count == 30
    # b > c 30–0; b > a 20–10; c > a 20–10.
    assert second.ranks == {B: 1, C: 2, A: 3}
    assert second.condorcet_winner == B


def test_a_cycle_has_no_condorcet_winner_and_a_full_smith_set() -> None:
    ballots = _on(0, ABC, 10) + _on(0, BCA, 10) + _on(0, CAB, 10)
    point = trend(ballots, OPTIONS, Method.SCHULZE, final=True)[-1]
    assert point.condorcet_winner is None
    assert point.smith_set == (A, B, C)
    assert point.ranks == {A: 1, B: 1, C: 1}


def test_plurality_ranks_by_first_preferences() -> None:
    ballots = _on(0, ABC, 6) + _on(0, BCA, 4) + _on(0, CAB, 4)
    point = trend(ballots, OPTIONS, Method.PLURALITY, final=True)[-1]
    assert point.ranks == {A: 1, B: 2, C: 2}


def test_smith_set_excludes_options_beaten_by_the_whole_top_cycle() -> None:
    d = OptionId("d")
    options = [A, B, C, d]
    ballots = [[[A], [B], [C], [d]], [[B], [C], [A], [d]], [[C], [A], [B], [d]]]
    assert smith_set(pairwise_matrix(ballots, options), options) == (A, B, C)


def test_a_point_carries_the_duels_and_each_options_tightest_one() -> None:
    ballots = _on(0, ABC, 6) + _on(0, BCA, 4)
    point = trend(ballots, OPTIONS, Method.SCHULZE, final=True)[-1]
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
    point = trend(ballots, OPTIONS, Method.PLURALITY, final=True)[-1]
    assert point.counts == {A: 6, B: 4, C: 0}


def test_orderings_count_ballots_per_ranking_ignoring_order_within_a_tie() -> None:
    ballots = (
        _on(0, ABC, 3) + _on(0, [[B, A], [C]], 1) + _on(0, [[A, B], [C]], 1) + _on(0, [[C]], 2)
    )
    point = trend(ballots, OPTIONS, Method.SCHULZE, final=True, step=1)[-1]
    assert point.orderings == {((A,), (B,), (C,)): 3, ((A, B), (C,)): 2, ((C,),): 2}


def test_the_margin_interval_is_wilsons_on_the_ballots_that_separate_the_two() -> None:
    """30 against 20 is a share of 0.6 on 50; Wilson's 95 % interval on it is
    [0.4618, 0.7239], so the margin lies in [−3.8, +22.4] ballots. Ballots
    preferring neither play no part."""
    neither: Ranking = [[C]]
    ballots = _on(0, ABC, 30) + _on(0, BCA, 20) + _on(0, neither, 7)
    point = trend(ballots, OPTIONS, Method.SCHULZE, final=True)[-1]
    lo, hi = point.margin_interval(A, B)
    assert (round(lo, 1), round(hi, 1)) == (-3.8, 22.4)
    assert point.margin_interval(B, A) == pytest.approx((-hi, -lo))


def test_the_margin_interval_narrows_as_ballots_accumulate() -> None:
    def width(n: int) -> float:
        point = trend(_on(0, ABC, 3 * n) + _on(0, BCA, 2 * n), OPTIONS, Method.SCHULZE, final=True)
        lo, hi = point[-1].margin_interval(A, B)
        return (hi - lo) / (5 * n)

    assert width(10) > width(40) > width(160)


def test_no_ballot_separating_two_options_gives_an_empty_interval() -> None:
    point = trend(_on(0, [[A, B], [C]], 12), OPTIONS, Method.SCHULZE, final=True)[-1]
    assert point.margin_interval(A, B) == (0.0, 0.0)
