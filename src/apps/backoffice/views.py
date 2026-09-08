# SPDX-License-Identifier: 0BSD
"""The espace mairie (§6.5).

Purpose-built, not Django admin, which is not routed in production at all
(§14). Eleven screens, all scoped to a poll and gated by the per-poll roles of
§3.7; this is the majority of the build and is scheduled first, before the
tally, the verifier and the publication artefacts.

Two rules govern every screen and are not negotiable per-view:

* every mutating screen posts through the service functions of §5.1 — no view
  writes through the ORM directly;
* no screen displays a voter's identity alongside ballot content, except the
  paper-entry screen, where the association is deliberate and logged.

Here so far: the shell the screens hang off — sign-in for named accounts
(R-2.2) and the poll index — plus screen 1 (tableau de bord) and screen 8
(journal d'audit), the two that read and never write. The gate is ``access.py``;
the read models are ``dashboard.py`` and ``auditlog.py``, so the views stay thin
enough to see the gate on each one.

TODO(scaffold): screens 2, 3, 5–7 and 9–11 of §6.5. Each waits on the service
function it must post through (§5.1) — no view writes through the ORM directly,
so a screen cannot land before ``registrations.services`` or
``ballots.services`` does.
"""

from __future__ import annotations

from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.utils.timezone import get_current_timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.audit.models import Action, Reason
from apps.core.models import Role
from apps.elections.models import Poll
from apps.elections.windows import WindowClosed
from apps.registrations import mail as registration_mail
from apps.registrations import services as registrations
from apps.registrations.models import Registration

from . import auditlog, dashboard, review
from .access import (
    accessible_polls,
    current_operator,
    is_commune_admin,
    poll_roles,
    require_poll_role,
)


class OperatorLoginView(LoginView):
    """Sign-in for named operator accounts (R-2.2).

    Django's view, its own template: there is no self-service account creation
    and no password reset by email here. Accounts are made by a commune admin
    on screen 10, or by the first-run wizard (§6.5.11).
    """

    template_name = "backoffice/login.html"


class OperatorLogoutView(LogoutView):
    """POST-only since Django 5.0, which is also what it should have been."""

    next_page = "backoffice:login"


@login_required
def poll_index(request: HttpRequest) -> HttpResponse:
    """Where a signed-in operator lands: the polls they can act on.

    Roles are per poll (§3.7), so there is no single home screen — an operator
    may hold ``entry_operator`` on one poll and nothing on the next.
    """
    return render(
        request,
        "backoffice/poll_index.html",
        {
            "polls": accessible_polls(request.user).order_by("-created_at"),
            "is_commune_admin": is_commune_admin(request.user),
        },
    )


@require_poll_role(Role.POLL_ADMIN, Role.ENTRY_OPERATOR, Role.AUDITOR)
def poll_dashboard(request: HttpRequest, poll: Poll) -> HttpResponse:
    """Screen 1 — tableau de bord (§6.5.1).

    Open to all three per-poll roles: an entry operator needs the closing
    instant and the paper deadline as much as an admin does, and none of what
    is here identifies a voter.

    The screen exists mainly for its blockers. §4 leaves ``open_poll`` and
    ``close_poll`` to a scheduler that may run late, twice, or not at all, so
    the condition that would make either refuse has to be visible before the
    hour it would fire rather than discovered at it.
    """
    return render(
        request,
        "backoffice/dashboard.html",
        {
            "poll": poll,
            "participation": dashboard.participation(poll),
            "blockers": dashboard.blockers(poll),
            "actions": dashboard.permitted_actions(poll, poll_roles(request.user, poll)),
        },
    )


def _filters(request: HttpRequest) -> auditlog.Filters:
    """Screen 8's query string, parsed leniently.

    A malformed date filters nothing rather than erroring: this is a read-only
    log an auditor is browsing, and a 400 on a hand-edited URL helps nobody.
    """
    tz = get_current_timezone()

    def instant(name: str) -> datetime | None:
        raw = request.GET.get(name, "")
        day = parse_date(raw) if raw else None
        return datetime.combine(day, datetime.min.time(), tzinfo=tz) if day else None

    date_to = instant("date_to")
    return auditlog.Filters(
        actor_id=request.GET.get("actor", ""),
        object_ref=request.GET.get("object", "").strip(),
        date_from=instant("date_from"),
        # Inclusive of the day the operator typed: they mean the whole of it.
        date_to=date_to.replace(hour=23, minute=59, second=59) if date_to else None,
    )


