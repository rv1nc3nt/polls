# SPDX-License-Identifier: 0BSD
"""The back-office trend (R-11.5 bis): the result recomputed as ballots arrive.

Pure, like the rest of this package: the caller supplies every ballot version
with its creation instant and day in the poll's timezone, never a clock.

What is computed is bounded by INV-1 rather than by what would be most
informative (docs/specification-decision-log.md #39). The audience — the poll
administrator — sees which electors have voted (R-7.5) and can reload that
list, and this screen, at will. Whatever two views of this screen differ by is
therefore attributable to the electors who voted in between. So:

* **a point every ``STEP`` arrivals** — a ballot cast, modified, or a paper
  entry changing state — never on the clock. Two consecutive points differ by
  ``STEP`` arrivals, however often the screen is reloaded;
* **a point never changes once shown.** Each counts every ballot as it stood
  when the point's last arrival came in: the version then in force, not the
  current one. Recomputing past points from the current live set would let a
  modification remove one ballot's old ranking from them, readable as the
  difference (decision log #39);
* **the newest point waits.** A point is shown only once ``LAG`` further
  arrivals follow it. The result published at closure is the whole live set,
  so it minus the last point shown before closure is what came after: never
  fewer than ``LAG`` ballots. After closure the final standing is shown too —
  it is the published result. ``LAG`` is shorter than ``STEP`` at the
  requirements owner's request, trading that floor for a fresher newest point
  (decision log #39).

Each point carries the ranks, the Condorcet winner, the Smith set, the
head-to-head counts (or, under plurality and approval, the count per option)
and the number of ballots per distinct ranking. The residual exposure is a
group of ``STEP`` arrivals — or the closing ``LAG`` — that all agree on a
duel, or all cast the same ranking: the difference then states each one's
choice. R-11.5 bis accepts that
in exchange for the figures.

Paper ballots are the one exception to "never changes": a countersignature or
a deletion changes a row's status in place, with no instant recorded, so it is
read as of the row's creation. The link from a paper ballot to its elector is
deliberate and already on the poll admin's screens (R-8.2 bis), so this
reveals nothing they could not read there.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from apps.core.types import OptionId

from .methods import Method, Ranking, option_counts, pairwise_matrix, schulze_paths

#: A ballot's ranking as a hashable key: its groups, each in the poll's option
#: order so that ``[[b, a]]`` and ``[[a, b]]`` are the same tie.
Ordering = tuple[tuple[OptionId, ...], ...]

#: Arrivals between two points.
STEP = 10

#: Arrivals that must follow a point before it is shown.
LAG = 5


@dataclass(frozen=True)
class Version:
    """One ballot version, as the trend reads it.

    ``ballot`` is shared by every version of one ballot (its tracking code,
    stable across versions, R-7.2). ``ranking`` is ``None`` for a version that
    does not count — a paper entry awaiting countersignature, or deleted — so
    from ``at`` on the ballot counts for nothing.
    """

    at: datetime
    day: date
    ballot: str
    ranking: Ranking | None


@dataclass(frozen=True)
class TrendPoint:
    """The standing after the ``arrivals``-th arrival, which came in on
    ``through``.

    ``ranks[o]`` is 1 for the leading option; options the method cannot
    separate share a rank. ``smith_set`` is in the poll's option order.
    ``pairwise[i][j]`` counts the ballots ranking ``i`` above ``j`` (§8.1);
    ``counts`` is the plurality or approval count, ``None`` under Schulze.
    ``orderings`` counts the ballots by the ranking they carry (R-11.3).
    """

    through: date
    arrivals: int
    ballot_count: int
    ranks: dict[OptionId, int]
    condorcet_winner: OptionId | None
    smith_set: tuple[OptionId, ...]
    pairwise: dict[OptionId, dict[OptionId, int]]
    counts: dict[OptionId, int] | None
    orderings: dict[Ordering, int]

    @property
    def leaders(self) -> tuple[OptionId, ...]:
        return tuple(o for o, rank in self.ranks.items() if rank == 1)

    def margin(self, i: OptionId, j: OptionId) -> int:
        """Ballots preferring ``i`` to ``j`` minus those preferring ``j``."""
        return self.pairwise[i][j] - self.pairwise[j][i]

    def tightest_duel(self, i: OptionId) -> tuple[OptionId, int] | None:
        """The opponent ``i`` fares worst against, and the margin there.

        Positive for the Condorcet winner alone: how far it is from losing a
        duel. Negative for every other option: how far it is from no longer
        losing any. Ties go to the first opponent in the poll's order.
        """
        if not self.pairwise[i]:
            return None
        worst = min(self.pairwise[i], key=lambda j: self.margin(i, j))
        return worst, self.margin(i, worst)


def trend(
    versions: Sequence[Version],
    options: Sequence[OptionId],
    method: Method,
    *,
    final: bool,
    step: int = STEP,
    lag: int = LAG,
) -> list[TrendPoint]:
    """The points to show: one per ``step`` arrivals with ``lag`` more after
    it and, once ``final``, the final standing."""
    ordered = sorted(versions, key=lambda v: (v.at, v.ballot))
    total = len(ordered)
    in_force: dict[str, Ranking] = {}
    points: list[TrendPoint] = []
    for n, version in enumerate(ordered, start=1):
        if version.ranking is None:
            in_force.pop(version.ballot, None)
        else:
            in_force[version.ballot] = version.ranking
        if n % step == 0 and total - n >= lag:
            points.append(_point(version.day, n, list(in_force.values()), options, method))
    if final and ordered and (not points or points[-1].arrivals != total):
        points.append(_point(ordered[-1].day, total, list(in_force.values()), options, method))
    return points


def _point(
    through: date,
    arrivals: int,
    ballots: Sequence[Ranking],
    options: Sequence[OptionId],
    method: Method,
) -> TrendPoint:
    d = pairwise_matrix(ballots, options)
    counts: dict[OptionId, int] | None = None
    if method is Method.SCHULZE:
        # §8.1: the strongest-path relation is transitive, so counting who
        # strictly beats an option ranks it consistently with the winner.
        p = schulze_paths(d, options)
        beats = {i: {j for j in options if j != i and p[i][j] > p[j][i]} for i in options}
    else:
        counts = option_counts(ballots, options, method)
        beats = {i: {j for j in options if counts[i] > counts[j]} for i in options}
    ranks = {i: 1 + sum(1 for j in options if i in beats[j]) for i in options}
    condorcet = [i for i in options if all(d[i][j] > d[j][i] for j in options if j != i)]
    return TrendPoint(
        through=through,
        arrivals=arrivals,
        ballot_count=len(ballots),
        ranks=ranks,
        condorcet_winner=condorcet[0] if condorcet else None,
        smith_set=smith_set(d, options),
        pairwise=d,
        counts=counts,
        orderings=orderings(ballots, options),
    )


def orderings(ballots: Sequence[Ranking], options: Sequence[OptionId]) -> dict[Ordering, int]:
    """Ballots per distinct ranking — R-11.3's summary table, before closure.

    Options a ballot leaves out are not part of its key: two ballots ranking
    only ``a`` are the same ordering however many options the poll has, and
    R-10.4 places the rest equal-last for the count either way.
    """
    position = {o: k for k, o in enumerate(options)}
    out: Counter[Ordering] = Counter()
    for ranking in ballots:
        key = tuple(
            tuple(sorted((o for o in group if o in position), key=position.__getitem__))
            for group in ranking
        )
        out[tuple(g for g in key if g)] += 1
    return dict(out)


def smith_set(
    d: Mapping[OptionId, Mapping[OptionId, int]], options: Sequence[OptionId]
) -> tuple[OptionId, ...]:
    """The smallest set whose members each beat every non-member pairwise.

    Equivalently, the options from which every other option is reachable
    through "is not beaten by" (``d[i][j] >= d[j][i]``): an option outside the
    set cannot reach the set, since every member beats it.
    """
    reach = {i: {j for j in options if j != i and d[i][j] >= d[j][i]} for i in options}
    for k in options:
        for i in options:
            if k in reach[i]:
                reach[i] |= reach[k]
    return tuple(i for i in options if reach[i] >= set(options) - {i})
