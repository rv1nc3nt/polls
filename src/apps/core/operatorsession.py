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
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.contrib.auth import logout
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.http import HttpRequest, HttpResponse

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


class OperatorSessionMiddleware:
    """Signs out a session past its deadline, before any view sees it."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """The response, the request signed out first if its time is up."""
        if request.user.is_authenticated:
            deadline = request.session.get(DEADLINE_KEY)
            if not isinstance(deadline, int) or time.time() >= deadline:
                logout(request)
        return self.get_response(request)
