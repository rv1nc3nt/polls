# SPDX-License-Identifier: 0BSD
"""Read model for the trend screen (R-11.5 bis).

Reads ``Ballot`` alone — every version's creation instant, tracking code,
ranking and status — and never ``Registration``: what makes the screen safe is
how its points are cut (``apps.tally.trend``), not that its readers lack the
other list (docs/specification-decision-log.md #39).
"""

from __future__ import annotations

import itertools
import math
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils.formats import number_format

from apps.ballots.models import Ballot, BallotStatus
from apps.core.types import OptionId
from apps.elections.models import Poll, PollState
from apps.elections.resultcards import interval_pts as _interval
from apps.elections.resultcards import pct as _pct
from apps.elections.resultcards import shown_interval as _shown_interval
from apps.elections.resultcards import signed as _signed
from apps.tally.methods import Method
from apps.tally.trend import TrendPoint, Version, trend

#: Withdrawn is absent on purpose: R-3.11 takes every figure of the poll off
#: view, and draft or announced polls have no ballot to show.
_SHOWN_IN = (PollState.OPEN, PollState.CLOSED, PollState.PUBLISHED)


def enabled(poll: Poll) -> bool:
    """Whether this poll's back office offers the trend at all."""
    return poll.pk in settings.TREND_POLL_IDS and poll.state in _SHOWN_IN


def series(poll: Poll) -> list[TrendPoint]:
    """The points to show, every version of every ballot considered.

    Superseded versions count until the next one arrives, which is what keeps
    a point fixed once shown. Paper entries awaiting countersignature and
    deleted ones count for nothing (§3.4).
    """
    zone = ZoneInfo(poll.timezone)
    counted = (BallotStatus.LIVE, BallotStatus.SUPERSEDED)
    rows = Ballot.objects.filter(poll=poll).values_list(
        "created_at", "tracking_code", "ranking", "status"
    )
    versions = [
        Version(
            at=created_at,
            day=created_at.astimezone(zone).date(),
            ballot=tracking_code,
            ranking=[[OptionId(o) for o in g] for g in ranking] if status in counted else None,
        )
        for created_at, tracking_code, ranking, status in rows
    ]
    option_ids = poll.options.order_by("position").values_list("option_id", flat=True)
    options = [OptionId(o) for o in option_ids]
    final = poll.state != PollState.OPEN
    return trend(versions, options, Method(poll.tally_method), final=final)


#: Categorical slots the stylesheet defines (``--s1`` … ``--s8``). With more
#: options than this the curves are left out: the table and the duels carry
#: the figures, and a ninth hue generated on the fly would not be told apart.
CHART_SERIES = 8


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
    carry their 95 % interval as a band, and the tooltip every option's. The
    axis is fitted to the lines, not the bands: an early band can span a
    hundred points and would flatten every line; the template clips it to the
    plot instead.
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

    def band(option: OptionId) -> str | None:
        pairs = [(k, b) for k, b in enumerate(bounds[option]) if b is not None]
        if option not in banded or len(pairs) < 2:
            return None
        upper = [f"{xs[k]},{y(b[1])}" for k, b in pairs]
        lower = [f"{xs[k]},{y(b[0])}" for k, b in reversed(pairs)]
        return "M" + " L".join(upper + lower) + " Z"

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
        "banded": bool(banded),
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
