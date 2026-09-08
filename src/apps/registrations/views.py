# SPDX-License-Identifier: 0BSD
"""The voter-facing registration pages (§6.2).

Three pages and no more: the form, the outcome, and the link from the
confirmation mail. Everything that decides anything is in ``services``; these
views validate input, apply the rate limit of R-5.8, and choose a template.

The confirmation route carries a token, so §6.3's requirements apply to it in
full — the exchange for a session, the redirect to a token-free URL, and the two
headers. ``apps.core.tokensession`` holds them in one place because the ballot
routes will need exactly the same treatment.
"""

from __future__ import annotations

from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.core import ratelimit, tokensession
from apps.core.types import Token
from apps.elections.models import Poll
from apps.elections.windows import WindowClosed

from . import mail, services
from .forms import RegistrationForm
from .models import Registration, RegistrationState


def _open_poll_or_404(poll_id: str) -> Poll:
    """INV-8: a sandbox poll is not reachable from a public URL (T-15)."""
    return get_object_or_404(Poll.objects.filter(is_sandbox=False), pk=poll_id)


def register(request: HttpRequest, poll_id: str) -> HttpResponse:
    """Steps 1–7 (§6.2). The form, and what happens when it is submitted."""
    poll = _open_poll_or_404(poll_id)
    form = RegistrationForm(request.POST or None)
    error = ""

    if request.method == "POST":
        if not ratelimit.allow("registration", request, ratelimit.registration_limit()):
            # R-5.8. Deliberately the same neutral wording as a duplicate: an
            # attacker probing NNEs learns nothing from being throttled either.
            error = str(services.NEUTRAL_REFUSAL())
        elif form.is_valid():
            try:
                return _submit(request, poll, form.cleaned_data)
            except services.RegistrationRefused as refusal:
                error = str(refusal)
            except WindowClosed as closed:
                error = str(closed)

    return render(
        request,
        "registrations/register.html",
        {"poll": poll, "form": form, "error": error},
    )


def _submit(request: HttpRequest, poll: Poll, data: dict[str, str]) -> HttpResponseRedirect:
    """Create the registration, then send the mail.

    The send is deferred until after the transaction commits: a registration
    that rolls back must not leave a delivered email pointing at a row that no
    longer exists, and the mail server is the slowest thing in the request.
    """
    registration, token = services.register(poll, data, language=request.LANGUAGE_CODE)

    if token is not None:
        transaction.on_commit(lambda: mail.send_confirmation(registration, token))

    outcome = (
        "pending_email"
        if registration.state == RegistrationState.PENDING_EMAIL
        else "pending_review"
    )
    return redirect("registrations:submitted", poll_id=str(poll.pk), outcome=outcome)


def submitted(request: HttpRequest, poll_id: str, outcome: str) -> HttpResponse:
    """The outcome page (§6.2 step 4).

    It tells the applicant what happens next, which is about their own request
    and discloses nothing about anybody else's. The two duplicate cases never
    reach here: they are refused on the form with one shared message (T-2, T-17).
    """
    poll = _open_poll_or_404(poll_id)
    if outcome not in {"pending_email", "pending_review"}:
        raise Http404
    return render(request, "registrations/submitted.html", {"poll": poll, "outcome": outcome})


def confirm(request: HttpRequest, poll_id: str, token: str) -> HttpResponse:
    """The link from the confirmation mail (§6.2 step 5, §6.3's token rules).

    Presenting the token proves control of the mailbox, which is the whole of
    the confirmation. The token is then exchanged for a session and this
    redirects to a token-free URL, so it is never sent again and never reaches a
    proxy log or a ``Referer`` (T-21).
    """
    poll = _open_poll_or_404(poll_id)
    registration = services.find_by_token(poll, Token(token))

    if registration is None:
        return tokensession.protect(
            render(
                request,
                "registrations/confirmed.html",
                {"poll": poll, "error": _("Ce lien n'est pas valide.")},
                status=404,
            )
        )

    try:
        services.confirm_mailbox(registration)
    except (services.RegistrationRefused, WindowClosed):
        # Already rejected, or the poll has closed. Handled on the landing page
        # rather than here, so the token still leaves the URL.
        pass

    tokensession.store(request, str(poll.pk), str(registration.pk))
    return tokensession.protect(
        redirect(reverse("registrations:confirmed", kwargs={"poll_id": str(poll.pk)}))
    )


def confirmed(request: HttpRequest, poll_id: str) -> HttpResponse:
    """Where the confirmation link lands, with the token gone from the URL."""
    poll = _open_poll_or_404(poll_id)
    registration_id = tokensession.load(request, str(poll.pk))
    registration = (
        Registration.objects.filter(pk=registration_id, poll=poll).first()
        if registration_id
        else None
    )
    return tokensession.protect(
        render(
            request,
            "registrations/confirmed.html",
            {"poll": poll, "registration": registration, "error": ""},
        )
    )
