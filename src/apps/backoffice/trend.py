# SPDX-License-Identifier: 0BSD
"""Read model for the trend screen (R-11.5 bis).

Reads the points recorded as they fell due (``TrendSnapshot``,
``apps.ballots.trendpoints``) and, for the five-ballot wait and the final
standing, the live ballots' rankings and epochs — never ``Registration``, and
no ballot time or order, which do not exist (decision log #42). What makes the
screen safe is how its points are cut (``apps.tally.trend``), not that its
readers lack the other list (docs/specification-decision-log.md #39).
"""

from __future__ import annotations

import itertools
import math
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone
from django.utils.formats import number_format

from apps.ballots.models import Ballot, TrendSnapshot
from apps.core.types import OptionId
from apps.elections.models import Poll, PollState
from apps.elections.resultcards import interval_pts as _interval
from apps.elections.resultcards import pct as _pct
from apps.elections.resultcards import shown_interval as _shown_interval
from apps.elections.resultcards import signed as _signed
from apps.tally import trend as pure
from apps.tally.methods import Method
from apps.tally.trend import TrendPoint

#: Withdrawn is absent on purpose: R-3.11 takes every figure of the poll off
#: view, and draft or announced polls have no ballot to show.
_SHOWN_IN = (PollState.OPEN, PollState.CLOSED, PollState.PUBLISHED)


def enabled(poll: Poll) -> bool:
    """Whether this poll's back office offers the trend at all."""
    return poll.pk in settings.TREND_POLL_IDS and poll.state in _SHOWN_IN


def series(poll: Poll) -> list[TrendPoint]:
    """The points to show: each one recorded, once five ballots counted now
    were first cast after it; and once the poll is closed, the final standing,
    unless the last point shown already is it.

    A point holds what was counted when it fell due — the version then in
    force of each ballot, paper entries awaiting countersignature and deleted
    ones counting for nothing (§3.4) — and never changes after.
    """
    option_ids = poll.options.order_by("position").values_list("option_id", flat=True)
    options = [OptionId(o) for o in option_ids]
    method = Method(poll.tally_method)
    live = list(Ballot.live.filter(poll=poll).values_list("ranking", "epoch"))
    epochs = [epoch for _ranking, epoch in live]
    points = [
        pure.standing(
            snapshot.taken_on,
            snapshot.sequence,
            pure.decode(snapshot.orderings),
            options,
            method,
        )
        for snapshot in TrendSnapshot.objects.filter(poll=poll).order_by("sequence")
        if pure.shown(snapshot.sequence, epochs)
    ]
    if poll.state != PollState.OPEN and live:
        ballots = [[[OptionId(o) for o in group] for group in ranking] for ranking, _epoch in live]
        closed_on = (
            timezone.localdate(poll.closed_at, ZoneInfo(poll.timezone))
            if poll.closed_at
            else (timezone.localdate(timezone=ZoneInfo(poll.timezone)))
        )
        final = pure.standing(
            closed_on, (points[-1].sequence if points else 0) + 1, ballots, options, method
        )
        if not points or points[-1].orderings != final.orderings:
            points.append(final)
    return points


#: Categorical slots the stylesheet defines (``--s1`` … ``--s8``). With more
#: options than this the curves are left out: the table and the duels carry
#: the figures, and a ninth hue generated on the fly would not be told apart.
CHART_SERIES = 8

#: On the curves, a band is drawn only where its interval is narrower than
#: ± this many points. A wider one says little beyond "too few ballots yet",
#: which the tooltip already gives in figures, and swamps the lines it
#: surrounds. The duels' sparklines keep every band: each is alone in its box.
BAND_MAX_HALF_WIDTH = 10.0


def _score(point: TrendPoint, option: OptionId) -> float:
    """What the curves plot, in points of the ballots counted so far.

    Under Schulze, the option's tightest duel margin (``tightest_duel``): above
    zero means it beats every other option head to head. Under plurality or
    approval, its share of the ballots.
    """
    if point.counts is not None:
        return _pct(point.counts[option], point.ballot_count)
    duel = point.tightest_duel(option)
    return _pct(duel[1], point.ballot_count) if duel else 0.0


