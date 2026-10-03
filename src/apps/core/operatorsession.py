# SPDX-License-Identifier: 0BSD
"""Back-office sessions end after ``OPERATOR_SESSION_AGE`` (review A-16).

An operator's session opens the screens that show who has voted and every
paper ballot beside its elector, and a mairie's PC is often shared. Django's
default would keep a browser signed in for two weeks.

The limit is absolute, counted from sign-in, and enforced here on the server,
not by the cookie alone: ``sessions.SessionStore`` rounds every stored expiry
up to midnight (INV-1, decision log #42), so the session row outlives the
cookie by up to a day, and a copied cookie would outlive it too. The deadline
is written into the session at sign-in, by signal so that every way of signing
in sets it (the form and the first-run wizard), and this middleware signs out
any request past it, or from a session signed in before it existed.

Voters never sign in, so their sessions keep ``SESSION_COOKIE_AGE``.

**An operator is also an elector.** A ballot route stores a ballot hash or a
receipt in the session (``tokensession``), and an operator's session holds
their account id: the two together would tie a named person to their ballot
(INV-1). So the two never share a session, whichever comes first. A ballot
route reached by a signed-in session signs it out before the view runs, and
the ballot keys then go into a fresh session; signing in drops any ballot keys
the browser already held.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.http import HttpRequest, HttpResponse
from django.utils.translation import gettext as _

from . import tokensession

#: Unix time, in whole seconds, after which the session no longer signs anyone in.
DEADLINE_KEY = "operator_session_until"


@receiver(user_logged_in)
def start_operator_session(sender: Any, request: HttpRequest | None, **kwargs: Any) -> None:
    """Give a session that has just signed in its deadline and a cookie to match."""
    if request is None:
        return
    age: int = settings.OPERATOR_SESSION_AGE
    request.session.set_expiry(age)
    request.session[DEADLINE_KEY] = int(time.time()) + age
    tokensession.forget_all(request.session)


class OperatorSessionMiddleware:
    """Signs out a session past its deadline, or one that reaches a ballot
    route, before any view sees it."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """The response, the request signed out first if its time is up."""
        if request.user.is_authenticated:
            deadline = request.session.get(DEADLINE_KEY)
            if not isinstance(deadline, int) or time.time() >= deadline:
                logout(request)
        return self.get_response(request)

    def process_view(self, request: HttpRequest, view_func: Callable[..., Any], *args: Any) -> None:
        """A ballot route never runs in a signed-in session (module docstring).

        Keyed on the URL namespace, not a list of views, so a ballot route
        added later is covered without anyone having to remember it.
        """
        match = request.resolver_match
        if match is not None and match.namespace == "ballots" and request.user.is_authenticated:
            logout(request)
            messages.info(
                request,
                _(
                    "Vous avez été déconnecté de l'espace mairie : un vote ne se fait "
                    "jamais depuis une session d'agent."
                ),
            )
