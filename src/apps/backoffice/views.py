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
(R-2.2) and the poll index — plus screen 1 (tableau de bord), screen 2
(configuration du scrutin), screen 3 (import de la liste électorale), screen 4
(file d'attente des inscriptions) and screen 8 (journal d'audit). The gate is
``access.py``; the read models are ``dashboard.py``, ``auditlog.py`` and
``review.py``, and the write paths are the service functions of §5.1
(``elections.config``, ``elections.rollimport``, ``registrations.services``), so
the views stay thin enough to see the gate on each one.

TODO(scaffold): screens 5–7 and 9–11 of §6.5. Each waits on the service
function it must post through (§5.1) — no view writes through the ORM directly,
so a screen cannot land before ``ballots.services`` and the closure/tally
pieces do.
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
from apps.elections import config, rollimport
from apps.elections.models import Poll, PollState, RollEntry
from apps.elections.transitions import TransitionRefused, extend_closes_at
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
from .forms import (
    ExtensionForm,
    OptionFormSet,
    PollConfigForm,
    config_initial,
    option_drafts,
    option_initial,
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


@require_poll_role(Role.POLL_ADMIN)
def poll_config(request: HttpRequest, poll: Poll) -> HttpResponse:
    """Screen 2 — configuration du scrutin (§6.5.2).

    Editable only while ``draft`` (R-3.3); read-only thereafter, with the
    reasoned ``closes_at`` extension of R-3.4 the one change still permitted
    once the poll is ``open``. Poll admin only — configuration and closure are
    the admin's, not the entry operator's (§3.7).

    Two forms, never both live: the ``draft`` poll gets the configuration
    editor, every other state gets the read-only view (plus the extension form
    while ``open``). The POST branch follows from ``poll.state`` alone, so
    neither form needs an action discriminator.
    """
    languages = list(poll.languages) or [poll.default_language]
    on_post = request.method == "POST"

    if poll.state == PollState.DRAFT:
        form = PollConfigForm(
            request.POST or None,
            content_languages=languages,
            initial=None if on_post else config_initial(poll),
        )
        formset = OptionFormSet(
            request.POST or None,
            prefix="opt",
            form_kwargs={"content_languages": languages},
            initial=None if on_post else option_initial(poll),
        )
        if on_post and form.is_valid() and formset.is_valid():
            draft = form.to_draft(option_drafts(formset))
            try:
                config.save_configuration(poll, draft, actor=current_operator(request))
            except config.ConfigurationLocked as locked:
                messages.error(request, str(locked))
            else:
                messages.success(request, _("Configuration enregistrée."))
                return redirect("backoffice:poll_config", poll_id=str(poll.pk))
        return render(
            request,
            "backoffice/poll_config.html",
            {"poll": poll, "editable": True, "form": form, "formset": formset},
        )

    extension = ExtensionForm(request.POST or None) if poll.state == PollState.OPEN else None
    if on_post and extension is not None and extension.is_valid():
        try:
            extend_closes_at(
                poll,
                extension.cleaned_data["new_closes_at"],
                current_operator(request),
                extension.cleaned_data["reason"],
            )
        except TransitionRefused as refused:
            messages.error(request, str(refused))
        else:
            messages.success(request, _("Date de clôture repoussée."))
            return redirect("backoffice:poll_config", poll_id=str(poll.pk))

    return render(
        request,
        "backoffice/poll_config.html",
        {
            "poll": poll,
            "editable": False,
            "options": poll.options.all(),
            "extension": extension,
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
            # R-5.4: the admin picks the roll entry to bind; it must belong to
            # this poll's snapshot. A missing or foreign id is left as None and
            # ``approve`` refuses with the reason why.
            roll_entry = RollEntry.objects.filter(
                poll=poll, pk=request.POST.get("roll_entry", "")
            ).first()
            if not reason:
                messages.error(request, _("Un motif est obligatoire pour accepter."))
            elif roll_entry is None:
                messages.error(
                    request, _("Choisissez l'entrée de la liste électorale à rattacher.")
                )
            else:
                registration, token = registrations.approve(
                    registration,
                    roll_entry,
                    reason=reason,
                    actor=current_operator(request),
                    note=note,
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


# --- Screen 3: import de la liste électorale (§6.5.3, §6.1) -----------------

#: The parsed file, held between the upload step and the review step. Keyed to
#: the session rather than the poll: ``WorkingRollEntry`` is commune-wide
#: (§3.2), so an in-progress import is not "this poll's" import even though the
#: screen that started it is scoped to one.
_ROLL_DRAFT_SESSION_KEY = "roll_import_draft"


@require_poll_role(Role.POLL_ADMIN)
def roll_import(request: HttpRequest, poll: Poll) -> HttpResponse:
    """Screen 3, step 1 — upload (§6.1, §6.5.3).

    Accepts the file, parses it, and stores the parsed table in the session for
    the review step. Nothing is written yet: a bad file is caught here, before
    anything durable exists to clean up.
    """
    error = ""
    if request.method == "POST":
        upload = request.FILES.get("file")
        filename = upload.name if upload else None
        if upload is None or not filename:
            error = _("Choisissez un fichier.")
        else:
            data = upload.read()
            try:
                table = rollimport.read_table(data, filename)
            except rollimport.UnreadableFile as exc:
                error = str(exc)
            else:
                request.session[_ROLL_DRAFT_SESSION_KEY] = {
                    "filename": filename,
                    "sha256": rollimport.file_digest(data),
                    "headers": table.headers,
                    "rows": table.rows,
                }
                return redirect("backoffice:roll_import_review", poll_id=str(poll.pk))

    return render(request, "backoffice/roll_import.html", {"poll": poll, "error": error})


@require_poll_role(Role.POLL_ADMIN)
def roll_import_review(request: HttpRequest, poll: Poll) -> HttpResponse:
    """Screen 3, steps 2–5 — column mapping, validation report, preview,
    explicit confirmation (§6.1, R-4.5), all on one page.

    The mapping lives in the form, not the session: resubmitting with a
    different choice re-runs the mapping and the report immediately, so
    correcting a wrong guess costs one click, not a restart. Only the parsed
    table — the part that is expensive to redo — is kept in the session.
    """
    draft = request.session.get(_ROLL_DRAFT_SESSION_KEY)
    if draft is None:
        messages.error(request, _("Aucun import en cours. Recommencez."))
        return redirect("backoffice:roll_import", poll_id=str(poll.pk))

    table = rollimport.Table(headers=draft["headers"], rows=draft["rows"])
    guessed = rollimport.guess_mapping(table.headers)
    mapping = {
        name: request.POST.get(f"col_{name}", guessed.get(name, "")) for name in rollimport.FIELDS
    }
    mapping = {name: header for name, header in mapping.items() if header}

    context: dict[str, object] = {
        "poll": poll,
        "filename": draft["filename"],
        "headers": table.headers,
        # Paired here rather than looked up in the template by a variable key,
        # which Django's template language cannot do (the audit log hit the
        # same limit — see ``auditlog.resolve_refs``'s caller).
        "fields": [
            {"name": name, "label": label, "selected": mapping.get(name, "")}
            for name, label in ((n, rollimport.FIELD_LABELS[n]) for n in rollimport.FIELDS)
        ],
        "total_rows": len(table.rows),
    }

    if any(name not in mapping for name in rollimport.MANDATORY_FIELDS):
        # Step 2: a mandatory column is still unmapped — nothing to validate.
        return render(request, "backoffice/roll_import_review.html", context)

    rows = rollimport.apply_mapping(table, mapping)
    report = rollimport.validate(rows, mapping)
    entries = rollimport.collapse(rows).entries
    context["report"] = report
    context["preview"] = entries[:20]
    context["entry_count"] = len(entries)

    if request.POST.get("action") == "confirm" and not report.blocking:
        rollimport.apply_import(
            rows,
            mapping,
            filename=draft["filename"],
            file_sha256=bytes.fromhex(draft["sha256"]),
            operator=current_operator(request),
        )
        del request.session[_ROLL_DRAFT_SESSION_KEY]
        messages.success(
            request,
            _("Liste électorale importée : %(count)s inscrit(s).") % {"count": len(entries)},
        )
        return redirect("backoffice:dashboard", poll_id=str(poll.pk))

    return render(request, "backoffice/roll_import_review.html", context)
