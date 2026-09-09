# SPDX-License-Identifier: 0BSD
"""Token handling on the ballot routes (§6.3, R-7.4 ter, MUST).

R-7.4 ter requires four things of every route the token arrives on, and §7's
claim that the token never reaches a log is false the moment one is missing:

1. the token is exchanged on use and the voter ends on a URL that does not
   contain it, so it is not resent on later requests;
2. the response carries ``Referrer-Policy: no-referrer``, so the token in the
   address bar does not travel to whatever the page links to;
3. it carries ``Cache-Control: no-store``, so a shared browser does not keep it;
4. nginx suppresses request-URI logging for the path prefix — configuration,
   not code, and named in ``ansible/roles/polls/tasks/provision.yml``.

**The open question of §6.3 is settled here.** Modifying a ballot needs
``ballot_hash``, which needs the token; a session holding a registration id
*and* a ballot hash would join a voter to their ballot for the session's life
(INV-1). The resolution has two halves:

- **Nothing in the session identifies a voter.** Retiring the standalone
  mailbox-confirmation route removed the only writer of a registration id to the
  session. One link now both confirms the mailbox and opens the ballot, and it
  stores no voter reference anywhere.
- **First cast keeps the token in the URL, not the session.** The cast form is
  served from and posted to the token URL; the cast completes in that request —
  which alone holds the token, transiently — and then redirects to a token-free
  receipt. The token is never written to the session table.
- **Modification carries only ``ballot_hash``.** Following the modification link
  exchanges the token for a session entry holding the ballot hash and nothing
  else — an opaque pointer to a ballot row, with no voter identifier beside it
  in the session — then redirects to a token-free URL (T-21). ``modify`` works
  from that hash and never sees the token again.

``SESSION`` keys are per poll, so a voter registered in two concurrent polls
(T-12) does not have one flow displace the other.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest, HttpResponse

_BALLOT_PREFIX = "ballot:"
_RECEIPT_PREFIX = "receipt:"


def _ballot_key(poll_id: str) -> str:
    return f"{_BALLOT_PREFIX}{poll_id}"


def _receipt_key(poll_id: str) -> str:
    return f"{_RECEIPT_PREFIX}{poll_id}"


def store_ballot(request: HttpRequest, poll_id: str, ballot_hash_hex: str) -> None:
    """Record that this browser presented a token whose ballot is this one.

    Only the hash is stored — never the token, never a registration id. There is
    deliberately no voter reference anywhere in the session to pair it with
    (INV-1). ``cycle_key`` because the browser's access has just changed: a
    session id handed out before the token was presented must not become one
    that can edit a ballot (session fixation).
    """
    request.session.cycle_key()
    request.session[_ballot_key(poll_id)] = ballot_hash_hex


def load_ballot(request: HttpRequest, poll_id: str) -> str | None:
    """The ballot hash this browser proved a token for, if any."""
    value = request.session.get(_ballot_key(poll_id))
    return str(value) if value else None


def clear_ballot(request: HttpRequest, poll_id: str) -> None:
    request.session.pop(_ballot_key(poll_id), None)


def store_receipt(request: HttpRequest, poll_id: str, receipt: dict[str, Any]) -> None:
    """Stash the just-recorded ranking and tracking code for the receipt page
    (§6.3, R-6.4).

    Ballot content only — a tracking code that is published anyway (§9) and a
    ranking. No voter identifier, so this is not a join; it is kept in the
    session merely so the summary survives the redirect off the token URL.
    """
    request.session[_receipt_key(poll_id)] = receipt


def load_receipt(request: HttpRequest, poll_id: str) -> dict[str, Any] | None:
    value = request.session.get(_receipt_key(poll_id))
    return value if isinstance(value, dict) else None


def protect(response: HttpResponse) -> HttpResponse:
    """Points 2 and 3, applied to every response on a token or ballot route.

    ``SECURE_REFERRER_POLICY`` is ``same-origin`` site-wide, which is right for
    the rest of the site and not enough here: an external link on a page whose
    URL holds a token would carry it in the ``Referer``.
    """
    response["Referrer-Policy"] = "no-referrer"
    response["Cache-Control"] = "no-store"
    return response
