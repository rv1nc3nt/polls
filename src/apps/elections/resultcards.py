# SPDX-License-Identifier: 0BSD
"""A result as cards: the headline, the duels, the duel matrix and the ballots
per ranking. One representation for two pages: the back-office trend (R-11.5
bis) shows its latest point this way, and the public results page shows the
published result (R-11.2, R-11.3) this way.

Every function reads a ``tally.trend.TrendPoint``. The trend builds its points
from the ballots counted when each fell due; ``published_standing`` builds one
from the figures the publication document states, so the public page draws
the same figures the document publishes. Only the final result is ever
shown publicly: the curves and the dated history stay in the back office
(``backoffice.trend``), where R-11.5 bis keeps the trend.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping
from datetime import date
from typing import Any

from django.utils.formats import number_format

from apps.core.types import OptionId
from apps.tally.methods import Method
from apps.tally.trend import Ordering, TrendPoint, standing_of


def published_standing(document: Mapping[str, Any], through: date) -> TrendPoint:
    """The published result as a ``TrendPoint``, from the document's own
    matrix, counts and ballots per ranking. The orderings are those published
    (a Schulze poll with at most four options, R-11.3); without them the point
    has none, and the page shows no ballots-per-ranking card."""
    options = [OptionId(o) for o in document["options"]]
    position = {o: k for k, o in enumerate(options)}
    method = Method(document["tally_method"])
    matrix = {
        OptionId(i): {OptionId(j): int(n) for j, n in row.items()}
        for i, row in document["matrix"].items()
    }
    published_counts = document.get("derivation", {}).get("counts")
    counts = (
        {OptionId(o): int(n) for o, n in published_counts.items()}
        if method is not Method.SCHULZE and published_counts is not None
        else None
    )
    # "a=b>c": groups in ranking order, ids within a group by code point; the
    # trend keys a ranking by its groups in the poll's option order.
    table: dict[Ordering, int] = {}
    for key, n in document.get("orderings", {}).items():
        ordering = tuple(
            tuple(sorted((OptionId(o) for o in group.split("=")), key=position.__getitem__))
            for group in key.split(">")
        )
        table[ordering] = int(n)
    return standing_of(
        through, 1, int(document["ballot_count"]), matrix, counts, table, options, method
    )


def vote_counts(point: TrendPoint, options: list[tuple[OptionId, str]]) -> list[dict[str, object]]:
    """Plurality or approval: each option's count, most first, as bars on the
    scale of the highest. Empty under Schulze, which is not decided on counts."""
    if point.counts is None:
        return []
    slots = {o: k for k, (o, _label) in enumerate(options, start=1)}
    top = max(point.counts.values(), default=0)
    rows = [
        {
            "label": label,
            "slot": slots[o],
            "count": point.counts[o],
            "pct": pct(point.counts[o], point.ballot_count),
            "rank": point.ranks[o],
            "bar": point.counts[o],
            "rest": top - point.counts[o],
        }
        for o, label in options
    ]
    rows.sort(key=lambda row: (-int(row["count"]), int(row["slot"])))  # type: ignore[call-overload]
    return rows


def pct(part: float, whole: int) -> float:
    """``part`` as a percentage of ``whole``; 0 when there is nothing to divide."""
    return 100 * part / whole if whole else 0.0


def signed(value: float, decimals: int | None = None) -> str:
    """``+12,5`` / ``−3`` / ``0``, in the active locale, true minus sign; one
    decimal only where needed unless ``decimals`` says how many."""
    if decimals is None:
        decimals = 1 if value % 1 else 0
    shown = round(value, decimals)
    text = number_format(abs(shown), decimals)
    return ("+" if shown > 0 else "−" if shown < 0 else "") + text


def direction(now: float, before: float | None) -> str | None:
    """``up``, ``down`` or ``flat`` — the stylesheet's arrow, never colour alone."""
    if before is None:
        return None
    return "up" if now > before else "down" if now < before else "flat"


def interval_pts(point: TrendPoint, i: OptionId, j: OptionId) -> tuple[float, float]:
    """``margin_interval`` in points of the ballots counted, like the margin."""
    lo, hi = point.margin_interval(i, j)
    return pct(lo, point.ballot_count), pct(hi, point.ballot_count)


