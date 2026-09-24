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

from datetime import datetime

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.models import QuerySet
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext as _

from apps.audit.models import Action, AuditEvent, Reason
from apps.core import manual
from apps.elections import closure, results_view, richtext, sandbox, windows
from apps.elections.models import Poll, PollState
from apps.registrations.models import PARTICIPATING, Channel, Registration

#: The manual documents served publicly (docs/manuel/README.md's own table):
#: the voter's guide, the independent-verifier walkthrough and the tally
#: methods explainer in full, and only the électeur-facing third of the FAQ —
#: the other two audiences (instance administrator, mairie area) answer
#: questions a visitor here never asked. Keyed by the URL slug.
_PUBLIC_DOCS: dict[str, manual.ManualDoc] = {
    "electeur": manual.ManualDoc(stem="guide-electeur"),
    "verifier": manual.ManualDoc(stem="verifier"),
    "depouillement": manual.ManualDoc(stem="methodes-de-depouillement"),
    "faq": manual.ManualDoc(stem="faq", section="C"),
}

#: The states a poll is visible to the public in at all. ``draft`` is
#: deliberately absent — a poll not yet even ``announced`` is not one anyone
#: may see (§6.6, R-3.10); ``announced`` is the early preview, config already
#: frozen (INV-6) so the page cannot change under a viewer's eyes.
_PUBLIC_STATES = (PollState.ANNOUNCED, PollState.OPEN, PollState.CLOSED, PollState.PUBLISHED)


def _public_polls() -> QuerySet[Poll]:
    """Every poll a member of the public may see at all (INV-8, §6.6)."""
    return Poll.objects.filter(is_sandbox=False, state__in=_PUBLIC_STATES)


def _status_key(poll: Poll, now: datetime) -> str:
    """ "preview" | "open" | "published" | "closed": what the public site says,
    kept independent of ``Poll.state`` past the two boundary instants (§4,
    §5.1).

    ``close_poll`` waits for ``paper_entry_deadline`` (§6.4), which sits after
    ``closes_at`` whenever a paper window is configured, and the scheduled job
    behind it may simply run late in any case — so ``state`` can read ``open``
    for a stretch after online voting has already stopped, and the window
    checks are already refusing every write (T-67, T-68). The mirror case
    exists at the open end too: ``state`` is ``open`` from the moment
    ``open_poll`` runs, which for a hand-opened poll pulls ``opens_at`` back
    to that instant (R-3.4), so the two agree from then on. A poll that
    somehow reads ``open`` ahead of ``opens_at`` anyway (T-52 forces the state
    in the database) is still refused by the window checks. Consulting the
    clock here, exactly as ``apps.elections.windows`` does for writes, keeps
    the page from telling a visitor a poll is open when nothing behind it
    would accept their vote.
    """
    if poll.state == PollState.ANNOUNCED or now < poll.opens_at:
        return "preview"
    if poll.state == PollState.OPEN and not windows.online_voting_closed(poll, now):
        return "open"
    if poll.state == PollState.PUBLISHED:
        return "published"
    return "closed"


def health(request: HttpRequest) -> JsonResponse:
    """``GET /sante`` (§14).

    200 with the application version and whether migrations are pending. No
    authentication, no personal data, no counts — it is read by the Ansible
    smoke play and by monitoring, both of which are outside the trust boundary.
    """
    executor = MigrationExecutor(connection)
    pending = bool(executor.migration_plan(executor.loader.graph.leaf_nodes()))
    return JsonResponse({"version": settings.APP_VERSION, "migrations_pending": pending})


def help_page(request: HttpRequest) -> HttpResponse:
    """The manual's public landing page (linked from every voter-facing
    page's footer, §6.6): links to the voter's guide, the independent
    verifier, the tally methods explainer and the voter FAQ, each rendered
    straight from ``docs/manuel/`` by `manual_page` below — one source of
    prose for the repository and the site, never two to keep in step by
    hand.
    """
    language = request.LANGUAGE_CODE
    rows = [
        {"slug": slug, "title": manual.read(doc, language)[0]} for slug, doc in _PUBLIC_DOCS.items()
    ]
    return render(
        request,
        "publicsite/manual_index.html",
        {"rows": rows, "breadcrumbs": [{"label": _("Aide")}]},
    )


def _public_image_base_url() -> str:
    """The prefix under which `manual_image` serves
    ``docs/manuel/captures/img/`` — derived from the URL pattern itself with
    a throwaway name, so it always matches whatever `reverse` would build for
    a real one, i18n prefix included (§3.8).
    """
    sentinel = "SENTINEL.png"
    full = reverse("publicsite:manual_image", args=[sentinel])
    return full[: -len(sentinel)]


