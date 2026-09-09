# SPDX-License-Identifier: 0BSD
"""The voter-facing registration pages (§6.2).

Two pages: the form and the outcome. The link from the confirmation mail lands
on ``ballots:access`` (§6.3) — one link both confirms the mailbox and opens the
ballot — so the token rules of R-7.4 ter live with the ballot routes now.
Everything that decides anything is in ``services``; these views validate
input, apply the rate limit of R-5.8, and choose a template.
"""

from __future__ import annotations

from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render

from apps.core import ratelimit
from apps.elections.models import Poll
from apps.elections.windows import WindowClosed

from . import mail, services
from .forms import RegistrationForm
from .models import RegistrationState


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
            # attacker probing names and dates of birth learns nothing from
            # being throttled either.
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

    outcome = {
        str(RegistrationState.PENDING_EMAIL): "pending_email",
        str(RegistrationState.REJECTED): "ineligible",
    }.get(str(registration.state), "pending_review")
    return redirect("registrations:submitted", poll_id=str(poll.pk), outcome=outcome)


def submitted(request: HttpRequest, poll_id: str, outcome: str) -> HttpResponse:
    """The outcome page (§6.2 step 4).

    It tells the applicant what happens next, which is about their own request
    and discloses nothing about anybody else's. The two duplicate cases never
    reach here: they are refused on the form with one shared message (T-2, T-17).
    An ``ineligible`` outcome is R-4.7 — a single match whose electoral-list type
    confers no standing on this poll (T-61).
    """
    poll = _open_poll_or_404(poll_id)
    if outcome not in {"pending_email", "pending_review", "ineligible"}:
        raise Http404
    return render(request, "registrations/submitted.html", {"poll": poll, "outcome": outcome})