def shown_interval(bounds: tuple[float, float]) -> dict[str, object]:
    """An interval for display: its bounds, and whether it leaves zero out —
    the duel's winner is then clear of the noise of the ballots received."""
    lo, hi = bounds
    # Both bounds to one decimal, so "−19,0 à +23,8" reads as a pair.
    return {"lo": signed(lo, 1), "hi": signed(hi, 1), "clear": lo > 0 or hi < 0}


def spark(
    values: list[float],
    band: list[tuple[float, float]] | None = None,
    width: int = 120,
    height: int = 32,
) -> dict[str, object]:
    """A sparkline of a duel's margin, zero line included, and its confidence
    band where given."""
    bounds = [v for b in band or [] for v in b]
    lo, hi = min([*values, *bounds, 0.0]), max([*values, *bounds, 0.0])
    if hi - lo < 1:
        lo, hi = lo - 1, hi + 1

    def y(v: float) -> int:
        return 3 + round((height - 6) * (hi - v) / (hi - lo))

    def x(k: int) -> int:
        return width // 2 if len(values) == 1 else 3 + round((width - 6) * k / (len(values) - 1))

    band_path = None
    if band:
        upper = [f"{x(k)},{y(b[1])}" for k, b in enumerate(band)]
        lower = [f"{x(k)},{y(b[0])}" for k, b in reversed(list(enumerate(band)))]
        band_path = "M" + " L".join(upper + lower) + " Z"
    return {
        "width": width,
        "height": height,
        "zero_y": y(0),
        "band": band_path,
        "path": " ".join(f"{'M' if k == 0 else 'L'}{x(k)},{y(v)}" for k, v in enumerate(values)),
        "end_x": x(len(values) - 1),
        "end_y": y(values[-1]),
    }


def summary(
    points: list[TrendPoint],
    options: list[tuple[OptionId, str]],
    *,
    schulze: bool,
    intervals: bool,
) -> dict[str, object]:
    """The headline figures of the latest point, and how they moved since the
    one before."""
    last = points[-1]
    previous = points[-2] if len(points) > 1 else None
    labels = dict(options)
    leaders = last.leaders
    lead: dict[str, object] | None = None
    if len(leaders) == 1:
        leader = leaders[0]
        if schulze:
            duel = last.tightest_duel(leader)
            if duel is not None:
                rival, margin = duel
                pts = pct(margin, last.ballot_count)
                before = (
                    pct(previous.margin(leader, rival), previous.ballot_count) if previous else None
                )
                lead = {
                    "pts": signed(pts),
                    "interval": (
                        shown_interval(interval_pts(last, leader, rival)) if intervals else None
                    ),
                    "ballots": margin,
                    "rival": labels[rival],
                    "for_pct": pct(last.pairwise[leader][rival], last.ballot_count),
                    "against_pct": pct(last.pairwise[rival][leader], last.ballot_count),
                    "delta": signed(pts - before) if before is not None else None,
                    "delta_dir": direction(pts, before),
                }
        elif last.counts is not None:
            counts = last.counts
            runner = max((o for o in counts if o != leader), key=counts.__getitem__, default=None)
            if runner is not None:
                gap = counts[leader] - counts[runner]
                lead = {
                    "pts": signed(pct(gap, last.ballot_count)),
                    "ballots": gap,
                    "rival": labels[runner],
                    "for_pct": pct(counts[leader], last.ballot_count),
                    "against_pct": pct(counts[runner], last.ballot_count),
                    "delta": None,
                    "delta_dir": None,
                    "interval": None,
                }
    return {
        "through": last.through,
        "count": last.ballot_count,
        "count_delta": last.ballot_count - previous.ballot_count if previous else None,
        "leaders": [labels[o] for o in leaders],
        "leader_changed": previous is not None and set(previous.leaders) != set(leaders),
        "condorcet": labels[last.condorcet_winner] if last.condorcet_winner else None,
        "smith": [labels[o] for o in last.smith_set],
        "lead": lead,
    }


