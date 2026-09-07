# SPDX-License-Identifier: 0BSD
"""§12.1 — pure functions, no database, no HTTP, no network."""

from __future__ import annotations

from apps.core.types import OptionId
from apps.tally.methods import Method, pairwise_matrix, tally
from apps.tally.tiebreak import break_tie, tiebreak_order

A, B, C = OptionId("a"), OptionId("b"), OptionId("c")
OPTIONS = [A, B, C]


def strict(*order: OptionId) -> list[list[OptionId]]:
    return [[o] for o in order]


def test_t9_cyclic_majority_ties_and_the_tiebreak_resolves_it() -> None:
    """T-9: A>B>C, B>C>A, C>A>B in equal numbers."""
    ballots = [strict(A, B, C), strict(B, C, A), strict(C, A, B)]
    result = tally(ballots, OPTIONS, Method.SCHULZE)

    assert result.winner is None
    assert set(result.tied) == {A, B, C}

    first = break_tie(result.tied, b"\x01" * 32, b"\x02" * 32)
    again = break_tie(result.tied, b"\x01" * 32, b"\x02" * 32)
    assert first == again


def test_t39_empty_ballot_set_reports_absence_rather_than_failing() -> None:
    result = tally([], OPTIONS, Method.SCHULZE)
    assert result.ballot_count == 0
    assert result.winner is None
    assert result.tied == ()


def test_t33_plurality_and_approval() -> None:
    ballots = [strict(A, B, C), strict(A, C, B), strict(B, A, C)]
    plurality = tally(ballots, OPTIONS, Method.PLURALITY)
    assert plurality.winner == A
    assert plurality.derivation["counts"] == {A: 2, B: 1, C: 0}

    approvals = [[[A, B]], [[A]], [[B]]]
    approval = tally(approvals, OPTIONS, Method.APPROVAL)
    assert approval.derivation["counts"] == {A: 2, B: 2, C: 0}
    assert set(approval.tied) == {A, B}


def test_unranked_options_rank_equal_last() -> None:
    """R-10.4: a ballot ranking only A beats B and C, which beat nothing."""
    d = pairwise_matrix([[[A]]], OPTIONS)
    assert d[A][B] == 1 and d[A][C] == 1
    assert d[B][A] == 0 and d[B][C] == 0


def test_clear_schulze_winner() -> None:
    ballots = [strict(A, B, C)] * 3 + [strict(B, A, C)] * 2
    assert tally(ballots, OPTIONS, Method.SCHULZE).winner == A


def test_t44_tiebreak_order_matches_a_stored_vector() -> None:
    """T-44: the test that catches a platform- or version-dependent draw.

    Recomputed by hand from §8.3: seed = SHA256(opening_seed || closure_hash),
    then options ordered by ascending SHA256(seed || option_id).
    """
    opening_seed = bytes(range(32))
    closure_hash = bytes(range(32, 64))
    order = [option for option, _ in tiebreak_order([A, B, C], opening_seed, closure_hash)]
    assert order == ["c", "a", "b"]
