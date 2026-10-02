# SPDX-License-Identifier: 0BSD
"""The back-office trend (R-11.5 bis): the result recomputed as ballots arrive.

Pure, like the rest of this package. The points themselves are recorded by
``apps.ballots.trendpoints`` at the moment each falls due, as the number of
ballots per distinct ranking and a date; everything a point shows is derived
here from that. Ballots carry no time and no order to rebuild a point from
afterwards: either would line a ballot up with the registration confirmed
just before it (INV-1, decision log #42).

What is computed is bounded by INV-1 rather than by what would be most
informative (docs/specification-decision-log.md #39). The audience — the poll
administrator — sees which electors have voted (R-7.5) and can reload that
list, and this screen, at will. Whatever two views of this screen differ by is
therefore attributable to the electors who voted in between. So:

* **a point every ``STEP`` ballots counted**, never on the clock: the
  points count 10, 20, 30… ballots. A modification adds no ballot, so it does
  not move a point; the ``STEP`` new ballots between two points are ``STEP``
  distinct electors, however often each modifies (R-7.1). Cutting on arrivals
  instead would let one elector modifying ``STEP`` times make the whole
  difference between two points (decision log #39);
* **a point never changes once shown.** Each counts every ballot as it stood
  at the moment the point fell due — the version then in force — and is stored
  then. Recomputing past points from the current live set would let a
  modification remove one ballot's old ranking from them, readable as the
  difference (decision log #39);
* **the newest point waits.** A point is shown only once ``LAG`` ballots
  first cast after it are counted (``shown``): each ballot records how many
  points had been taken when it was first cast, its *epoch*, a bucket of at
  least ``STEP`` ballots. The result published at closure is the
  whole live set, so it minus the last point shown before closure is what came
  after: never fewer than ``LAG`` electors. After closure the final standing is shown too —
  it is the published result. ``LAG`` is shorter than ``STEP`` at the
  requirements owner's request, trading that floor for a fresher newest point
  (decision log #39).

Each point carries the ranks, the Condorcet winner, the Smith set, the
head-to-head counts (or, under plurality and approval, the count per option)
and the number of ballots per distinct ranking. The residual exposure is a
group of ``STEP`` electors — or the closing ``LAG`` — that all agree on a
duel, or all cast the same ranking: the difference then states each one's
choice. R-11.5 bis accepts that in exchange for the figures.

A countersignature or a deletion of a paper ballot after a point was taken
does not change that point: the point holds what was counted then.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from apps.core.types import OptionId

from .methods import Method, Ranking, option_counts, pairwise_matrix, schulze_paths

#: A ballot's ranking as a hashable key: its groups, each in the poll's option
#: order so that ``[[b, a]]`` and ``[[a, b]]`` are the same tie.
Ordering = tuple[tuple[OptionId, ...], ...]

#: Ballots counted between two points.
STEP = 10

#: Ballots first cast after a point, and counted, before it is shown.
LAG = 5

#: The normal quantile of a two-sided 95 % interval.
Z95 = 1.959964


@dataclass(frozen=True)
class TrendPoint:
    """The standing at the ``sequence``-th point, taken on ``through``.

    ``sequence`` is the point's place in the series, 1 for the first; the
    final standing added after closure follows the last point taken.

    ``ranks[o]`` is 1 for the leading option; options the method cannot
    separate share a rank. ``smith_set`` is in the poll's option order.
    ``pairwise[i][j]`` counts the ballots ranking ``i`` above ``j`` (§8.1);
    ``counts`` is the plurality or approval count, ``None`` under Schulze.
    ``orderings`` counts the ballots by the ranking they carry (R-11.3).
    """

    through: date
    sequence: int
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

    def margin_interval(self, i: OptionId, j: OptionId, z: float = Z95) -> tuple[float, float]:
        """A confidence interval on ``margin(i, j)``, in ballots.

        Wilson's interval on the share of ``i`` among the ballots that separate
        the two, the ones preferring neither left aside, scaled back to a
        margin. It measures how far the ballots received so far are from
        settling the duel, as if they were a random draw from those to come:
        it knows nothing of who votes early and who late (decision log #39).
        Deterministic, so a point shown never changes. ``(0, 0)`` when no
        ballot separates the two.
        """
        won, lost = self.pairwise[i][j], self.pairwise[j][i]
        m = won + lost
        if m == 0:
            return 0.0, 0.0
        share = won / m
        centre = (share + z * z / (2 * m)) / (1 + z * z / m)
        half = z / (1 + z * z / m) * math.sqrt(share * (1 - share) / m + z * z / (4 * m * m))
        return m * (2 * (centre - half) - 1), m * (2 * (centre + half) - 1)


def due(ballots_counted: int, points_taken: int, step: int = STEP) -> bool:
    """Whether a further point falls due now: the ballots counted have reached
    the next multiple of ``step``. The count moves by at most one per ballot
    write, so it meets each multiple exactly; a paper deletion can lower it,
    and the next point then waits for the next multiple, not this one again."""
    return ballots_counted >= step * (points_taken + 1)


def shown(sequence: int, epochs: Iterable[int], lag: int = LAG) -> bool:
    """Whether point ``sequence`` may be shown: ``lag`` ballots counted now
    were first cast after it. ``epochs`` are those of the ballots counted now,
    each the number of points taken before it was first cast."""
    return sum(1 for epoch in epochs if epoch >= sequence) >= lag


def encode(table: Mapping[Ordering, int]) -> list[dict[str, object]]:
    """``orderings`` as stored: a list, sorted so that equal tables store
    equal bytes."""
    rows = [{"ranking": [list(g) for g in key], "count": n} for key, n in table.items()]
    return sorted(rows, key=lambda row: (str(row["ranking"]), row["count"]))


def decode(rows: Iterable[Mapping[str, object]]) -> list[Ranking]:
    """The ballots a stored table stands for, one ranking per ballot. Enough
    to recompute every figure of the point, which depends on nothing else."""
    ballots: list[Ranking] = []
    for row in rows:
        groups = row["ranking"]
        count = row["count"]
        assert isinstance(groups, list) and isinstance(count, int)
        ranking = [[OptionId(str(o)) for o in group] for group in groups]
        ballots.extend([ranking] * count)
    return ballots


def standing(
    through: date,
    sequence: int,
    ballots: Sequence[Ranking],
    options: Sequence[OptionId],
    method: Method,
) -> TrendPoint:
    """Every figure of one point, from the ballots it counts."""
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
        sequence=sequence,
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
