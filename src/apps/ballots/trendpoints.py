# SPDX-License-Identifier: 0BSD
"""The trend's points (R-11.5 bis), recorded at the moment each falls due.

R-11.5 bis recomputes the ranking each time the ballots counted reach a
further multiple of ten, "each ballot counted as it stood at that moment".
Rebuilding those moments afterwards needs every ballot's time, or at least its
order, and either lines a first ballot up with the registration confirmed just
before it (INV-1, decision log #42). So ballots keep neither, and the point is
taken instead in the very transaction that brings the count to the multiple:
the live set then *is* the set the rule describes. A point is stored as the
number of ballots per distinct ranking and the day — nothing per ballot.

Recorded for every poll, whatever ``settings.TREND_POLL_IDS`` says: that
setting only decides whether the screen is offered, and a poll switched on
while already open still shows the points it has passed (decision log #39).

Called by every ballot write that can raise the count: a first online cast, a
paper entry, a paper correction and a countersignature (``services``). A test
that writes ``Ballot`` rows directly calls ``record_due_point`` itself.
"""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.core.types import OptionId
from apps.elections.models import Poll
from apps.tally import trend

from .models import Ballot, TrendSnapshot


def current_epoch(poll: Poll) -> int:
    """The epoch a ballot first cast now receives: the points taken so far."""
    return TrendSnapshot.objects.filter(poll=poll).count()


def record_due_point(poll: Poll, today: date | None = None) -> TrendSnapshot | None:
    """Take the next point if the ballots counted have reached it, and return
    it; ``None`` when none is due. Runs inside the caller's ballot write, so
    the point and the ballot that brought it about stand or fall together, and
    SQLite's single writer keeps two concurrent writes from taking one point
    twice (``uniq_trend_point_sequence`` would refuse the second anyway)."""
    taken = TrendSnapshot.objects.filter(poll=poll).count()
    rankings = list(Ballot.live.filter(poll=poll).values_list("ranking", flat=True))
    if not trend.due(len(rankings), taken):
        return None
    options = [
        OptionId(o) for o in poll.options.order_by("position").values_list("option_id", flat=True)
    ]
    ballots = [[[OptionId(o) for o in group] for group in ranking] for ranking in rankings]
    return TrendSnapshot.objects.create(
        poll=poll,
        sequence=taken + 1,
        ballot_count=len(ballots),
        taken_on=today or timezone.localdate(timezone=ZoneInfo(poll.timezone)),
        orderings=trend.encode(trend.orderings(ballots, options)),
    )
