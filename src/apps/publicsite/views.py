# SPDX-License-Identifier: 0BSD
"""Public pages (§6.6, §9) and the health endpoint (§14).

Nothing here is behind a login. Two rules shape it:

* **INV-1 / R-11.5.** A running count is disclosed only where
  ``show_live_participation`` is set, and even then only from
  ``Registration.channel`` — never by counting ballots (INV-5). When the flag
  is off, no branch here counts anything: not the page, not a header, not the
  JSON (T-20).
* **§9 / R-11.4.** The results page and its CSV/JSON are exactly the live
  ballot set and the published document, so a third party recomputes the
  closure hash from the CSV alone. The shaping is
  ``elections.results_view``, shared with back-office screen 9.
"""

from __future__ import annotations

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.models import QuerySet
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.dateparse import parse_datetime

from apps.audit.models import Action, AuditEvent, Reason
from apps.elections import closure, optioncontent, results_view
from apps.elections.models import Poll, PollState
from apps.registrations.models import Channel, Registration, RegistrationState

#: The states a poll is visible to the public in at all. ``draft`` is
#: deliberately absent — a poll not yet even ``announced`` is not one anyone
#: may see (§6.6, R-3.10); ``announced`` is the early preview, config already
#: frozen (INV-6) so the page cannot change under a viewer's eyes.
_PUBLIC_STATES = (PollState.ANNOUNCED, PollState.OPEN, PollState.CLOSED, PollState.PUBLISHED)


def _public_polls() -> QuerySet[Poll]:
    """Every poll a member of the public may see at all (INV-8, §6.6)."""
    return Poll.objects.filter(is_sandbox=False, state__in=_PUBLIC_STATES)


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
    """INV-8: sandbox polls never appear in public listings (T-15).

    A published poll's outcome is surfaced here too, not just on its own page:
    the winner (or tie, or "no ballot retained") is recomputed with
    ``results_view.result_view`` — the same read model the results page
    itself uses — and shown beside the listing with a link into the detail
    (R-11.2, R-11.4). Shaped into plain dicts here, one per row, because the
    template cannot index ``result_view``'s dataclass by a variable poll id
    (see ``results_view``'s own docstring).
    """
    language = request.LANGUAGE_CODE
    rows = []
    for poll in _public_polls().order_by("-opens_at"):
        outcome = None
        if poll.state == PollState.PUBLISHED:
            view = results_view.result_view(poll)
            outcome = {"winner": view.winner, "tied": view.tied}
        rows.append({"poll": poll, "title": poll.title(language), "outcome": outcome})
    return render(request, "publicsite/poll_list.html", {"rows": rows})


def _extensions(poll: Poll) -> list[dict[str, object]]:
    """Every logged extension of ``closes_at`` (R-3.4), oldest first.

    R-3.4 requires the extension to appear on the public page. The audit event
    carries the before/after instants and a reason **code** (§10); the operator
    who made it is not shown here — the public interest is that the date moved,
    when, and why, not who keyed it.
    """
    events = AuditEvent.objects.filter(poll=poll, action=Action.POLL_CLOSES_AT_EXTENDED).order_by(
        "at"
    )
    reason_label = dict(Reason.choices)
    return [
        {
            "at": event.at,
            "old": parse_datetime(event.before.get("closes_at", "")),
            "new": parse_datetime(event.after.get("closes_at", "")),
            "reason": reason_label.get(event.reason, event.reason),
        }
        for event in events
    ]


def _live_participation(poll: Poll) -> dict[str, int] | None:
    """Turnout for an open poll, or ``None`` when it must not be shown.

    R-11.5: only where ``show_live_participation`` is set, and only while the
    poll is open — once it is closed the figures are the ones frozen at closure
    and belong to the publication, not this page. Counted from
    ``Registration.channel`` (INV-5), never from ballots, and never broken down
    further than the two channels.
    """
    if not (poll.show_live_participation and poll.state == PollState.OPEN):
        return None
    active = Registration.objects.filter(poll=poll, state=RegistrationState.ACTIVE)
    online = active.filter(channel=Channel.ONLINE).count()
    paper = active.filter(channel=Channel.PAPER).count()
    confirmed = active.count()
    return {
        "voted_online": online,
        "voted_paper": paper,
        "voted_total": online + paper,
        "not_voted": confirmed - online - paper,
    }


def poll_detail(request: HttpRequest, poll_id: str) -> HttpResponse:
    """The public poll page (§6.6).

    The propositions, the closing instant, the paper keying deadline where one
    is configured (§6.4), any logged extension (R-3.4) and the
    consultative-status notice (R-1.4, rendered by ``base.html`` on every
    page). Participation appears only through ``_live_participation``, which
    returns ``None`` unless the poll is open and configured for it (T-20). An
    ``announced`` poll (R-3.10) reaches here too; ``is_preview`` marks that
    page instead of ``is_open``, so it gets the "not yet open" notice rather
    than the registration link — nothing here is votable before the poll
    actually opens.

    A ``withdrawn`` poll (R-3.11) is deliberately not in ``_public_polls()`` —
    the listing must not name it — but its URL is not left to a plain 404
    either: someone may already hold the link. Fetched separately below and
    answered with a fixed notice carrying none of its content, exactly as
    §6.6 describes.
    """
    withdrawn = Poll.objects.filter(
        is_sandbox=False, state=PollState.WITHDRAWN, pk=poll_id
    ).exists()
    if withdrawn:
        return render(request, "publicsite/poll_withdrawn.html", {})
    poll = get_object_or_404(_public_polls(), pk=poll_id)
    language = request.LANGUAGE_CODE
    return render(
        request,
        "publicsite/poll_detail.html",
        {
            "poll": poll,
            "title": poll.title(language),
            "description": poll.description(language),
            "options": [
                {
                    "option_id": option.option_id,
                    "label": option.label(language),
                    # R-3.12, §3.1 bis: optional, so this is often empty —
                    # never a reason not to show the proposition itself.
                    "details_html": optioncontent.render_option_details(option, language),
                }
                for option in poll.options.all()
            ],
            "has_paper_window": poll.paper_entry_deadline > poll.closes_at,
            "extensions": _extensions(poll),
            "participation": _live_participation(poll),
            "is_preview": poll.state == PollState.ANNOUNCED,
            "is_open": poll.state == PollState.OPEN,
            "is_published": poll.state == PollState.PUBLISHED,
        },
    )


def results(request: HttpRequest, poll_id: str) -> HttpResponse:
    """The artefacts of §9, once the poll is ``published`` (R-11.2, R-11.4).

    ``?format=csv`` is the anonymised ballot list — exactly the live set, so
    the closure hash recomputes from it alone; ``?format=json`` is the
    publication document verbatim. Otherwise the page renders the derivation,
    the pairwise matrix, the frozen counts, the tie-break where one applies and
    the per-ordering table (R-11.3), all from ``elections.results_view``.
    """
    poll = get_object_or_404(
        Poll.objects.filter(is_sandbox=False, state=PollState.PUBLISHED), pk=poll_id
    )

    fmt = request.GET.get("format")
    if fmt == "csv":
        response = HttpResponse(closure.published_csv(poll), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="bulletins-{poll.pk}.csv"'
        return response
    if fmt == "json":
        return JsonResponse(closure.publication(poll), json_dumps_params={"ensure_ascii": False})
    if fmt is not None:
        raise Http404

    return render(
        request,
        "publicsite/results.html",
        {"poll": poll, "view": results_view.result_view(poll)},
    )
