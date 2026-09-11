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
(file d'attente des inscriptions), screens 5–7 (saisie, rectification et
contreseing des bulletins papier) and screen 8 (journal d'audit). The gate is
``access.py``; the read models are ``dashboard.py``, ``auditlog.py``,
``review.py`` and ``paper.py``, and the write paths are the service functions of
§5.1 (``elections.config``, ``elections.rollimport``,
``registrations.services``, ``ballots.services``), so the views stay thin enough
to see the gate on each one.

Here so far, additionally: screen 9 (clôture et publication), whose read model
is ``elections.results_view`` (shared with the public results page) and whose
write paths are ``elections.closure`` (the physical tie-break) and
``elections.transitions.publish_poll``; screen 10 (comptes et
rôles), whose read model and write path are both ``accounts.py``; screen 11
(première installation), whose write path is ``firstrun.py``; and screen 12
(paramètres de messagerie, §6.5.12), whose read model and write path are both
``mailsettings.py``. Screens 10 and 12 are commune-level — they go through
``require_commune_admin``, not ``require_poll_role``, and neither of their
views takes a ``poll`` argument, so the per-poll roles screen 10 *assigns* are
still not access to a poll's screens for the commune admin who assigns them
(§3.7). Screen 11 runs before any account exists, so it cannot use either
gate: ``require_first_run`` opens it only while no account has been created.

Here so far, additionally: "Nouveau scrutin" (§6.5, docs/spec-divergences.md
#10), the create step the numbered screens never included — commune-level
like 10 and 12, reusing screen 2's form and write path (``elections.config``)
rather than a screen of its own.
"""

from __future__ import annotations

from datetime import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, password_validation
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBase, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils.timezone import get_current_timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.audit.models import Action, Reason
from apps.ballots import services as ballots
from apps.ballots.forms import RankingForm
from apps.ballots.models import Ballot, BallotSource, BallotStatus, PaperBallotLink
from apps.ballots.ranking import BallotRefused
from apps.core.codes import format_tracking_code
from apps.core.models import PollRole, Role, User
from apps.core.types import TrackingCode
from apps.elections import closure, config, results_view, rollimport
from apps.elections.models import Poll, PollState, RollEntry, default_eligible_list_types
from apps.elections.transitions import TransitionRefused, extend_closes_at, publish_poll
from apps.elections.windows import WindowClosed
from apps.registrations import mail as registration_mail
from apps.registrations import services as registrations
from apps.registrations.models import Channel, Registration

from . import accounts, auditlog, dashboard, firstrun, mailsettings, paper, review
from .access import (
    accessible_polls,
    current_operator,
    is_commune_admin,
    poll_roles,
    require_commune_admin,
    require_first_run,
    require_poll_role,
)
from .forms import (
    ExtensionForm,
    FirstRunForm,
    GrantRoleForm,
    MailSettingsForm,
    MailTestForm,
    NewAccountForm,
    OptionFormSet,
    PollConfigForm,
    PollCreateForm,
    config_initial,
    config_warnings,
    option_drafts,
    option_initial,
)


class OperatorLoginView(LoginView):
    """Sign-in for named operator accounts (R-2.2).

    Django's view, its own template: there is no self-service account creation
    and no password reset by email here. Accounts are made by a commune admin
    on screen 10, or by the first-run wizard (§6.5.11).

    On a fresh install there is no account to sign in with, so this redirects
    to the wizard instead of showing a form nobody can pass.
    """

    template_name = "backoffice/login.html"

    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponseBase:
        if firstrun.is_open():
            return redirect("backoffice:first_run")
        return super().dispatch(request, *args, **kwargs)


class OperatorLogoutView(LogoutView):
    """POST-only since Django 5.0, which is also what it should have been."""

    next_page = "backoffice:login"


# --- Screen 11: première installation (§6.5.11) -------------------------
#
# The one screen not gated on a role or the commune-admin flag: it runs on a
# fresh database, before any account exists, so it is gated by
# ``require_first_run`` on there being no account and closes for good once the
# first one is made. It replaces ``createsuperuser`` (§14) and, like
# ``accounts.create_account``, writes no audit event — there is no operator yet
# and no ``Action`` code for installing the instance.


@require_first_run
def first_run(request: HttpRequest) -> HttpResponse:
    """Screen 11 — première installation (§6.5.11).

    Creates the commune record and the first ``commune_admin`` account so an
    adopting commune never runs ``createsuperuser`` (§14). ``require_first_run``
    keeps it reachable only while no account exists; ``firstrun.install`` is the
    writer and does both rows in one transaction. The new administrator is
    signed in on success and lands on the (empty) poll index.
    """
    form = FirstRunForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        admin = firstrun.install(
            commune_name=form.cleaned_data["commune_name"],
            data_protection_referent=form.cleaned_data["data_protection_referent"],
            data_protection_contact=form.cleaned_data["data_protection_contact"],
            username=form.cleaned_data["username"],
            full_name=form.cleaned_data["full_name"],
            raw_password=form.cleaned_data["raw_password"],
        )
        login(request, admin)
        messages.success(
            request,
            _("Installation terminée. Vous êtes connecté comme administrateur de la commune."),
        )
        return redirect("backoffice:poll_index")
    return render(request, "backoffice/first_run.html", {"form": form})


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


@require_commune_admin
def poll_create(request: HttpRequest) -> HttpResponse:
    """Screen "Nouveau scrutin" — the create step ``access.py`` names ("crée
    les scrutins", R-3.1) but that, until now, no screen offered.

    Commune-level, like screens 10 and 12: a poll being created has no
    ``poll_admin`` yet to gate on. Reuses screen 2's form and option editor —
    a poll's initial configuration is the same shape as an edit of one — plus
    ``is_sandbox`` (R-3.7), which screen 2 excludes because it is fixed here
    and nowhere else. A fresh poll has no ``languages`` yet to derive the
    content fields from, so the editor opens on the default language alone;
    adding another is the same "change the set, save, the new fields appear on
    the next load" path screen 2 already uses (`forms.PollConfigForm`).

    Creating grants the admin no role on the poll (§3.7) — the redirect lands
    on "Rôles par scrutin" for it, so that granting one, to themselves or
    anyone else, stays the separate, audited step it always is.
    """
    languages = [settings.LANGUAGE_CODE]
    on_post = request.method == "POST"
    default_initial = {
        "default_language": settings.LANGUAGE_CODE,
        "eligible_list_types": default_eligible_list_types(),
    }
    form = PollCreateForm(
        request.POST or None,
        content_languages=languages,
        initial=None if on_post else default_initial,
    )
    formset = OptionFormSet(
        request.POST or None, prefix="opt", form_kwargs={"content_languages": languages}
    )
    if on_post and form.is_valid() and formset.is_valid():
        draft = form.to_draft(option_drafts(formset))
        poll = config.create_poll(
            draft, is_sandbox=form.cleaned_data["is_sandbox"], actor=current_operator(request)
        )
        messages.success(request, _("Scrutin créé. Attribuez-vous un rôle pour y accéder."))
        return redirect(f"{reverse('backoffice:role_admin')}?scrutin={poll.pk}")
    return render(request, "backoffice/poll_create.html", {"form": form, "formset": formset})


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
            {
                "poll": poll,
                "editable": True,
                "form": form,
                "formset": formset,
                "warnings": config_warnings(poll),
            },
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
            "warnings": config_warnings(poll),
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


def _validated_reason(posted: str, permitted: tuple[Reason, ...]) -> str:
    """A reason code checked against the vocabulary *this* action offers, not
    against every ``Reason`` there is: a code that is valid but untrue on the
    decision in front of the operator is a false record (§10)."""
    return posted if posted in {str(reason) for reason in permitted} else ""


# --- Screen 5: saisie d'un bulletin papier (§6.5.5, §6.4) ------------------


@require_poll_role(Role.ENTRY_OPERATOR)
def paper_entry(request: HttpRequest, poll: Poll) -> HttpResponse:
    """Screen 5 — search the snapshot, confirm the elector, key the ranking.

    One page: a search step until a snapshot entry is chosen, then the ranking
    form. Where the elector already has a paper ballot the operator is sent to
    screen 6; where they have already voted online the screen is a dead end —
    that vote stands and cannot be replaced by a paper one (see
    ``docs/spec-divergences.md``).
    """
    if poll.state != PollState.OPEN:
        messages.error(
            request, _("La saisie des bulletins papier n'est possible que pendant le scrutin.")
        )
        return redirect("backoffice:dashboard", poll_id=str(poll.pk))

    query = (request.POST.get("q") or request.GET.get("q") or "").strip()
    chosen = request.POST.get("roll_entry", "")
    entry = RollEntry.objects.filter(poll=poll, pk=chosen).first() if chosen else None

    context: dict[str, object] = {"poll": poll, "query": query}

    if entry is None:
        context["matches"] = paper.snapshot_search(poll, query) if query else None
        return render(request, "backoffice/paper_entry.html", context)

    channel = paper.channel_state(poll, entry)
    if channel == Channel.PAPER:
        existing = paper.in_force_paper_ballot(poll, entry)
        if existing is not None:
            return redirect(
                "backoffice:paper_ballot", poll_id=str(poll.pk), ballot_id=str(existing.pk)
            )

    context.update({"entry": entry, "channel": channel})
    if channel == Channel.ONLINE:
        # Dead end: no form, no way through. The online vote is final.
        return render(request, "backoffice/paper_entry.html", context)

    submitting = request.POST.get("action") == "record"
    form = RankingForm(
        request.POST if submitting else None, poll=poll, language=request.LANGUAGE_CODE
    )
    context["form"] = form

    if submitting and form.is_valid():
        try:
            ballot = ballots.enter_paper(
                poll,
                str(entry.pk),
                form.cleaned_data["ranking"],
                str(current_operator(request).pk),
                request.LANGUAGE_CODE,
                identity_confirmed=bool(request.POST.get("identity_confirmed")),
                note=request.POST.get("note", "").strip(),
            )
        except (BallotRefused, WindowClosed) as refused:
            messages.error(request, str(refused))
        else:
            messages.success(request, _("Bulletin papier enregistré."))
            return redirect(
                "backoffice:paper_receipt", poll_id=str(poll.pk), ballot_id=str(ballot.pk)
            )

    return render(request, "backoffice/paper_entry.html", context)


@require_poll_role(Role.ENTRY_OPERATOR, Role.POLL_ADMIN)
def paper_receipt(request: HttpRequest, poll: Poll, ballot_id: str) -> HttpResponse:
    """The receipt handed to the elector (R-8.4): tracking code, the recorded
    ranking, and — where no signed form is collected — the R-8.2 bis notice that
    a paper ballot stays tied to their identity. Rendered with a print
    stylesheet; re-openable later in the poll's default language.
    """
    ballot = get_object_or_404(
        Ballot.objects.filter(poll=poll, source=BallotSource.PAPER), pk=ballot_id
    )
    link = get_object_or_404(PaperBallotLink, ballot=ballot)
    labels = paper.option_labels(poll, link.language or poll.default_language)
    return render(
        request,
        "backoffice/paper_receipt.html",
        {
            "poll": poll,
            "ballot": ballot,
            "tracking_code": format_tracking_code(TrackingCode(ballot.tracking_code)),
            "ranking_rows": [
                [labels.get(option_id, option_id) for option_id in group]
                for group in ballot.ranking
            ],
            "pending_countersign": ballot.status == BallotStatus.PENDING_COUNTERSIGN,
            "show_identity_notice": not poll.paper_requires_signed_form,
        },
    )


# --- Screen 6: rectification et suppression d'un bulletin papier (§6.5.6) ---


@require_poll_role(Role.ENTRY_OPERATOR)
def paper_ballot_list(request: HttpRequest, poll: Poll) -> HttpResponse:
    """Every paper ballot of this poll — in force, superseded, deleted, and the
    not-in-force collision records — so none is invisible (§6.5.6)."""
    links = (
        PaperBallotLink.objects.filter(poll=poll)
        .select_related("ballot", "roll_entry", "operator", "countersigned_by")
        .order_by("-created_at")
    )
    return render(request, "backoffice/paper_ballot_list.html", {"poll": poll, "links": links})


@require_poll_role(Role.ENTRY_OPERATOR)
def paper_ballot(request: HttpRequest, poll: Poll, ballot_id: str) -> HttpResponse:
    """One paper ballot beside the elector it belongs to, with the correction
    and deletion actions of R-8.5. Both take a mandatory reason; deletion also
    re-opens online voting (R-9.4). A superseded, deleted or not-in-force row is
    shown read-only.
    """
    ballot = get_object_or_404(
        Ballot.objects.filter(poll=poll, source=BallotSource.PAPER), pk=ballot_id
    )
    link = get_object_or_404(PaperBallotLink, ballot=ballot)
    editable = ballot.status in (BallotStatus.LIVE, BallotStatus.PENDING_COUNTERSIGN)
    operator_id = str(current_operator(request).pk)
    form = RankingForm(
        request.POST if request.POST.get("action") == "correct" else None,
        poll=poll,
        language=link.language or request.LANGUAGE_CODE,
    )

    if request.method == "POST" and editable:
        action = request.POST.get("action", "")
        note = request.POST.get("note", "").strip()
        try:
            if action == "correct":
                reason = _validated_reason(request.POST.get("reason", ""), paper.CORRECTION_REASONS)
                if form.is_valid() and reason:
                    new = ballots.correct_paper(
                        ballot, form.cleaned_data["ranking"], operator_id, reason, note
                    )
                    messages.success(request, _("Bulletin rectifié."))
                    return redirect(
                        "backoffice:paper_ballot", poll_id=str(poll.pk), ballot_id=str(new.pk)
                    )
                if not reason:
                    messages.error(request, _("Un motif est obligatoire pour rectifier."))
            elif action == "delete":
                reason = _validated_reason(request.POST.get("reason", ""), paper.DELETION_REASONS)
                if not reason:
                    messages.error(request, _("Un motif est obligatoire pour supprimer."))
                else:
                    ballots.delete_paper(ballot, operator_id, reason, note)
                    messages.success(
                        request,
                        _(
                            "Bulletin supprimé ; le vote en ligne redevient possible "
                            "pour cet électeur."
                        ),
                    )
                    return redirect(
                        "backoffice:paper_ballot", poll_id=str(poll.pk), ballot_id=str(ballot.pk)
                    )
        except (BallotRefused, WindowClosed) as refused:
            messages.error(request, str(refused))

    labels = paper.option_labels(poll, link.language or poll.default_language)
    return render(
        request,
        "backoffice/paper_ballot.html",
        {
            "poll": poll,
            "ballot": ballot,
            "link": link,
            "editable": editable,
            "form": form,
            "tracking_code": format_tracking_code(TrackingCode(ballot.tracking_code)),
            "ranking_rows": [
                [labels.get(option_id, option_id) for option_id in group]
                for group in ballot.ranking
            ],
            "correction_reasons": paper.choices(paper.CORRECTION_REASONS),
            "deletion_reasons": paper.choices(paper.DELETION_REASONS),
            "versions": Ballot.objects.filter(
                poll=poll, tracking_code=ballot.tracking_code
            ).order_by("version"),
        },
    )


# --- Screen 7: contreseing (§6.5.7) ---------------------------------------


@require_poll_role(Role.ENTRY_OPERATOR)
def countersign_queue(request: HttpRequest, poll: Poll) -> HttpResponse:
    """Entries awaiting a second operator (R-8.7). Present only where the poll
    is configured for countersignature; a POST validates one entry, refused for
    the operator who keyed it and outside the paper window (T-56)."""
    if not poll.paper_requires_countersign:
        raise Http404

    if request.method == "POST":
        ballot = get_object_or_404(
            Ballot.objects.filter(poll=poll, status=BallotStatus.PENDING_COUNTERSIGN),
            pk=request.POST.get("ballot", ""),
        )
        try:
            ballots.countersign(ballot, str(current_operator(request).pk))
        except (BallotRefused, WindowClosed) as refused:
            messages.error(request, str(refused))
        else:
            messages.success(request, _("Bulletin contresigné."))
        return redirect("backoffice:countersign_queue", poll_id=str(poll.pk))

    links = (
        PaperBallotLink.objects.filter(poll=poll, ballot__status=BallotStatus.PENDING_COUNTERSIGN)
        .select_related("ballot", "roll_entry", "operator")
        .order_by("created_at")
    )
    return render(request, "backoffice/countersign_queue.html", {"poll": poll, "links": links})


# --- Screen 9: clôture et publication (§6.5.9, §9) ------------------------


@require_poll_role(Role.POLL_ADMIN)
def results_publish(request: HttpRequest, poll: Poll) -> HttpResponse:
    """Screen 9 — closure hash, tally derivation, tie-break, publication (§9).

    Poll admin only: publication is the admin's, not the entry operator's
    (§3.7). No elector identity appears here — the counts are the ones frozen at
    closure (§9) and the derivation is the pure tally of §8.

    Before the poll is ``closed`` the screen only says why not and when it will
    close (the scheduled ``close_poll`` runs at ``paper_entry_deadline``, §4).
    Once ``closed`` it shows the derivation and offers, in order:

    * the ``physical`` draw entry (§8.3), where the tally reports a tie the
      computed rule does not resolve — posted through ``elections.closure``;
    * the publication action, ``transitions.publish_poll``, refused while a
      physical draw is still owed.

    ``?format=csv`` and ``?format=json`` return the R-11.2 artefacts for
    preview and for the published page to serve; they are exactly the live set
    and the §9 document, so a third party recomputes the closure hash from the
    CSV alone.
    """
    if poll.state not in (PollState.CLOSED, PollState.PUBLISHED):
        return render(
            request,
            "backoffice/results_publish.html",
            {"poll": poll, "not_closed": True, "blockers": dashboard.blockers(poll)},
        )

    fmt = request.GET.get("format")
    if fmt == "csv":
        response = HttpResponse(closure.published_csv(poll), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="bulletins-{poll.pk}.csv"'
        return response
    if fmt == "json":
        return JsonResponse(closure.publication(poll), json_dumps_params={"ensure_ascii": False})

    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "record_tiebreak":
            order = request.POST.getlist("order")
            try:
                closure.record_physical_tiebreak(poll, order, current_operator(request))
            except closure.TiebreakRefused as refused:
                messages.error(request, str(refused))
            else:
                messages.success(request, _("Résultat du tirage au sort enregistré."))
                return redirect("backoffice:results_publish", poll_id=str(poll.pk))
        elif action == "publish":
            try:
                publish_poll(poll, current_operator(request))
            except TransitionRefused as refused:
                messages.error(request, str(refused))
            else:
                messages.success(request, _("Résultats publiés."))
                return redirect("backoffice:results_publish", poll_id=str(poll.pk))
        else:
            messages.error(request, _("Action inconnue."))

    return render(
        request,
        "backoffice/results_publish.html",
        {"poll": poll, "screen9": results_view.result_view(poll)},
    )


# --- Screen 10: comptes et rôles (§6.5.10) -------------------------------
#
# Commune-level, so ``require_commune_admin`` and no ``poll`` argument — a
# ``poll`` parameter here would (rightly) trip
# ``test_every_poll_scoped_view_is_gated``. The role-assignment screen still
# works on one poll; it takes it from the query string and resolves it itself,
# gated on the flag either way (§3.7).


@require_commune_admin
def account_admin(request: HttpRequest) -> HttpResponse:
    """Screen 10, part one — the operator accounts (R-2.2, §6.5.10).

    Create a named account, reset a password, deactivate one (which ends its
    access on the next request, not just at the next login — see ``access``),
    and grant or withdraw the commune-admin flag. All of it posts through
    ``accounts``; this view chooses the branch and carries the message.
    """
    creating = request.POST.get("action") == "create"
    form = NewAccountForm(request.POST if creating else None)

    if request.method == "POST":
        operator = current_operator(request)
        action = request.POST.get("action", "")
        try:
            if creating:
                if form.is_valid():
                    accounts.create_account(
                        username=form.cleaned_data["username"],
                        full_name=form.cleaned_data["full_name"],
                        raw_password=form.cleaned_data["raw_password"],
                        is_commune_admin=form.cleaned_data["is_commune_admin"],
                    )
                    messages.success(
                        request,
                        _("Compte créé : %(name)s.") % {"name": form.cleaned_data["username"]},
                    )
                    return redirect("backoffice:account_admin")
            else:
                account = get_object_or_404(User, pk=request.POST.get("account", ""))
                if action in {"activate", "deactivate"}:
                    accounts.set_active(account, active=action == "activate", actor=operator)
                    messages.success(
                        request,
                        _("Compte réactivé.")
                        if action == "activate"
                        else _("Compte désactivé : l'accès cesse à la prochaine requête."),
                    )
                    return redirect("backoffice:account_admin")
                if action in {"promote", "demote"}:
                    accounts.set_commune_admin(account, flag=action == "promote", actor=operator)
                    messages.success(request, _("Rôle d'administration de la commune mis à jour."))
                    return redirect("backoffice:account_admin")
                if action == "set_password":
                    raw = request.POST.get("raw_password", "")
                    try:
                        password_validation.validate_password(raw, user=account)
                    except ValidationError as weak:
                        messages.error(request, " ".join(weak.messages))
                    else:
                        accounts.set_password(account, raw_password=raw, actor=operator)
                        messages.success(request, _("Mot de passe réinitialisé."))
                    return redirect("backoffice:account_admin")
                messages.error(request, _("Action inconnue."))
        except accounts.AccountActionRefused as refused:
            messages.error(request, str(refused))

    return render(
        request,
        "backoffice/account_admin.html",
        {"rows": accounts.accounts(), "form": form},
    )


@require_commune_admin
def role_admin(request: HttpRequest) -> HttpResponse:
    """Screen 10, part two — per-poll role assignment (R-2.1, §3.7, §6.5.10).

    One poll at a time, chosen from the list (``?scrutin=`` on the way back).
    Granting and revoking go through ``accounts``, which writes the
    ``ROLE_ASSIGNED`` / ``ROLE_REVOKED`` event of §10; nothing here touches the
    ORM. The commune admin doing the assigning gains no access to the poll's
    screens by it — that is the whole point of §3.7's split.
    """
    poll_id = request.POST.get("poll") or request.GET.get("scrutin") or ""
    poll = get_object_or_404(Poll, pk=poll_id) if poll_id else None
    granting = request.POST.get("action") == "grant"
    grant_form = GrantRoleForm(request.POST if granting else None)

    if request.method == "POST" and poll is not None:
        operator = current_operator(request)
        back = f"{reverse('backoffice:role_admin')}?scrutin={poll.pk}"
        try:
            if granting:
                if grant_form.is_valid():
                    accounts.grant_role(
                        poll,
                        grant_form.cleaned_data["account"],
                        grant_form.cleaned_data["role"],
                        actor=operator,
                    )
                    messages.success(request, _("Rôle attribué."))
                    return redirect(back)
            elif request.POST.get("action") == "revoke":
                grant = get_object_or_404(PollRole, pk=request.POST.get("grant", ""), poll=poll)
                accounts.revoke_role(grant, actor=operator)
                messages.success(request, _("Rôle retiré."))
                return redirect(back)
            else:
                messages.error(request, _("Action inconnue."))
        except accounts.AccountActionRefused as refused:
            messages.error(request, str(refused))

    return render(
        request,
        "backoffice/role_admin.html",
        {
            "polls": Poll.objects.order_by("-created_at"),
            "selected_poll": poll,
            "holders": accounts.role_holders(poll) if poll is not None else [],
            "grant_form": grant_form,
        },
    )


# --- Screen 12: paramètres de messagerie (§6.5.12) -------------------------
#
# Commune-level, like screen 10: ``require_commune_admin``, no ``poll``
# argument. One relay serves every poll, so this is not a per-poll setting.


@require_commune_admin
def mail_settings(request: HttpRequest) -> HttpResponse:
    """Screen 12 — the commune's SMTP relay (§6.5.12), admin-only (§3.7).

    Two actions on one screen: "save" writes the settings through
    ``mailsettings.save`` (audited, §10), and "test" sends a real message
    through whatever is already saved, so a mistyped host or a stale password
    shows up here rather than in a confirmation mail nobody received (§14).
    Testing needs settings saved first — it exercises the stored row, not the
    unsaved form, so there is never a question of which one was tested.
    """
    config = mailsettings.current()
    testing = request.method == "POST" and request.POST.get("action") == "test"
    form = MailSettingsForm(
        request.POST if request.method == "POST" and not testing else None, instance=config
    )
    test_form = MailTestForm(request.POST if testing else None)

    if request.method == "POST":
        operator = current_operator(request)
        if testing:
            if test_form.is_valid():
                if config is None or not config.host:
                    messages.error(
                        request, _("Enregistrez d'abord les paramètres avant de les tester.")
                    )
                else:
                    recipient = test_form.cleaned_data["recipient"]
                    try:
                        mailsettings.send_test(config, recipient=recipient)
                    except mailsettings.TestSendFailed as failed:
                        messages.error(
                            request, _("Échec de l'envoi : %(error)s") % {"error": str(failed)}
                        )
                    else:
                        messages.success(
                            request,
                            _("Message de test envoyé à %(to)s.") % {"to": recipient},
                        )
            return redirect("backoffice:mail_settings")
        if form.is_valid():
            draft = mailsettings.MailSettingsDraft(
                host=form.cleaned_data["host"],
                port=form.cleaned_data["port"],
                encryption=form.cleaned_data["encryption"],
                username=form.cleaned_data["username"],
                from_email=form.cleaned_data["from_email"],
                raw_password=form.cleaned_data["raw_password"],
            )
            mailsettings.save(draft, actor=operator)
            messages.success(request, _("Paramètres de messagerie enregistrés."))
            return redirect("backoffice:mail_settings")

    return render(
        request,
        "backoffice/mail_settings.html",
        {"form": form, "test_form": test_form, "config": config},
    )
