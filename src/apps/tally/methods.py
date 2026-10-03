# SPDX-License-Identifier: 0BSD
"""The tally (§8). A pure function of its arguments.

No I/O, no clock, no randomness beyond the seeded tie-break, no database — in
particular it never reads ``Registration`` (INV-9), which is why this package
imports no model at all.

Version-pinned (R-10.2). A poll records the version it is tallied under, and
``tally`` runs that version or refuses. A change to how any method counts is a
new version: it is added beside the old one, never edited in place. Two lists
keep the old ones alive (decision log #52): ``IMPLEMENTED_VERSIONS``, every
version a poll may have recorded, which ``tally`` runs for as long as this code
exists; and ``SELECTABLE_VERSIONS``, the ones a poll may still be configured
with. Retiring a version takes it out of the second list only: no new poll uses
it, and every poll that recorded it is still tallied and published under it.
``METHOD_VERSION`` is the version new polls get.
The published artefacts are also stored at publication
(``elections.closure.freeze_publication``), so a published result does not
even depend on this rule being kept.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum

from apps.core.types import OptionId

#: The version a new poll is configured with.
METHOD_VERSION = "1"

#: Every version ``tally`` can run. A version is never removed from here: a
#: poll that recorded it must stay reproducible (R-10.2). Version 1 is the whole
#: of this module.
IMPLEMENTED_VERSIONS: tuple[str, ...] = ("1",)

#: The versions a poll may still be configured and announced with: implemented
#: ones that are not retired.
SELECTABLE_VERSIONS: tuple[str, ...] = ("1",)


class UnsupportedMethodVersion(ValueError):
    """A poll recorded a method version this code does not implement (R-10.2).

    Tallying it under whatever the current code does would be exactly the
    silent restatement the version exists to prevent.
    """


def version_to_run(recorded: str, legacy_tallied_as: str | None) -> str:
    """The version a poll is tallied under: the one it recorded, if this code
    implements it; else, for a poll frozen before versions were checked, the
    version every such poll was in fact tallied under (``legacy_tallied_as``,
    set by migration only, decision log #52).

    Raises ``UnsupportedMethodVersion`` otherwise: a poll recording a version
    this code does not know, as an older release would meet one recorded by a
    newer, is never tallied under another version's rules.
    """
    if recorded in IMPLEMENTED_VERSIONS:
        return recorded
    if legacy_tallied_as in IMPLEMENTED_VERSIONS:
        return legacy_tallied_as
    raise UnsupportedMethodVersion(recorded)


Ranking = Sequence[Sequence[OptionId]]


class Method(StrEnum):
    """The counting methods of R-10.3; values match ``Poll.tally_method``."""

    SCHULZE = "schulze"
    PLURALITY = "plurality"
    APPROVAL = "approval"


@dataclass(frozen=True)
class TallyResult:
    """What the back-office publishes (§9).

    ``winner`` is ``None`` in exactly two cases, which the caller must
    distinguish: no ballots at all (T-39), and a tie (§8.3). ``tied`` says
    which. The tally does not know the poll's tie-break rule and never breaks
    a tie itself: the caller either draws with ``tiebreak.tiebreak_order``
    (``computed``) or waits for a human entry (``physical``,
    ``elections.closure``).
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
    version: str = METHOD_VERSION,
) -> TallyResult:
    """``tally(ballots, method, params) → {winner, matrix, derivation}`` (R-10.1).

    ``ballots`` is the live set only (§3.4): superseded, deleted and
    ``pending_countersign`` rows are excluded by the caller, which is also what
    the closure hash covers, so the published CSV re-tallies to this result.

    ``version`` is the poll's recorded method version (R-10.2); one this code
    does not implement raises ``UnsupportedMethodVersion``. There is only
    version 1 today, so it runs the functions below; a version 2 would
    dispatch here.
    """
    if version not in IMPLEMENTED_VERSIONS:
        raise UnsupportedMethodVersion(version)
    match method:
        case Method.SCHULZE:
            result = _tally_schulze(ballots, options)
        case Method.PLURALITY | Method.APPROVAL:
            result = _tally_counted(ballots, options, method)
    # The version that actually ran, which the publication states.
    return replace(result, method_version=version)


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


def option_counts(
    ballots: Sequence[Ranking], options: Sequence[OptionId], method: Method
) -> dict[OptionId, int]:
    """The per-option count plurality and approval are decided on (§8.2)."""
    counts: dict[OptionId, int] = dict.fromkeys(options, 0)
    for ranking in ballots:
        if not ranking:
            continue
        chosen = ranking[0] if method is Method.PLURALITY else [o for g in ranking for o in g]
        for option in chosen:
            if option in counts:
                counts[option] += 1
    return counts


def _tally_counted(
    ballots: Sequence[Ranking], options: Sequence[OptionId], method: Method
) -> TallyResult:
    """Plurality (first preferences) and approval (every option ranked), R-10.3.

    Under ``plurality`` a ballot whose first group holds several options — only
    possible where the poll allows ties — contributes to each of them; the
    configuration that permits it is a misconfiguration the back-office warns
    about, not something to resolve silently here.
    """
    counts = option_counts(ballots, options, method)
    # ``default``: no options at all is unreachable from a real poll (it
    # needs two to be announced), but a pure function must not crash on it.
    best = max(counts.values(), default=0)
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
