# SPDX-License-Identifier: 0BSD
"""Run the tally for a closed poll (§8).

Operator-triggered from the back-office (§6.5 screen 9); this command exists so
the same work is runnable, observable and testable from a terminal. The tally
is a pure function of the live ballot set and gains nothing from running early,
which is why closure does not run it.
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.elections.closure import publication
from apps.elections.models import Poll, PollState


class Command(BaseCommand):
    help = "Dépouille un scrutin clos et écrit les artefacts de publication."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("poll_id")

    def handle(self, *args: Any, **options: Any) -> None:
        poll = Poll.objects.filter(pk=options["poll_id"]).first()
        if poll is None:
            raise CommandError("scrutin introuvable")
        if poll.state not in (PollState.CLOSED, PollState.PUBLISHED):
            raise CommandError("le scrutin doit être clos")
        self.stdout.write(json.dumps(publication(poll), indent=2, ensure_ascii=False))
