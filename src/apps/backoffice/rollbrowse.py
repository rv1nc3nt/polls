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

from collections.abc import Iterable
from uuid import UUID

from django.db import models
from django.db.models import Q, QuerySet
from django.utils.translation import gettext_lazy as _

from apps.elections.models import Poll, RollEntry, WorkingRollEntry
from apps.registrations.models import Channel, Registration, RegistrationState

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


class Participation(models.TextChoices):
    """Where an elector on a poll's frozen copy stands, for the poll admin
    answering "I cannot vote" (R-7.5): the names-with-a-voted-flag list of §7.

    Read from ``Registration.state`` and ``channel`` alone (INV-5). There is
    deliberately no timestamp beside ``online``: when a registration voted is
    the one fact that would line it up with a ballot's own time (INV-1).
    """

    NOT_REGISTERED = "not_registered", _("pas d'inscription")
    UNCONFIRMED = "unconfirmed", _("inscription non confirmée")
    NOT_VOTED = "not_voted", _("inscrit, n'a pas voté")
    ONLINE = "online", _("a voté en ligne")
    PAPER = "paper", _("a voté sur papier")


def participation(poll: Poll, entries: Iterable[RollEntry]) -> dict[UUID, Participation]:
    """``roll_entry_id → Participation`` for every entry in ``entries``.

    A ``pending_review`` registration is bound to no entry yet, so it reads
    here as ``NOT_REGISTERED``; screen 4 is where it is found. A cleared paper
    shell (R-9.4, decision log #27) is no elector's registration and reads the
    same way — the elector registers online like anyone else.
    """
    ids = [entry.pk for entry in entries]
    result = dict.fromkeys(ids, Participation.NOT_REGISTERED)
    rows = (
        Registration.objects.filter(poll=poll, roll_entry__in=ids)
        .exclude(state=RegistrationState.REJECTED)
        .exclude(channel=Channel.NONE, email_canonical="")
        .values_list("roll_entry_id", "state", "channel")
    )
    for entry_id, state, channel in rows:
        if channel == Channel.ONLINE:
            result[entry_id] = Participation.ONLINE
        elif channel == Channel.PAPER:
            result[entry_id] = Participation.PAPER
        elif state == RegistrationState.ACTIVE:
            result[entry_id] = Participation.NOT_VOTED
        else:
            result[entry_id] = Participation.UNCONFIRMED
    return result
