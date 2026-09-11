# SPDX-License-Identifier: 0BSD
"""Plain browsing of an electoral roll: a poll's frozen copy (R-4.4,
``roll_status``) or the commune-wide working roll (screen 3, ``roll_import``).

Distinct from ``paper.snapshot_search``, which exists to confirm one
live-typed name against the elector standing in front of an operator (R-8.3)
and so scores near matches — a diacritic-aware token overlap, a date-of-birth
match — and ranks them. This is paging through everyone, in alphabetical
order, optionally narrowed by a plain substring; there is no query to score
because there is no single person being confirmed. Do not merge the two: a
browse screen ranking results the way a confirmation screen does would hide
rather than show, and a confirmation screen paginating alphabetically would
make an operator read past the match to find it.
"""

from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.elections.models import RollEntry, WorkingRollEntry

#: Matches the audit screen's page size (§6.5.8) — no reason for this one to
#: differ.
PAGE_SIZE = 50


def search[Entry: (RollEntry, WorkingRollEntry)](
    queryset: QuerySet[Entry], query: str
) -> QuerySet[Entry]:
    """Alphabetical, narrowed by a case-insensitive substring across the three
    name fields ``RollEntry`` and ``WorkingRollEntry`` share
    (``RollEntryFields``, §6.1) when ``query`` is given."""
    queryset = queryset.order_by("birth_name", "first_names")
    query = query.strip()
    if not query:
        return queryset
    return queryset.filter(
        Q(birth_name__icontains=query)
        | Q(usual_name__icontains=query)
        | Q(first_names__icontains=query)
    )