# --- the curves ---------------------------------------------------------------

_W, _H = 760, 300
_LEFT, _RIGHT, _TOP, _BOTTOM = 52, 230, 18, 34
_STEPS = (1, 2, 5, 10, 20, 25, 50)


def _axis(values: list[float]) -> tuple[float, float, int]:
    """A domain that holds every value and zero, on round ticks (≤ 7)."""
    lo, hi = min([*values, 0.0]), max([*values, 0.0])
    if hi - lo < 1:
        lo, hi = lo - 5, hi + 5
    step = next((s for s in _STEPS if (hi - lo) / s <= 6), 100)
    return step * math.floor(lo / step), step * math.ceil(hi / step), step


def _spread(ys: list[int], gap: int = 16) -> list[int]:
    """Push end labels apart vertically, keeping their order, so none overlap."""
    order = sorted(range(len(ys)), key=lambda k: ys[k])
    out = list(ys)
    for a, b in itertools.pairwise(order):
        out[b] = max(out[b], out[a] + gap)
    return out


def _score_interval(point: TrendPoint, option: OptionId) -> tuple[float, float] | None:
    """The 95 % interval of what ``_score`` plots under Schulze: the margin of
    the option's tightest duel at that point."""
    duel = point.tightest_duel(option)
    return _interval(point, option, duel[0]) if duel else None


def _banded(last: TrendPoint) -> set[OptionId]:
    """The options whose curve carries its interval as a band: the leader and
    its closest rival, or the options tied in the lead. Every band at once
    would bury the lines; the rest are in the tooltip."""
    leaders = set(last.leaders)
    if len(leaders) == 1:
        (leader,) = leaders
        duel = last.tightest_duel(leader)
        if duel is not None:
            leaders.add(duel[0])
    return leaders


