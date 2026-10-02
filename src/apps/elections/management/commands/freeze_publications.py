# SPDX-License-Identifier: 0BSD
"""Store the artefacts of polls published before they were stored (R-10.2).

From decision log #41 on, ``publish_poll`` stores the JSON document and the
CSV as served, and they are never recomputed. A poll published earlier holds
neither; this stores what the current code computes for it — what its results
page has been serving all along — once. Idempotent, so the deploy runs it after
every ``migrate`` (ansible/roles/polls/tasks/deploy.yml).
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.elections.models import Poll, PollState
from apps.elections.transitions import freeze_legacy_publication


class Command(BaseCommand):
    help = (
        "Fige les fichiers de publication des scrutins publiés avant qu'ils soient "
        "conservés (document JSON et liste CSV)."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        pending = Poll.objects.filter(state=PollState.PUBLISHED, published_document__isnull=True)
        frozen = [str(poll.pk) for poll in pending if freeze_legacy_publication(poll)]
        for poll_id in frozen:
            self.stdout.write(f"frozen {poll_id}")
        if not frozen:
            self.stdout.write("nothing to freeze")
