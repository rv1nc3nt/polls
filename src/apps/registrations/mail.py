# SPDX-License-Identifier: 0BSD
"""The mail §6.2 sends (steps 7 and 8).

Deliverability is the most fragile dependency in the design (§14): every online
ballot passes through the confirmation email, and mail from a small self-hosted
domain is routinely filtered. Two consequences are visible here — the messages
are plain text, which survives filtering better than HTML and is what a
screen reader wants anyway (R-14.1), and every send is a separate call so one
bad address cannot stop a run.

The confirmation mail is **the only place the plaintext token is written out**
(§7). It is passed in, never re-derived: nothing stores it, so nothing can
re-send it, and losing it is unrecoverable by anyone including administrators
(R-7.6). Where ``allow_ballot_modification`` is off the point is moot and the
message does not raise it — a voter who cannot change their ballot has nothing
to lose by losing the mail, beyond the vote they already cast.

Every message renders in ``Registration.language`` (§3.8).
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _

from apps.core.codes import format_tracking_code
from apps.core.mailbackend import default_from_email
from apps.core.types import Token, TrackingCode

from .models import Registration


def _absolute(path: str) -> str:
    """A link a mail client can follow.

    ``PUBLIC_BASE_URL`` is deployment configuration (§15): the request that
    triggered the send may be a management command with no host at all, so the
    site's own address cannot be inferred here.
    """
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}{path}"


def ballot_url(registration: Registration, token: Token) -> str:
    """The link that confirms the mailbox and opens the ballot (§6.2 step 7).

    One link does both: ``ballots:access`` moves a ``pending_email``
    registration to ``active`` and then shows the ballot, or — once the elector
    has voted and the poll permits it — the modification form. The token
    travels in the URL here; on arrival the ballot routes exchange it and
    redirect to a token-free address, so it never reaches a proxy log or a
    ``Referer`` header (§6.3, R-7.4 ter, T-21).
    """
    with translation.override(registration.language):
        path = reverse(
            "ballots:access",
            kwargs={"poll_id": str(registration.poll_id), "token": token.reveal()},
        )
    return _absolute(path)


def _ranking_lines(registration: Registration, ranking: list[list[str]]) -> list[str]:
    """The recorded ranking as ``"1. Label"`` lines, ties joined with ``" = "``
    and rendered in the registration's language (§3.8)."""
    poll = registration.poll
    labels = {
        option.option_id: (option.label(registration.language) or option.option_id)
        for option in poll.options.all()
    }
    return [
        f"{position}. " + " = ".join(labels.get(option_id, option_id) for option_id in group)
        for position, group in enumerate(ranking, start=1)
    ]


def send_ballot_receipt(
    registration: Registration, tracking_code: str, ranking: list[list[str]]
) -> int:
    """R-6.4: after an online cast, the ranking recorded and the tracking code.

    Plain text like every message here (§14). The tracking code is the voter's
    permanent handle on the ballot — it appears in the published CSV (§9) and is
    unchanged if they later modify — so the message says to keep it. It carries
    no token: modification is by the link sent at registration (R-7.1, R-7.6).
    """
    poll = registration.poll
    with translation.override(registration.language):
        context = {
            "poll_title": poll.title(registration.language),
            "tracking_code": format_tracking_code(TrackingCode(tracking_code)),
            "ranking_lines": _ranking_lines(registration, ranking),
            "closes_at": poll.closes_at,
            "allow_modification": poll.allow_ballot_modification,
        }
        subject = _("Votre bulletin est enregistré : %(poll)s") % {"poll": context["poll_title"]}
        body = render_to_string("registrations/mail/ballot_receipt.txt", context)
    return send_mail(subject, body, default_from_email(), [registration.email])


def send_confirmation(registration: Registration, token: Token) -> int:
    """Step 7. Carries the ballot link and, where modification is enabled, says
    plainly that losing this mail loses the ability to change the ballot — which
    nonetheless still counts (R-5.6, R-7.6).

    It carries **no tracking code**: the code belongs to a ballot and no ballot
    exists yet. Issuing one here would put the same value on a ``Registration``
    row and a ``Ballot`` row, which is a join in all but name (§6.2, T-25).
    """
    poll = registration.poll
    with translation.override(registration.language):
        context = {
            "poll_title": poll.title(registration.language),
            "ballot_url": ballot_url(registration, token),
            "closes_at": poll.closes_at,
            "allow_modification": poll.allow_ballot_modification,
        }
        subject = _("Confirmez votre inscription : %(poll)s") % {"poll": context["poll_title"]}
        body = render_to_string("registrations/mail/confirmation.txt", context)
    return send_mail(subject, body, default_from_email(), [registration.email])


def send_reminder(registration: Registration) -> int:
    """Step 8 (R-5.7). Carries no token: the voter already has one, and minting
    a second would leave two live ``voter_hash`` values for one registration.

    A voter who has lost the first mail cannot be helped by this one, which is
    the honest consequence of R-7.6 and is what the confirmation mail warned
    about.
    """
    poll = registration.poll
    with translation.override(registration.language):
        context = {"poll_title": poll.title(registration.language), "closes_at": poll.closes_at}
        subject = _("Rappel : le scrutin « %(poll)s » se clôt bientôt") % {
            "poll": context["poll_title"]
        }
        body = render_to_string("registrations/mail/reminder.txt", context)
    return send_mail(subject, body, default_from_email(), [registration.email])
