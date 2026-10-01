# SPDX-License-Identifier: 0BSD
"""The back-office trend (R-11.5 bis): the ranking re-counted day after day.

Pure, like the rest of this package: the caller supplies each live ballot's
calendar day in the poll's timezone and the last day that may be shown, never
a clock.

What is computed is bounded by INV-1 rather than by what would be most
informative (docs/specification-decision-log.md #39). The audience — the poll
administrator — also holds each registration's ``confirmed_at``, and an elector
often votes a minute after confirming. So:

* a point only ever covers **whole days**, and the day still running is never
  shown, so reloading the screen through the day reveals nothing finer;
* consecutive days are **merged until a bin holds ``MIN_BIN`` ballots**, the
  same reasoning that keeps R-11.5 from publishing turnout by polling station;
* each point carries the ranks, the Condorcet winner, the Smith set, the
  head-to-head counts (or, under plurality and approval, the count per
  option) and the number of ballots per distinct ranking. Subtracting two
  consecutive points yields the same figures for one bin, so ``MIN_BIN`` is
  the smallest group whose aggregate anyone sees — the size of a very small
  polling station. The residual exposure is a bin whose electors all agree on
  a duel or, through the per-ranking counts, all cast the same ranking: its
  aggregate then states each one's choice. R-11.5 bis accepts that in
  exchange for the figures (decision log #39).

Each point is cumulative: every live ballot whose day is on or before
``through``. A ballot modified on a later day is counted from the day of its
current version (R-7.2), the earlier versions being no longer live.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from apps.core.types import OptionId

from .methods import Method, Ranking, option_counts, pairwise_matrix, schulze_paths

#: A ballot's ranking as a hashable key: its groups, each in the poll's option
#: order so that ``[[b, a]]`` and ``[[a, b]]`` are the same tie.
Ordering = tuple[tuple[OptionId, ...], ...]

#: The fewest ballots a bin may hold before it is shown on its own.
MIN_BIN = 10


@dataclass(frozen=True)
class TrendPoint:
    """The standing after every ballot cast up to and including ``through``.

    ``ranks[o]`` is 1 for the leading option; options the method cannot
    separate share a rank. ``smith_set`` is in the poll's option order.
    ``pairwise[i][j]`` counts the ballots ranking ``i`` above ``j`` (§8.1);
    ``counts`` is the plurality or approval count, ``None`` under Schulze.
    ``orderings`` counts the ballots by the ranking they carry (R-11.3).
    """

    through: date
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
    ballots: Sequence[tuple[date, Ranking]],
    options: Sequence[OptionId],
    method: Method,
    *,
    last_day: date,
    final: bool,
    min_bin: int = MIN_BIN,
) -> list[TrendPoint]:
    """One cumulative point per bin of at least ``min_bin`` ballots.

    Ballots dated after ``last_day`` are ignored — the caller passes the day
    before today while ballots can still arrive. Where ``final`` is false, a
    trailing remainder below ``min_bin`` waits for later days rather than being
    shown; once ``final``, it is folded into the last bin instead of being
    dropped, so the last point is the whole live set.
    """
    by_day: dict[date, list[Ranking]] = {}
    for day, ranking in ballots:
        if day <= last_day:
            by_day.setdefault(day, []).append(ranking)

    bins: list[tuple[date, int]] = []
    pending = 0
    last_seen: date | None = None
    for day in sorted(by_day):
        pending += len(by_day[day])
        last_seen = day
        if pending >= min_bin:
            bins.append((day, pending))
            pending = 0
    if final and pending and bins and last_seen is not None:
        _through, size = bins.pop()
        bins.append((last_seen, size + pending))

    points: list[TrendPoint] = []
    cumulative: list[Ranking] = []
    days = iter(sorted(by_day))
    for through, _size in bins:
        for day in days:
            cumulative.extend(by_day[day])
            if day == through:
                break
        points.append(_point(through, cumulative, options, method))
    return points


def _point(
    through: date, ballots: Sequence[Ranking], options: Sequence[OptionId], method: Method
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
