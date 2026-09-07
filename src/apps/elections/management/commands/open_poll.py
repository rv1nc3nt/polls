# SPDX-License-Identifier: 0BSD
"""``draft → open`` at ``opens_at`` (§4).

Selection is state-based — ``state = draft AND opens_at ≤ now`` — so a host that
was down opens the poll late rather than never (T-51). A refusal is loud: the
poll stays in ``draft``, the blocking reason is logged, and the command exits
non-zero (T-53). It never opens a partially configured poll.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from apps.core.jobs import EXIT_REFUSED, JobCommand
from apps.core.models import JobRun
from apps.elections.models import Poll, PollState
from apps.elections.transitions import TransitionRefused, open_poll


class Command(JobCommand):
    help = "Ouvre les scrutins dont la date d'ouverture est atteinte."
    job_name = "open_poll"

    def handle_job(self, run: JobRun, **options: Any) -> None:
        due = Poll.objects.filter(state=PollState.DRAFT, opens_at__lte=timezone.now())
        opened, refused = [], []
        for poll in due:
            if options.get("dry_run"):
                self.stdout.write(f"would open {poll.id}")
                continue
            try:
                open_poll(poll, actor=None)
            except TransitionRefused as exc:
                refused.append({"poll": str(poll.id), "blockers": exc.blockers})
                self.stderr.write(f"REFUSED {poll.id}: {', '.join(exc.blockers)}")
            else:
                opened.append(str(poll.id))
                self.stdout.write(f"opened {poll.id}")
        run.detail = {"opened": opened, "refused": refused}
        if refused:
            run.succeeded = False
            raise SystemExit(EXIT_REFUSED)
