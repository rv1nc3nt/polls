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

# Keys that may never appear in ``before``/``after``, at any depth. The scan of
# T-55 is the real check; this is the cheap one that catches a mistake at write
# time. ``object_ref`` is here too: the dedicated ``object_ref`` column is the
# only legitimate carrier of a row reference, so the same word turning up
# *inside* a payload — as screen 8's own filters do, nesting the operator's
# free-text search box under this key — is always a mistake, not a reference.
FORBIDDEN_KEYS = frozenset(
    {
        "name",
        "last_name",
        "first_names",
        "birth_name",
        "usual_name",
        "declared_last_name",
        "declared_first_names",
        "declared_dob",
        "date_of_birth",
        "email",
        "email_canonical",
        "review_reason",
        "object_ref",
    }
)


class PersonalDataInAuditEvent(ValueError):
    """Raised when an event would carry an elector's identity (§10)."""


class UnknownAuditReason(ValueError):
    """Raised when ``reason`` is not a ``Reason`` code — prose, most likely,
    which could carry a name the log would then keep for ever (§10)."""


def _offending_keys(value: Any) -> set[str]:
    """``FORBIDDEN_KEYS`` found anywhere under ``value``, however deeply nested.

    A top-level scan misses exactly the shape screen 8 produces: free text
    nested one level down, under an innocuous key such as ``filters``.
    """
    if isinstance(value, dict):
        found: set[str] = set(FORBIDDEN_KEYS & value.keys())
        for nested in value.values():
            found |= _offending_keys(nested)
        return found
    if isinstance(value, (list, tuple)):
        found = set()
        for item in value:
            found |= _offending_keys(item)
        return found
    return set()


def _check(payload: dict[str, Any], field: str) -> None:
    offending = _offending_keys(payload)
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
    operator writes goes on the referenced object (§10). A plain ``str`` is
    accepted — a form hands back the code's value — but must be one of
    ``Reason``'s; anything else raises ``UnknownAuditReason`` before a row is
    written (review note L2).

    Raises ``PersonalDataInAuditEvent`` if ``before`` or ``after`` carries a
    ``FORBIDDEN_KEYS`` key at any depth. Writes inside the caller's
    transaction, so an event recorded before a rollback is lost with it (see
    ``elections.transitions.open_poll`` for refusals logged after one).
    ``actor_label`` defaults to ``"system"`` when there is no ``actor``.
    """
    if reason and reason not in Reason.values:
        raise UnknownAuditReason(str(reason))
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
