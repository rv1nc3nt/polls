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

What is here so far is the shell the screens hang off: sign-in for named
accounts (R-2.2) and the poll index that a signed-in operator lands on. The
gate itself is ``access.py``.

TODO(scaffold): screens 1–11 of §6.5, in that order. The dashboard comes first
because it is what names ``open_poll``'s and ``close_poll``'s blockers before
the hour they would fire (§4) — ``opening_blockers`` and ``closing_blockers``
in ``apps.elections.transitions`` already return them.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from .access import accessible_polls, is_commune_admin


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
