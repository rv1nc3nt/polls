# SPDX-License-Identifier: 0BSD
"""``open → closed`` at ``paper_entry_deadline`` (§4).

The deadline, not ``closes_at``: online voting stops at ``closes_at`` on the
write path regardless, while keying and countersignature continue to the
deadline (§6.4). A ballot still ``pending_countersign`` blocks the transition —
the command refuses, leaves the poll ``open``, logs the blocker and exits
non-zero (T-57). That is safe rather than dangerous: the window checks already
refuse every ballot write past the deadline whatever the state says, so the poll
is closed in substance while the state field waits for the countersignatures, or
for the admin's override, which carries a mandatory reason and cannot be
automated.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from apps.core.jobs import EXIT_REFUSED, JobCommand
from apps.core.models import JobRun
from apps.elections.models import Poll, PollState
from apps.elections.transitions import TransitionRefused, close_poll


class Command(JobCommand):
    help = "Clôt les scrutins dont l'échéance de saisie est atteinte."
    job_name = "close_poll"

    def handle_job(self, run: JobRun, **options: Any) -> None:
        due = Poll.objects.filter(state=PollState.OPEN, paper_entry_deadline__lte=timezone.now())
        closed, refused = [], []
        for poll in due:
            if options.get("dry_run"):
                self.stdout.write(f"would close {poll.id}")
                continue
            try:
                close_poll(poll, actor=None)
            except TransitionRefused as exc:
                refused.append({"poll": str(poll.id), "blockers": exc.blockers})
                self.stderr.write(f"REFUSED {poll.id}: {', '.join(exc.blockers)}")
            else:
                closed.append(str(poll.id))
                self.stdout.write(f"closed {poll.id}")
        run.detail = {"closed": closed, "refused": refused}
        if refused:
            run.succeeded = False
            raise SystemExit(EXIT_REFUSED)
