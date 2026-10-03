# SPDX-License-Identifier: 0BSD
"""Schulze against an implementation neither side wrote (review D-1).

The application and the verifier were both written here, from the same
reading of §8.1; agreeing with each other cannot catch a misreading they share.
``votelib`` (MIT, J. Šimbera; pinned) is a third, independent implementation.
On seeded random polls its pairwise counts must equal the application's ``d``,
and its strongest paths (``Schulze.widest_paths``, winning votes, as §8.1)
the application's ``p``. ``unranked_at_bottom`` is R-10.4's equal-last; a tie
inside a ballot is a frozenset in its terms.

Its ``Schulze.evaluate`` is not compared: it orders candidates by how many
others they beat on path strength and takes the first, so where two options
are both unbeaten it still names one. Schulze's winner set, and §8.1's, is
every unbeaten option, and a tie goes to §8.3. The winners are therefore read
from votelib's paths by that definition. On Schulze's own 45-voter example its
pairwise counts are those printed in the paper (``tests/vectors/schulze.json``).
"""

from __future__ import annotations

import collections
import random
from typing import Any

import votelib.convert
from votelib.evaluate.condorcet import Schulze

from apps.core.types import OptionId
from apps.tally.methods import Method, tally
from tests.integration.test_differential import CASES, SEED, random_case

Pair = tuple[str, str]


def _votelib(case: dict[str, Any]) -> tuple[dict[Pair, int], dict[Pair, int]]:
    """votelib's pairwise counts and strongest paths, zeros left out."""
    votes: collections.Counter[tuple[Any, ...]] = collections.Counter()
    for ballot in case["ballots"]:
        votes[tuple(g[0] if len(g) == 1 else frozenset(g) for g in ballot["ranking"])] += 1
    pairs = votelib.convert.RankedToCondorcetVotes(unranked_at_bottom=True).convert(votes)
    paths = Schulze.widest_paths(pairs)
    return (
        {pair: n for pair, n in pairs.items() if n},
        {pair: n for pair, n in paths.items() if n},
    )


def _unbeaten(paths: dict[Pair, int], options: list[str]) -> list[str]:
    return sorted(
        i
        for i in options
        if all(paths.get((i, j), 0) >= paths.get((j, i), 0) for j in options if j != i)
    )


def test_an_independent_schulze_agrees_on_random_polls() -> None:
    # Seeded for reproducible test cases; nothing here draws a tie-break (§8.3).
    rng = random.Random(SEED)  # noqa: S311
    compared, disagreements = 0, []
    for index in range(CASES):
        case = random_case(rng, index)
        # votelib knows only the options some ballot ranks, not the poll's
        # list: one nobody ranks (equal-last everywhere, R-10.4) is left out on
        # both sides here, and has a hand-worked vector of its own instead.
        ranked = {o for b in case["ballots"] for g in b["ranking"] for o in g}
        options = [o for o in case["options"] if o in ranked]
        if len(options) < 2:
            continue
        ours = tally(
            [b["ranking"] for b in case["ballots"]],
            [OptionId(o) for o in options],
            Method.SCHULZE,
        )
        d = {(i, j): n for i, row in ours.matrix.items() for j, n in row.items() if n}
        p_rows: dict[str, dict[str, int]] = ours.derivation["paths"]  # type: ignore[assignment]
        p = {(i, j): n for i, row in p_rows.items() for j, n in row.items() if n}
        winners = sorted(ours.derivation["winners"])  # type: ignore[call-overload]
        their_d, their_p = _votelib(case)
        compared += 1
        if d != their_d:
            disagreements.append(f"{case['name']}: pairwise counts differ")
        elif p != their_p:
            disagreements.append(f"{case['name']}: path strengths differ")
        elif winners != _unbeaten(their_p, options):
            disagreements.append(f"{case['name']}: winners {winners} differ")
    assert compared > CASES // 2
    assert disagreements == [], "\n".join(disagreements[:10])
