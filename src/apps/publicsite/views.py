# SPDX-License-Identifier: 0BSD
"""Public pages (§6.6) and the health endpoint (§14)."""

from __future__ import annotations

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render

from apps.elections.models import Poll, PollState


def health(request: HttpRequest) -> JsonResponse:
    """``GET /sante`` (§14).

    200 with the application version and whether migrations are pending. No
    authentication, no personal data, no counts — it is read by the Ansible
    smoke play and by monitoring, both of which are outside the trust boundary.
    """
    executor = MigrationExecutor(connection)
    pending = bool(executor.migration_plan(executor.loader.graph.leaf_nodes()))
    return JsonResponse({"version": settings.APP_VERSION, "migrations_pending": pending})


def poll_list(request: HttpRequest) -> HttpResponse:
    """INV-8: sandbox polls never appear in public listings (T-15)."""
    polls = Poll.objects.filter(is_sandbox=False).exclude(state=PollState.DRAFT)
    return render(request, "publicsite/poll_list.html", {"polls": polls})


def poll_detail(request: HttpRequest, poll_id: str) -> HttpResponse:
    """The public poll page (§6.6).

    Shows the propositions, the closing instant, the paper keying deadline
    where one is configured, any logged extension (R-3.4) and the
    consultative-status notice (R-1.4). Participation figures appear only if
    ``show_live_participation`` is set; when it is off no page, endpoint or
    header exposes a running count (T-20), which is why nothing is counted here.
    """
    poll = get_object_or_404(Poll.objects.filter(is_sandbox=False), pk=poll_id)
    return render(request, "publicsite/poll_detail.html", {"poll": poll})


def results(request: HttpRequest, poll_id: str) -> HttpResponse:
    """The artefacts of §9, once the poll is ``published``."""
    poll = get_object_or_404(
        Poll.objects.filter(is_sandbox=False, state=PollState.PUBLISHED), pk=poll_id
    )
    return render(request, "publicsite/results.html", {"poll": poll})
