# SPDX-License-Identifier: 0BSD
"""Reminder 48 h before ``closes_at`` (R-5.7).

State-based, not time-triggered (§14): it selects everyone who is *due* a
reminder and has not had one, rather than acting because it happens to be
T−48 h. cron has no catch-up for missed runs, so a host that was down sends late
rather than not at all — once each (T-37, T-49).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.core.jobs import JobCommand
from apps.core.models import JobRun
from apps.elections.models import PollState
from apps.registrations import mail
from apps.registrations.models import Channel, Registration, RegistrationState

logger = logging.getLogger("polls.jobs")
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
        if options.get("dry_run"):
            run.detail = {"due": due.count(), "sent": 0, "dry_run": True}
            self.stdout.write(f"{due.count()} reminders due (dry run)")
            return

        sent = 0
        failed = 0
        for registration in due.select_related("poll").iterator():
            # Stamped in the same transaction as the send, and one registration
            # at a time: a crash mid-run leaves the ones already sent stamped,
            # so the next invocation sends the remainder and nobody is reminded
            # twice (T-37, T-49). One bad address costs one reminder, not the run.
            #
            # The stamp is written *before* the send, not after: SMTP has no
            # transaction of its own, so the only way to guarantee "stamped
            # implies sent, and unsent implies unstamped" is to let a send
            # failure unwind the stamp via this block's own rollback. The
            # reverse order (send, then stamp) left a real gap — a `.save()`
            # failing after a genuinely delivered reminder recorded nothing,
            # so the next run resent it to the same address.
            try:
                with transaction.atomic():
                    registration.reminder_sent_at = timezone.now()
                    registration.save(update_fields=["reminder_sent_at"])
                    mail.send_reminder(registration)
            except Exception:
                failed += 1
                logger.exception("reminder failed for registration %s", registration.pk)
            else:
                sent += 1

        run.detail = {"due": sent + failed, "sent": sent, "failed": failed}
        self.stdout.write(f"{sent} reminders sent, {failed} failed")
        if failed:
            self.stderr.write(f"{failed} reminders could not be sent")
