# SPDX-License-Identifier: 0BSD
"""The retention purge (§11, R-13.3).

Two months after **closure**, not after publication: a poll that closes and is
never published — an unresolved physical tie-break, an abandoned result — would
otherwise keep its identity data for ever. The basis for holding it ends when
the poll is over, not when somebody gets round to announcing the outcome.
Publication after a purge stays possible because §9 freezes the counts.

This module is the sole permitted writer past ``closes_at`` and the only caller
of the deletes below (§5.1). The INV-2 trigger names the exception rather than
being disabled for the job's duration: it permits ``DELETE`` on a registration
only where the poll is ``closed`` or ``published``, and INV-7's trigger does the
same for ``RollEntry``. ``closed`` and not ``published`` alone, because the
anchor is closure: a poll that closes and is never published must still purge.
``AuditEvent`` is never touched — it holds references and non-identifying state
only, so deleting the referenced rows is what anonymises the log (T-14, T-54,
T-55).

Idempotent: a re-run finds nothing left to delete and says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.models import Action, Reason
from apps.ballots.models import PaperBallotLink
from apps.registrations.models import DuplicateAttempt, Registration

from .models import Poll, PollState, RollEntry

RETENTION = timedelta(days=61)


@dataclass(frozen=True)
class PurgeReport:
    poll_id: str
    registrations: int
    roll_entries: int
    paper_links: int
    duplicate_attempts: int


def due_polls(now: datetime | None = None) -> list[Poll]:
    """State-based selection (§14): everything past its anchor and not yet
    purged, so a host that was down purges late rather than never."""
    now = now or timezone.now()
    return list(
        Poll.objects.filter(
            state__in=[PollState.CLOSED, PollState.PUBLISHED],
            closed_at__lte=now - RETENTION,
        )
    )


@transaction.atomic
def purge(poll: Poll) -> PurgeReport:
    """Delete the identity data of one poll. Ballots, results and the log stay."""
    links = PaperBallotLink.objects.filter(poll=poll).delete()[0]
    attempts = DuplicateAttempt.objects.filter(poll=poll).delete()[0]
    registrations = Registration.objects.filter(poll=poll).delete()[0]
    roll_entries = RollEntry.objects.filter(poll=poll).delete()[0]

    report = PurgeReport(
        poll_id=str(poll.id),
        registrations=registrations,
        roll_entries=roll_entries,
        paper_links=links,
        duplicate_attempts=attempts,
    )
    audit.record(
        action=Action.RETENTION_PURGE,
        poll=poll,
        object_ref=audit.ref(poll),
        after={
            "registrations": registrations,
            "roll_entries": roll_entries,
            "paper_links": links,
            "duplicate_attempts": attempts,
        },
        reason=Reason.DEADLINE_REACHED,
    )
    return report
