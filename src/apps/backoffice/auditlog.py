# SPDX-License-Identifier: 0BSD
"""The read model behind screen 8, journal d'audit (§6.5.8).

Read-only, and there is nothing here that could be otherwise: INV-3 gives
``AuditEvent`` no update or delete path in the application or the database, so
this module offers filtering and rendering and no writer at all. The one write
the screen performs is its own access event, which §10 requires in its minimum
list and which the view records.

The interesting part is ``resolve_refs``. ``object_ref`` names a row rather than
copying anything out of it (§10), so after the retention purge (§11) it points
at a row that is gone. That is the design working, not a fault: the log still
reads *registration 7f3a… moved pending_review → active, by operator M, reason
name_divergence_accepted*, with no way to recover to whom. The screen must say
so in those words rather than render a broken link or an empty cell.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.apps import apps
from django.db.models import QuerySet

from apps.audit.models import AuditEvent
from apps.core.models import User
from apps.elections.models import Poll

#: The apps whose rows an ``object_ref`` can name. Scanned rather than listed
#: one model at a time so a model added later resolves without a change here.
_REFERENCED_APPS = ("core", "elections", "registrations", "ballots", "audit")


@dataclass(frozen=True)
class Filters:
    """Screen 8's filters: actor, date and object (§6.5.8)."""

    actor_id: str = ""
    object_ref: str = ""
    date_from: datetime | None = None
    date_to: datetime | None = None

    def as_audit_payload(self) -> dict[str, str]:
        """What the access event records about this consultation (§10).

        Nested under one key, and holding an actor id and an object reference —
        both non-identifying. An operator account id is staff identity, retained
        legitimately, and is not elector data (§10).
        """
        return {
            "actor_id": self.actor_id,
            "object_ref": self.object_ref,
            "date_from": self.date_from.isoformat() if self.date_from else "",
            "date_to": self.date_to.isoformat() if self.date_to else "",
        }


def events(poll: Poll, filters: Filters) -> QuerySet[AuditEvent]:
    """This poll's events, most recent first, filtered as asked."""
    queryset = AuditEvent.objects.filter(poll=poll).select_related("actor")
    if filters.actor_id:
        try:
            queryset = queryset.filter(actor_id=uuid.UUID(filters.actor_id))
        except ValueError:
            # A hand-edited query string. Filters nothing rather than erroring;
            # this is a log an auditor is browsing, not a form being submitted.
            pass
    if filters.object_ref:
        queryset = queryset.filter(object_ref__icontains=filters.object_ref)
    if filters.date_from:
        queryset = queryset.filter(at__gte=filters.date_from)
    if filters.date_to:
        queryset = queryset.filter(at__lt=filters.date_to)
    return queryset


def actors(poll: Poll) -> QuerySet[User]:
    """The accounts that appear in this poll's log, to populate the filter."""
    return User.objects.filter(audit_events__poll=poll).distinct().order_by("username")


def resolve_refs(page: list[AuditEvent]) -> dict[str, bool]:
    """Which ``object_ref`` values on this page still name a row.

    One query per referenced model per page rather than one per event: an audit
    screen over a poll's whole history is the place a per-row existence check
    becomes visible.
    """
    models = {
        model._meta.model_name: model
        for config in apps.get_app_configs()
        if config.label in _REFERENCED_APPS
        for model in config.get_models()
    }

    wanted: dict[str, set[str]] = {}
    for event in page:
        model_name, _sep, pk = event.object_ref.partition(":")
        if model_name not in models:
            continue
        try:
            uuid.UUID(pk)
        except ValueError:
            # Not a reference this screen can resolve; rendered as-is.
            continue
        wanted.setdefault(model_name, set()).add(pk)

    alive: dict[str, bool] = {}
    for model_name, pks in wanted.items():
        # ``_default_manager`` rather than ``objects``: this reaches the models
        # through the app registry, where the static type is only ``Model``.
        manager = models[model_name]._default_manager
        rows = manager.filter(pk__in=pks).values_list("pk", flat=True)
        found = {str(pk) for pk in rows}
        for pk in pks:
            alive[f"{model_name}:{pk}"] = pk in found
    return alive


def as_json(payload: dict[str, Any]) -> str:
    """An event's ``before``/``after`` as the screen shows it.

    Keys sorted so two events of the same kind line up down the column, and an
    empty payload renders as nothing rather than as ``{}``.
    """
    return json.dumps(payload, ensure_ascii=False, sort_keys=True) if payload else ""
