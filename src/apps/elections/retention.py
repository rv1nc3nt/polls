# SPDX-License-Identifier: 0BSD
"""The retention purges (§11, R-13.3, R-13.3 bis).

Two purges, two anchors. A poll's frozen roll and identity data are purged two
months after **closure**, not after publication: a poll that closes and is
never published — an unresolved physical tie-break, an abandoned result — would
otherwise keep its identity data for ever. The basis for holding it ends when
the poll is over, not when somebody gets round to announcing the outcome.
Publication after a purge stays possible because §9 freezes the counts.

**A withdrawn poll (R-3.11) shares the same purge, anchored on `withdrawn_at`
where the poll never reached `closed`.** Closure and withdrawal are
alternative ends to the same thing — the poll being over — so `due_polls`
selects on whichever anchor a `withdrawn` poll actually has: `closed_at` if it
passed through `closed` on the way (whether it was later withdrawn from
`closed` itself or from `published`, in which case `closed_at` predates
`withdrawn_at` and is the earlier, correct anchor), `withdrawn_at` otherwise —
a poll pulled straight from `announced` or `open` has no `closed_at` at all,
and without this second anchor its identity data would never become due.

This module is the sole permitted writer past ``closes_at`` and the only caller
of the deletes below (§5.1). The INV-2 trigger names the exception rather than
being disabled for the job's duration: it permits ``DELETE`` on a registration
only where the poll is ``closed`` or ``published``, and INV-7's trigger does the
same for ``RollEntry``. ``closed`` and not ``published`` alone, because the
anchor is closure: a poll that closes and is never published must still purge.
``AuditEvent`` is never touched — it holds references and non-identifying state
only, so deleting the referenced rows is what anonymises the log (T-14, T-54,
T-55).

The working roll (``WorkingRollEntry``) has no poll to anchor on before one
opens, so it is purged two months after **import** instead, where no poll is
``draft`` to still consume it (R-13.3 bis, §11) — see ``working_roll_due`` and
``purge_working_roll`` below. Unlike ``RollEntry`` it carries no protecting
trigger, since ``apply_import`` already deletes it at will.

Both purges are idempotent: a re-run finds nothing left to delete and says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.models import Action, Reason
from apps.ballots.models import PaperBallotLink
from apps.registrations.models import DuplicateAttempt, Registration

from .models import Poll, PollState, RollEntry, RollImport, WorkingRollEntry

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
    purged, so a host that was down purges late rather than never.

    A ``withdrawn`` poll anchors on ``closed_at`` where it has one — set
    before the later withdrawal, so it is the earlier and correct anchor — and
    on ``withdrawn_at`` otherwise, for the poll pulled straight from
    ``announced`` or ``open`` that never acquired a ``closed_at`` at all.
    """
    now = now or timezone.now()
    threshold = now - RETENTION
    return list(
        Poll.objects.filter(
            Q(state__in=[PollState.CLOSED, PollState.PUBLISHED], closed_at__lte=threshold)
            | Q(state=PollState.WITHDRAWN, closed_at__isnull=False, closed_at__lte=threshold)
            | Q(
                state=PollState.WITHDRAWN,
                closed_at__isnull=True,
                withdrawn_at__lte=threshold,
            )
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


def working_roll_due(now: datetime | None = None) -> bool:
    """R-13.3 bis: is the working roll due for purge?

    Anchored on the latest import, not on any poll's closure — there is no
    poll to anchor on before one opens, and this purge exists precisely for
    the roll no poll ever did. "In use" means a poll currently ``draft`` **or**
    ``announced`` (R-3.10): both still read ``WorkingRollEntry`` at ``open``
    (§3.2, §4) — announcing early is a detour, not a different destination —
    while an ``open``, ``closed`` or ``published`` poll already holds its own
    frozen ``RollEntry`` copy and never looks at the working roll again, so its
    existence does not postpone this purge.
    """
    now = now or timezone.now()
    latest = RollImport.objects.order_by("-imported_at").first()
    if latest is None or latest.imported_at > now - RETENTION:
        return False
    return not Poll.objects.filter(state__in=(PollState.DRAFT, PollState.ANNOUNCED)).exists()


@transaction.atomic
def purge_working_roll() -> int:
    """Delete ``WorkingRollEntry`` where due (R-13.3 bis). Idempotent: a
    re-run, or a call while not due, finds nothing to delete and logs nothing.

    ``RollImport`` (filename, hash, row count, operator, date) is provenance,
    not identity data, and is left alone — the same distinction the per-poll
    purge draws between ``RollEntry`` and ``AuditEvent`` (§10, §11).
    """
    if not working_roll_due():
        return 0
    deleted = WorkingRollEntry.objects.all().delete()[0]
    if deleted:
        latest = RollImport.objects.order_by("-imported_at").first()
        audit.record(
            action=Action.WORKING_ROLL_PURGED,
            object_ref=audit.ref(latest) if latest is not None else "",
            after={"working_roll_entries": deleted},
            reason=Reason.DEADLINE_REACHED,
        )
    return deleted