def manual_image(request: HttpRequest, name: str) -> HttpResponse:
    """One screenshot from the voter's guide (`_PUBLIC_DOCS["electeur"]`),
    served straight off disk — the manual's images live under version
    control next to the prose they illustrate, not in `MEDIA_ROOT` (§6.6). A
    handful of small PNGs, read whole rather than streamed.
    """
    try:
        path = manual.image_path(name)
    except LookupError:
        raise Http404 from None
    return HttpResponse(path.read_bytes(), content_type="image/png")


def manual_page(request: HttpRequest, slug: str) -> HttpResponse:
    """One rendered page of the public manual (`help_page` above lists all
    four). §6.6's public-facing prose is never typed twice: this reads and
    sanitises the same ``docs/manuel/*.md`` a repository maintainer edits.
    """
    doc = _PUBLIC_DOCS.get(slug)
    if doc is None:
        raise Http404
    page = manual.render(
        doc,
        request.LANGUAGE_CODE,
        doc_links={
            "guide-electeur": reverse("publicsite:manual_page", args=["electeur"]),
            "verifier": reverse("publicsite:manual_page", args=["verifier"]),
            "methodes-de-depouillement": reverse("publicsite:manual_page", args=["depouillement"]),
        },
        image_base_url=_public_image_base_url(),
    )
    return render(
        request,
        "publicsite/manual_page.html",
        {
            "page": page,
            "breadcrumbs": [
                {"label": _("Aide"), "url": reverse("publicsite:help")},
                {"label": page.title},
            ],
        },
    )


#: The ``?statut=`` values the template's filter tags may send back, matching
#: the badge shown on each row (``_status_key``'s own return values). Anything
#: else in the query string is treated as no filter at all.
_STATUS_FILTERS = ("preview", "open", "published", "closed")