@require_poll_role(Role.AUDITOR, Role.POLL_ADMIN)
def audit_log(request: HttpRequest, poll: Poll) -> HttpResponse:
    """Screen 8 — journal d'audit (§6.5.8).

    Read-only, filterable by actor, date and object. INV-3 means there is no
    other kind of screen this could be: the table has no update or delete path
    in the application or the database.

    Consulting it is itself logged — §10's minimum list ends with "access to the
    log itself" — which is why this read view performs one write. The event
    records the filters, so a later reader can see what was looked at and not
    merely that somebody looked.
    """
    filters = _filters(request)
    page = Paginator(auditlog.events(poll, filters), 50).get_page(request.GET.get("page"))

    # Materialised *before* the access event below is written, and not only for
    # tidiness: ``Paginator`` caps the slice at the count it took a moment ago,
    # so a row inserted between the count and the evaluation of this lazy
    # queryset pushes the oldest event on the page out of the slice. Writing
    # the access event first would therefore hide an event from the page that
    # recorded the access. What the auditor is shown is fixed here, then logged.
    events_on_page = list(page.object_list)

    audit.record(
        action=Action.AUDIT_LOG_ACCESSED,
        poll=poll,
        actor=request.user if request.user.is_authenticated else None,
        object_ref=audit.ref(poll),
        after={"filters": filters.as_audit_payload(), "page": page.number},
    )

    # Paired here rather than looked up in the template, which cannot index a
    # dict by a variable key. ``exists`` is None where the reference names
    # nothing this screen knows how to resolve.
    alive = auditlog.resolve_refs(events_on_page)
    rows = [
        {
            "event": event,
            "exists": alive.get(event.object_ref),
            # JSON rather than Python's dict repr, which is what the template
            # would otherwise print. This is the form the value is stored in and
            # the form an auditor quoting it should be quoting (§10).
            "before": auditlog.as_json(event.before),
            "after": auditlog.as_json(event.after),
        }
        for event in events_on_page
    ]

    return render(
        request,
        "backoffice/audit_log.html",
        {
            "poll": poll,
            "page": page,
            "rows": rows,
            "filters": filters,
            "actors": auditlog.actors(poll),
        },
    )


@require_poll_role(Role.POLL_ADMIN)
def registration_queue(request: HttpRequest, poll: Poll) -> HttpResponse:
    """Screen 4 — file d'attente des inscriptions (§6.5.4).

    Registrations that could not be matched automatically, each beside the roll
    entries an agent should compare them against. Poll admin only: this is where
    an elector's identity is read, and R-5.4 makes the decision an
    administrative one.
    """
    queue = review.pending(poll)
    return render(
        request,
        "backoffice/registration_queue.html",
        {
            "poll": poll,
            "rows": [
                {"registration": registration, "matches": review.near_matches(registration)}
                for registration in queue
            ],
            "approval_reasons": review.choices(review.APPROVAL_REASONS),
            "refusal_reasons": review.choices(review.REFUSAL_REASONS),
        },
    )


@require_poll_role(Role.POLL_ADMIN)
def registration_decide(request: HttpRequest, poll: Poll) -> HttpResponse:
    """Accept or reject one pending registration, with a mandatory reason.

    Posts through ``registrations.services`` and writes nothing itself (§6.5).
    Approval mints the token and mails it — never straight to ``active``, since
    the mailbox is confirmed in every path (§6.2 step 5, T-18).
    """
    if request.method != "POST":
        return redirect("backoffice:registration_queue", poll_id=str(poll.pk))

    registration = get_object_or_404(
        Registration, pk=request.POST.get("registration", ""), poll=poll
    )
    note = request.POST.get("note", "").strip()
    decision = request.POST.get("decision", "")

    # The vocabulary is checked against the one *this* decision offers, not
    # against every Reason there is: a refusal logged as "bulletin en double"
    # would be a valid code and a false record (§10).
    def _reason(field: str, permitted: tuple[Reason, ...]) -> str:
        value = request.POST.get(field, "")
        return value if value in {str(reason) for reason in permitted} else ""

    try:
        if decision == "approve":
            reason = _reason("approve_reason", review.APPROVAL_REASONS)
            if not reason:
                messages.error(request, _("Un motif est obligatoire pour accepter."))
            else:
                registration, token = registrations.approve(
                    registration, reason=reason, actor=current_operator(request), note=note
                )
                transaction.on_commit(
                    lambda: registration_mail.send_confirmation(registration, token)
                )
                messages.success(request, _("Inscription acceptée : le lien de vote a été envoyé."))
        elif decision == "reject":
            reason = _reason("reject_reason", review.REFUSAL_REASONS)
            if not reason:
                messages.error(request, _("Un motif est obligatoire pour refuser."))
            else:
                registrations.reject(
                    registration, reason=reason, actor=current_operator(request), note=note
                )
                messages.success(request, _("Inscription refusée."))
        else:
            messages.error(request, _("Décision inconnue."))
    except (registrations.RegistrationRefused, WindowClosed) as refusal:
        messages.error(request, str(refusal))

    return redirect("backoffice:registration_queue", poll_id=str(poll.pk))
