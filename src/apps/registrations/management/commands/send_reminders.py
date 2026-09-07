# SPDX-License-Identifier: 0BSD
"""Reminder 48 h before ``closes_at`` (R-5.7).

State-based, not time-triggered (§14): it selects everyone who is *due* a
reminder and has not had one, rather than acting because it happens to be
T−48 h. cron has no catch-up for missed runs, so a host that was down sends late
rather than not at all — once each (T-37, T-49).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

from apps.core.jobs import JobCommand
from apps.core.models import JobRun
from apps.elections.models import PollState
from apps.registrations.models import Channel, Registration, RegistrationState

LEAD = timedelta(hours=48)


class Command(JobCommand):
    help = "Envoie le rappel aux inscrits n'ayant pas voté."
    job_name = "send_reminders"

    def handle_job(self, run: JobRun, **options: Any) -> None:
        due = Registration.objects.filter(
            poll__state=PollState.OPEN,
            poll__closes_at__lte=timezone.now() + LEAD,
            state=RegistrationState.ACTIVE,
            channel=Channel.NONE,
            reminder_sent_at__isnull=True,
        )
        # TODO(scaffold): render and send using Registration.language (§3.8),
        # then stamp reminder_sent_at in the same transaction as the send so a
        # crash mid-run cannot double-send on the next invocation.
        run.detail = {"due": due.count()}
        self.stdout.write(f"{due.count()} reminders due")