def duels(
    points: list[TrendPoint], options: list[tuple[OptionId, str]], *, intervals: bool
) -> list[dict[str, object]]:
    """Every head-to-head pair at the latest point, closest-run last.

    Each is oriented winner first, with the ballots preferring neither (ranked
    equal, or both left unranked, R-10.4) shown between the two shares, and
    the margin's history as a sparkline. Pairs involving a leader come first.
    With ``intervals``, each margin carries its 95 % interval, and the
    sparkline the interval's history as a band.
    """
    last = points[-1]
    previous = points[-2] if len(points) > 1 else None
    slots = {o: k for k, (o, _label) in enumerate(options, start=1)}
    labels = dict(options)
    n = last.ballot_count
    out = []
    for (a, _la), (b, _lb) in itertools.combinations(options, 2):
        left, right = (a, b) if last.margin(a, b) >= 0 else (b, a)
        won, lost = last.pairwise[left][right], last.pairwise[right][left]
        margin = pct(won - lost, n)
        history = [pct(p.margin(left, right), p.ballot_count) for p in points]
        delta = margin - history[-2] if previous is not None else None
        band = [interval_pts(p, left, right) for p in points] if intervals else None
        out.append(
            {
                "left": {
                    "label": labels[left],
                    "slot": slots[left],
                    "count": won,
                    "pct": pct(won, n),
                },
                "right": {
                    "label": labels[right],
                    "slot": slots[right],
                    "count": lost,
                    "pct": pct(lost, n),
                },
                "neither": n - won - lost,
                "neither_pct": pct(n - won - lost, n),
                "tied": won == lost,
                "margin": signed(margin),
                "margin_ballots": won - lost,
                "delta": signed(delta) if delta is not None else None,
                "delta_dir": None if delta is None else direction(delta, 0.0),
                "interval": shown_interval(band[-1]) if band else None,
                "spark": spark(history, band) if len(history) > 1 else None,
                "leader": bool({left, right} & set(last.leaders)),
                "abs_margin": abs(won - lost),
            }
        )
    out.sort(key=lambda d: (not d["leader"], -int(d["abs_margin"])))  # type: ignore[call-overload]
    return out


def matrix(point: TrendPoint, options: list[tuple[OptionId, str]]) -> list[dict[str, object]]:
    """The duel matrix at one point (§8.1, the published matrix of R-11.2):
    row ``i``, column ``j`` is the number of ballots ranking ``i`` above ``j``.

    Each cell says whether the row's option wins, loses or ties that duel, so
    the template can mark it by more than colour (R-14.1).
    """
    n = point.ballot_count
    rows = []
    for slot, (i, label) in enumerate(options, start=1):
        cells: list[dict[str, object]] = []
        for j, _other in options:
            if i == j:
                cells.append({"self": True})
                continue
            won, lost = point.pairwise[i][j], point.pairwise[j][i]
            cells.append(
                {
                    "self": False,
                    "count": won,
                    "pct": pct(won, n),
                    "outcome": "win" if won > lost else "loss" if won < lost else "tie",
                }
            )
        rows.append({"slot": slot, "label": label, "cells": cells})
    return rows


def ballot_types(point: TrendPoint, options: list[tuple[OptionId, str]]) -> list[dict[str, object]]:
    """The ballots per distinct ranking at one point, most frequent first.

    Each ranking is a list of groups of options — one option per group unless
    the ballot ranks some equal — followed by the options it left out, which
    R-10.4 counts as equal-last.
    """
    slots = {o: k for k, (o, _label) in enumerate(options, start=1)}
    labels = dict(options)
    n = point.ballot_count
    top = max(point.orderings.values(), default=0)
    rows = []
    for ordering, count in sorted(
        point.orderings.items(), key=lambda kv: (-kv[1], [[slots[o] for o in g] for g in kv[0]])
    ):
        ranked = {o for group in ordering for o in group}
        rows.append(
            {
                "groups": [
                    [{"label": labels[o], "slot": slots[o]} for o in group] for group in ordering
                ],
                "unranked": [
                    {"label": label, "slot": slots[o]} for o, label in options if o not in ranked
                ],
                "count": count,
                "pct": pct(count, n),
                "bar": count,
                "rest": top - count,
            }
        )
    return rows
