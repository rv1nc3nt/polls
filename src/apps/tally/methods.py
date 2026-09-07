# SPDX-License-Identifier: 0BSD
"""The tally (§8). A pure function of its arguments.

No I/O, no clock, no randomness beyond the seeded tie-break, no database — in
particular it never reads ``Registration`` (INV-9), which is why this package
imports no model at all. Version-pinned (R-10.2): ``METHOD_VERSION`` is written
onto the poll at creation and published with the result, so a later change to
this file cannot silently restate an old result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from apps.core.types import OptionId

METHOD_VERSION = "1"

Ranking = Sequence[Sequence[OptionId]]


class Method(StrEnum):
    SCHULZE = "schulze"
    PLURALITY = "plurality"
    APPROVAL = "approval"


@dataclass(frozen=True)
class TallyResult:
    """What the back-office publishes (§9).

    ``winner`` is ``None`` in exactly two cases, which the caller must
    distinguish: no ballots at all (T-39), and a tie the poll's ``physical``
    tie-break rule sends to a human (§8.3). ``tied`` says which.
    """

    method: Method
    method_version: str
    ballot_count: int
    winner: OptionId | None
    tied: tuple[OptionId, ...]
    matrix: dict[OptionId, dict[OptionId, int]]
    derivation: dict[str, object] = field(default_factory=dict)


def pairwise_matrix(
    ballots: Sequence[Ranking], options: Sequence[OptionId]
) -> dict[OptionId, dict[OptionId, int]]:
    """``d[i][j]``: live ballots ranking ``i`` strictly above ``j`` (§8.1).

    Options a ballot does not rank are equal-last (R-10.4): they beat nothing
    and are beaten by everything the ballot did rank. Options tied within a
    group beat each other not at all, in either direction.
    """
    d: dict[OptionId, dict[OptionId, int]] = {i: {j: 0 for j in options if j != i} for i in options}
    option_set = set(options)
    for ranking in ballots:
        rank_of: dict[OptionId, int] = {}
        for position, group in enumerate(ranking):
            for option in group:
                if option in option_set:
                    rank_of[option] = position
        unranked = option_set - rank_of.keys()
        last = len(ranking)
        for option in unranked:
            rank_of[option] = last
        for i in options:
            for j in options:
                if i != j and rank_of[i] < rank_of[j]:
                    d[i][j] += 1
    return d


def schulze_paths(
    d: Mapping[OptionId, Mapping[OptionId, int]], options: Sequence[OptionId]
) -> dict[OptionId, dict[OptionId, int]]:
    """Strongest path strengths, exactly the loop of §8.1."""
    p: dict[OptionId, dict[OptionId, int]] = {
        i: {j: (d[i][j] if d[i][j] > d[j][i] else 0) for j in options if j != i} for i in options
    }
    for i in options:
        for j in options:
            if j == i:
                continue
            for k in options:
                if k in (i, j):
                    continue
                p[j][k] = max(p[j][k], min(p[j][i], p[i][k]))
    return p


def _schulze_winners(
    p: Mapping[OptionId, Mapping[OptionId, int]], options: Sequence[OptionId]
) -> list[OptionId]:
    return [i for i in options if all(p[i][j] >= p[j][i] for j in options if j != i)]


def tally(
    ballots: Sequence[Ranking],
    options: Sequence[OptionId],
    method: Method,
) -> TallyResult:
    """``tally(ballots, method, params) → {winner, matrix, derivation}`` (R-10.1).

    ``ballots`` is the live set only (§3.4): superseded, deleted and
    ``pending_countersign`` rows are excluded by the caller, which is also what
    the closure hash covers, so the published CSV re-tallies to this result.
    """
    match method:
        case Method.SCHULZE:
            return _tally_schulze(ballots, options)
        case Method.PLURALITY:
            return _tally_counted(ballots, options, method)
        case Method.APPROVAL:
            return _tally_counted(ballots, options, method)


def _tally_schulze(ballots: Sequence[Ranking], options: Sequence[OptionId]) -> TallyResult:
    d = pairwise_matrix(ballots, options)
    p = schulze_paths(d, options) if ballots else {i: {} for i in options}
    winners = _schulze_winners(p, options) if ballots else []
    return TallyResult(
        method=Method.SCHULZE,
        method_version=METHOD_VERSION,
        ballot_count=len(ballots),
        winner=winners[0] if len(winners) == 1 else None,
        tied=tuple(winners) if len(winners) > 1 else (),
        matrix=d,
        derivation={
            "pairwise": {i: dict(row) for i, row in d.items()},
            "paths": {i: dict(row) for i, row in p.items()},
            "winners": list(winners),
        },
    )


def _tally_counted(
    ballots: Sequence[Ranking], options: Sequence[OptionId], method: Method
) -> TallyResult:
    """Plurality (first preferences) and approval (every option ranked), R-10.3.

    Under ``plurality`` a ballot whose first group holds several options — only
    possible where the poll allows ties — contributes to each of them; the
    configuration that permits it is a misconfiguration the back-office warns
    about, not something to resolve silently here.
    """
    counts: dict[OptionId, int] = dict.fromkeys(options, 0)
    for ranking in ballots:
        if not ranking:
            continue
        chosen = ranking[0] if method is Method.PLURALITY else [o for g in ranking for o in g]
        for option in chosen:
            if option in counts:
                counts[option] += 1
    best = max(counts.values()) if ballots else 0
    winners = [o for o in options if counts[o] == best] if ballots else []
    return TallyResult(
        method=method,
        method_version=METHOD_VERSION,
        ballot_count=len(ballots),
        winner=winners[0] if len(winners) == 1 else None,
        tied=tuple(winners) if len(winners) > 1 else (),
        matrix=pairwise_matrix(ballots, options),
        derivation={"counts": dict(counts), "winners": list(winners)},
    )