def curves(
    points: list[TrendPoint],
    options: list[tuple[OptionId, str]],
    *,
    schulze: bool,
    intervals: bool = False,
) -> dict[str, object] | None:
    """Geometry for the main chart: one line per option across the points.

    Every coordinate is a whole number: the template would render a float
    with the active locale's decimal comma, which SVG reads as a separator.
    Colour follows the option's position in the poll, never its rank.

    With ``intervals`` (Schulze only), the leader's and its rival's curves
    carry their 95 % interval as a band where narrower than
    ``BAND_MAX_HALF_WIDTH``, and the tooltip every option's, however wide. The
    axis is fitted to the lines, not the bands, which can still reach ten
    points past them; the template clips them to the plot instead.
    """
    if not points or len(options) > CHART_SERIES:
        return None
    scores = {o: [_score(p, o) for p in points] for o, _label in options}
    lo, hi, step = _axis([v for vs in scores.values() for v in vs])
    plot_w, plot_h = _W - _LEFT - _RIGHT, _H - _TOP - _BOTTOM

    def x(k: int) -> int:
        if len(points) == 1:
            return _LEFT + plot_w // 2
        return _LEFT + round(plot_w * k / (len(points) - 1))

    def y(v: float) -> int:
        return _TOP + round(plot_h * (hi - v) / (hi - lo))

    xs = [x(k) for k in range(len(points))]
    ends = _spread([y(scores[o][-1]) for o, _label in options])
    bounds: dict[OptionId, list[tuple[float, float] | None]] = {}
    if intervals and schulze:
        bounds = {o: [_score_interval(p, o) for p in points] for o, _label in options}
    banded = _banded(points[-1]) if bounds else set()

    def narrow(b: tuple[float, float] | None) -> bool:
        return b is not None and (b[1] - b[0]) / 2 < BAND_MAX_HALF_WIDTH

    def band(option: OptionId) -> str | None:
        """One closed shape per run of consecutive points narrow enough; an
        interval usually narrows as ballots come in, but a margin moving
        towards an even split can widen it again."""
        if option not in banded:
            return None
        shapes = []
        for is_narrow, run in itertools.groupby(
            enumerate(bounds[option]), key=lambda kb: narrow(kb[1])
        ):
            pairs = [(k, b) for k, b in run if b is not None]
            if not is_narrow or len(pairs) < 2:
                continue
            upper = [f"{xs[k]},{y(b[1])}" for k, b in pairs]
            lower = [f"{xs[k]},{y(b[0])}" for k, b in reversed(pairs)]
            shapes.append("M" + " L".join(upper + lower) + " Z")
        return " ".join(shapes) or None

    def tip_interval(option: OptionId, k: int) -> dict[str, object] | None:
        b = bounds[option][k] if bounds else None
        return _shown_interval(b) if b else None

    series = []
    for slot, ((option, label), end_y) in enumerate(zip(options, ends, strict=True), start=1):
        series.append(
            {
                "slot": slot,
                "label": label,
                "band": band(option) if bounds else None,
                "path": " ".join(
                    f"{'M' if k == 0 else 'L'}{xs[k]},{y(v)}" for k, v in enumerate(scores[option])
                ),
                "marks": [{"x": xs[k], "y": y(v)} for k, v in enumerate(scores[option])],
                "end_y": end_y,
                "end_value": _signed(scores[option][-1])
                if schulze
                else number_format(scores[option][-1], 0),
            }
        )
    ticks = []
    v = lo
    while v <= hi:
        ticks.append(
            {"y": y(v), "label": _signed(v) if schulze else number_format(v, 0), "zero": v == 0}
        )
        v += step
    # Several points can fall on one day: label a day once, at its first
    # point, and keep at most about six labels.
    firsts = [k for k, p in enumerate(points) if k == 0 or p.through != points[k - 1].through]
    every = max(1, math.ceil(len(firsts) / 6))
    dates = [{"x": xs[k], "date": points[k].through} for k in firsts[::every]]
    columns = []
    for k, p in enumerate(points):
        rows = sorted(
            (
                {
                    "slot": slot,
                    "label": label,
                    "value": _signed(scores[o][k]) if schulze else number_format(scores[o][k], 1),
                    "interval": tip_interval(o, k),
                    "raw": scores[o][k],
                }
                for slot, (o, label) in enumerate(options, start=1)
            ),
            key=lambda r: -float(r["raw"]),  # type: ignore[arg-type]
        )
        columns.append({"x": xs[k], "through": p.through, "count": p.ballot_count, "rows": rows})
    return {
        "width": _W,
        "height": _H,
        "left": _LEFT,
        "right": _W - _RIGHT,
        "top": _TOP,
        "bottom": _H - _BOTTOM,
        "zero_y": y(0),
        "plot_w": plot_w,
        "plot_h": plot_h,
        "above_h": y(0) - _TOP,
        "label_x": _W - _RIGHT + 14,
        "ticks": ticks,
        "dates": dates,
        "series": series,
        "banded": any(line["band"] for line in series),
        "band_max": number_format(BAND_MAX_HALF_WIDTH, 0),
        "columns": columns,
        "xs": ",".join(str(c) for c in xs),
    }


# --- the summary and the duels -------------------------------------------------


def table(
    points: list[TrendPoint], options: list[tuple[OptionId, str]], *, schulze: bool
) -> list[dict[str, object]]:
    """The figures behind the curves, newest first, for the table view."""
    labels = dict(options)
    return [
        {
            "through": p.through,
            "count": p.ballot_count,
            "cells": [
                {
                    "rank": p.ranks[o],
                    "value": _signed(_score(p, o)) if schulze else number_format(_score(p, o), 1),
                }
                for o, _label in options
            ],
            "condorcet": labels[p.condorcet_winner] if p.condorcet_winner else None,
            "smith": [labels[o] for o in p.smith_set],
        }
        for p in reversed(points)
    ]
