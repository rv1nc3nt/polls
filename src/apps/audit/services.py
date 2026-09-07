# SPDX-License-Identifier: 0BSD
"""The only writer of ``AuditEvent`` (§10).

There is no update and no delete path, here or anywhere else in the
application — INV-3 is absolute, and the trigger backs it against raw SQL.
"""

from __future__ import annotations

from typing import Any

from apps.core.models import User
from apps.elections.models import Poll

from .models import Action, AuditEvent, Reason

# Keys that may never appear in ``before``/``after``. The scan of T-55 is the
# real check; this is the cheap one that catches a mistake at write time.
FORBIDDEN_KEYS = frozenset(
    {"name", "last_name", "first_names", "nne", "email", "email_canonical", "review_reason"}
)


class PersonalDataInAuditEvent(ValueError):
    """Raised when an event would carry an elector's identity (§10)."""


def _check(payload: dict[str, Any], field: str) -> None:
    offending = FORBIDDEN_KEYS & payload.keys()
    if offending:
        raise PersonalDataInAuditEvent(
            f"{field} carries personal data: {sorted(offending)}. "
            "Audit events hold references and non-identifying state only (§10); "
            "the value belongs on the referenced row, where the purge takes it."
        )


def record(
    *,
    action: Action,
    poll: Poll | None = None,
    actor: User | None = None,
    actor_label: str = "",
    object_ref: str = "",
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: Reason | str = "",
) -> AuditEvent:
    """Append one event.

    ``reason`` is a code from the declared vocabulary, never prose: any note an
    operator writes goes on the referenced object (§10).
    """
    before = before or {}
    after = after or {}
    _check(before, "before")
    _check(after, "after")
    return AuditEvent.objects.create(
        poll=poll,
        actor=actor,
        actor_label=actor_label or ("" if actor else "system"),
        action=action,
        object_ref=object_ref,
        before=before,
        after=after,
        reason=str(reason),
    )


def ref(obj: Any) -> str:
    """``registration:<uuid>`` and friends (§10)."""
    return f"{obj._meta.model_name}:{obj.pk}"