def poll_list(request: HttpRequest) -> HttpResponse:
    """INV-8: sandbox polls never appear in public listings (T-15).

    A published poll's outcome is surfaced here too, not just on its own page:
    the winner (or tie, or "no ballot retained") is recomputed with
    ``results_view.result_view`` — the same read model the results page
    itself uses — and shown beside the listing with a link into the detail
    (R-11.2, R-11.4). Shaped into plain dicts here, one per row, because the
    template cannot index ``result_view``'s dataclass by a variable poll id
    (see ``results_view``'s own docstring).

    The ``statut`` filter narrows this same list rather than the queryset: a
    row's badge is clock-gated (``_status_key``), not read off ``Poll.state``,
    so filtering has to happen after that same recomputation to stay
    consistent with what the badge shows.
    """
    language = request.LANGUAGE_CODE
    now = timezone.now()
    rows = []
    for poll in _public_polls().order_by("-opens_at"):
        outcome = None
        if poll.state == PollState.PUBLISHED:
            view = results_view.result_view(poll)
            outcome = {"winner": view.winner, "tied": view.tied}
        rows.append(
            {
                "poll": poll,
                "title": poll.title(language),
                "outcome": outcome,
                "status": _status_key(poll, now),
            }
        )
    has_polls = bool(rows)
    status = request.GET.get("statut", "")
    if status not in _STATUS_FILTERS:
        status = ""
    if status:
        rows = [row for row in rows if row["status"] == status]
    return render(
        request,
        "publicsite/poll_list.html",
        {"rows": rows, "status": status, "has_polls": has_polls},
    )


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

    ``state`` alone is not enough, the same gap divergences #14/#15 fixed for
    the rest of this page: ``state`` still reads ``open`` through the whole
    paper-keying stretch after ``closes_at``, during which online voting has
    already stopped but paper ballots keep landing. Showing a still-updating
    count there is exactly the running-turnout-during-the-vote disclosure
    R-11.5 exists to prevent, even though the online electorate itself can no
    longer act on it.
    """
    if not (
        poll.show_live_participation
        and poll.state == PollState.OPEN
        and not windows.online_voting_closed(poll)
    ):
        return None
    active = Registration.objects.filter(PARTICIPATING, poll=poll)
    online = active.filter(channel=Channel.ONLINE).count()
    paper = active.filter(channel=Channel.PAPER).count()
    confirmed = active.count()
    return {
        "voted_online": online,
        "voted_paper": paper,
        "voted_total": online + paper,
        "not_voted": confirmed - online - paper,
    }


def _draft_preview_context(poll: Poll, language: str) -> dict[str, object]:
    """Title, description and options exactly as a preview of ``poll`` shows
    them — shared by the poll admin's own internal aperçu
    (``apps.backoffice.views.poll_preview``) and the unguessable share-link
    view below (R-3.10 bis), so the two draw from one read of the poll
    rather than two independently-maintained copies.

    Deliberately narrower than ``poll_detail``'s own context: a preview has
    no extensions yet, no participation (R-11.5 applies only once open), and
    no clock-derived status — those are each caller's own concern, not
    something a still-``draft`` poll has.
    """
    title = poll.title(language)
    return {
        "title": title,
        "breadcrumbs": [{"label": title}],
        "description_html": richtext.render_poll_description(poll, language),
        "options": [
            {
                "option_id": option.option_id,
                "label": option.label(language),
                # R-3.12, §3.1 bis: optional, so this is often empty — never
                # a reason not to show the proposition itself.
                "details_html": richtext.render_option_details(option, language),
            }
            for option in poll.options.all()
        ],
        "has_paper_window": poll.paper_entry_deadline > poll.closes_at,
        # A long proposition description is clipped client-side with a
        # "Lire la suite" popup (static/js/option-details-dialog.js) rather
        # than truncated here: the full HTML always renders, so a visitor
        # with JavaScript off sees exactly the same text, unclipped.
        "option_details_preview_length": settings.OPTION_DETAILS_PREVIEW_LENGTH,
    }


def poll_preview_shared(request: HttpRequest, poll_id: str, token: str) -> HttpResponse:
    """The unguessable, unauthenticated draft preview (R-3.10 bis).

    Anyone holding the link the poll admin generated from screen 2 sees
    exactly what that admin's own internal aperçu shows — without an
    account, and without freezing anything: the page re-reads ``poll`` on
    every request, so it can and does change between two visits, exactly as
    the draft itself can (§6.6). A blank ``preview_token`` never matches a
    nonempty path segment, so a poll with no link generated 404s here just
    as a wrong token does — the two are indistinguishable, on purpose.

    Once the poll has left ``draft`` the token no longer matters for an
    ordinary poll — the real public page (or the withdrawn notice, or a 404 if
    never public) already exists and does this page's job better, so a
    still-held link redirects there instead of dying. A sandbox poll is the
    exception: it has no public page, so the link keeps serving it (R-3.7).
    """
    poll = get_object_or_404(Poll, pk=poll_id, preview_token=token)
    if poll.state == PollState.DRAFT:
        return render(
            request,
            "publicsite/poll_preview_shared.html",
            {"poll": poll, **_draft_preview_context(poll, request.LANGUAGE_CODE)},
        )
    if not poll.is_sandbox:
        return redirect("publicsite:poll_detail", poll_id=str(poll.pk))
    # R-3.7: a sandbox poll has no public page to redirect to, so its link
    # stays the way in for as long as the poll exists. It leads to the same
    # page the public would see, registration link included, and remembers in
    # the session that this browser holds the link (``sandbox.grant_link``).
    sandbox.grant_link(request.session, poll)
    if poll.state == PollState.WITHDRAWN:
        return render(
            request,
            "publicsite/poll_withdrawn.html",
            {"breadcrumbs": [{"label": _("Scrutin retiré")}]},
        )
    return _render_poll_detail(request, poll, template="publicsite/poll_sandbox.html")


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
    actually opens. ``is_preview``/``is_open``/``online_voting_closed``/
    ``is_published`` are clock-gated via ``_status_key``, not read off
    ``poll.state`` directly, for the same reason the ballot and registration
    windows are (§5.1): ``state`` can lag the clock in both directions, and
    the page must not offer a vote the write path would refuse.

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
        return render(
            request,
            "publicsite/poll_withdrawn.html",
            {"breadcrumbs": [{"label": _("Scrutin retiré")}]},
        )
    poll = get_object_or_404(_public_polls(), pk=poll_id)
    return _render_poll_detail(request, poll)


def _render_poll_detail(
    request: HttpRequest, poll: Poll, *, template: str = "publicsite/poll_detail.html"
) -> HttpResponse:
    """The poll page itself, shared by the public route and a sandbox poll's
    share link (R-3.7) so the two cannot drift apart."""
    language = request.LANGUAGE_CODE
    # ``status`` is clock-gated the same way ``apps.elections.windows`` gates
    # the write path (§5.1) — see ``_status_key``. Using ``poll.state`` alone
    # here left the page advertising "Consultation ouverte." and the
    # registration link for the whole stretch between ``closes_at`` and
    # whenever the scheduled ``close_poll`` job actually runs, which is
    # ``paper_entry_deadline`` (§6.4) at the earliest — confusing, since the
    # window checks are already refusing every online vote (T-67, T-68).
    status = _status_key(poll, timezone.now())
    return render(
        request,
        template,
        {
            "poll": poll,
            **_draft_preview_context(poll, language),
            "extensions": _extensions(poll),
            "participation": _live_participation(poll),
            "is_preview": status == "preview",
            "is_open": status == "open",
            # ``state`` is still ``open`` here — paper keying and
            # countersignature legitimately continue past ``closes_at`` — but
            # online voting itself is already refused, so the page says so
            # instead of repeating the "ouverte" banner (§6.4).
            "online_voting_closed": windows.online_voting_closed(poll),
            "is_published": status == "published",
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
        {
            "poll": poll,
            "view": results_view.result_view(poll),
            "breadcrumbs": [
                {
                    "label": poll.title(request.LANGUAGE_CODE),
                    "url": reverse("publicsite:poll_detail", args=[poll.pk]),
                },
                {"label": _("Résultats")},
            ],
        },
    )
