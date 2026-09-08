# SPDX-License-Identifier: 0BSD
"""Turning a token in a URL into a session (§6.3, MUST).

§6.3 requires four things of every route a token arrives on, and §7's claim
that the token never reaches a log is false the moment any one of them is
missing:

1. the server exchanges the token for a session and redirects to a token-free
   URL, so it is not resent on subsequent requests;
2. the response carries ``Referrer-Policy: no-referrer``, so the token in the
   address bar does not travel to whatever the page links to;
3. it carries ``Cache-Control: no-store``, so a shared browser does not keep it;
4. nginx suppresses request-URI logging for the path prefix — configuration,
   not code, and named in ``ansible/roles/polls/tasks/provision.yml``.

**What the session holds is a registration id, not the token.** §7 says the
plaintext token is never persisted anywhere, and Django's default session
backend is a database table: storing the token there would persist it, in the
database, on every confirmation. The id is enough for what §6.2 needs — this
browser has proven control of the mailbox that registration was sent to — and
it is not a secret.

Open question for §6.3, recorded here so it is met deliberately rather than
discovered: modifying a ballot needs ``ballot_hash``, which needs the token. A
session holding both a registration id and a ballot hash would be a join
between a voter and their ballot for as long as the session lives, which is
INV-1. Resolving that is part of §6.3 and is not settled here.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse

#: One entry per poll, so a voter registered in two concurrent polls (T-12) does
#: not have one confirmation displace the other.
_PREFIX = "voter:"


def _key(poll_id: str) -> str:
    return f"{_PREFIX}{poll_id}"


def store(request: HttpRequest, poll_id: str, registration_id: str) -> None:
    """Record that this browser presented a valid token for this poll.

    ``cycle_key`` because the identity attached to the session has just changed:
    a session id handed out before the token was presented must not become one
    that carries the confirmation (session fixation).
    """
    request.session.cycle_key()
    request.session[_key(poll_id)] = registration_id


def load(request: HttpRequest, poll_id: str) -> str | None:
    """The registration this browser has proven itself for, if any."""
    value = request.session.get(_key(poll_id))
    return str(value) if value else None


def clear(request: HttpRequest, poll_id: str) -> None:
    request.session.pop(_key(poll_id), None)


def protect(response: HttpResponse) -> HttpResponse:
    """Points 2 and 3, applied to every response on a token route.

    ``SECURE_REFERRER_POLICY`` is ``same-origin`` site-wide, which is right for
    the rest of the site and not enough here: an external link on a page whose
    URL holds a token would carry it in the ``Referer``.
    """
    response["Referrer-Policy"] = "no-referrer"
    response["Cache-Control"] = "no-store"
    return response
