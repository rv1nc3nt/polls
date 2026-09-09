# SPDX-License-Identifier: 0BSD
"""The voter-facing ballot pages (§6.3).

One link from the confirmation mail lands on ``access``: it confirms the mailbox
(folding in what was a separate route) and then, on the elector's channel:

* ``none`` — show the ballot and cast it. The token stays in *this* URL for the
  single cast interaction and is never written to the session (§7); the cast
  completes in the one request that holds it, then redirects to a token-free
  receipt.
* ``online`` and the poll permits modification — exchange the token for a
  session entry holding only ``ballot_hash`` and redirect to the token-free
  ``modify`` page (R-7.4 ter, T-21). Nothing in that session identifies the
  voter, so no voter↔ballot join is formed (INV-1).
* ``online`` and it does not — the link is spent (R-7.1).
* ``paper`` — refuse and direct to the mairie (R-9.2, T-7).

Every response carries the two headers of R-7.4 ter via ``tokensession.protect``.
Writes go through ``ballots.services`` and ``registrations.services`` only; no
view writes through the ORM.
"""

from __future__ import annotations

from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.core import tokensession
from apps.core.codes import format_tracking_code
from apps.core.types import BallotHash, Token, TrackingCode
from apps.elections.models import Poll
from apps.elections.windows import WindowClosed, check_ballot_window
from apps.registrations import services as registrations

from . import services
from .forms import RankingForm
from .models import BallotSource
from .ranking import BallotRefused

# ``RegistrationState`` / ``Channel`` values as bare strings: this module holds
# no ``apps.registrations`` model import (INV-1), the same discipline as
# ``ballots.services``.
_STATE_ACTIVE = "active"
_CHANNEL_NONE = "none"
_CHANNEL_ONLINE = "online"
_CHANNEL_PAPER = "paper"

_NOTICE_KINDS = ("mairie", "enregistre", "indisponible", "lien-invalide")


def _reachable_poll_or_404(poll_id: str) -> Poll:
    """INV-8: a sandbox poll is not reachable from a public URL (T-15)."""
    return get_object_or_404(Poll.objects.filter(is_sandbox=False), pk=poll_id)


def _ranking_display(poll: Poll, ranking: list[list[str]], language: str) -> list[str]:
    """``["1. A", "2. B = C"]`` for the receipt page — option labels, never ids
    on screen (§3.8)."""
    labels = {
        option.option_id: (option.label(language) or option.option_id)
        for option in poll.options.all()
    }
    return [
        f"{position}. " + " = ".join(labels.get(option_id, option_id) for option_id in group)
        for position, group in enumerate(ranking, start=1)
    ]


def _to_notice(poll: Poll, kind: str) -> HttpResponse:
    return tokensession.protect(redirect("ballots:notice", poll_id=str(poll.pk), kind=kind))


def access(request: HttpRequest, poll_id: str, token: str) -> HttpResponse:
    """The link from the confirmation mail (§6.2 step 7, §6.3)."""
    poll = _reachable_poll_or_404(poll_id)
    tok = Token(token)
    holder = registrations.arrive(poll, tok)

    if holder is None:
        return tokensession.protect(
            render(
                request,
                "ballots/message.html",
                {
                    "poll": poll,
                    "heading": _("Lien non valide"),
                    "body": _(
                        "Ce lien n'est pas valide. Vérifiez que vous l'avez copié en entier ; "
                        "en cas de doute, adressez-vous à la mairie."
                    ),
                },
                status=404,
            )
        )
    if holder.state != _STATE_ACTIVE:
        return _to_notice(poll, "indisponible")
    if holder.channel == _CHANNEL_PAPER:
        return _to_notice(poll, "mairie")
    if holder.channel == _CHANNEL_ONLINE:
        if not poll.allow_ballot_modification:
            return _to_notice(poll, "enregistre")
        try:
            check_ballot_window(poll, BallotSource.ONLINE)
        except WindowClosed:
            return _to_notice(poll, "indisponible")
        digest = services.online_ballot_hash(poll, tok)
        tokensession.store_ballot(request, str(poll.pk), digest.hex())
        return tokensession.protect(redirect("ballots:modify", poll_id=str(poll.pk)))

    # channel == none: the first-cast form, served on the token URL.
    try:
        check_ballot_window(poll, BallotSource.ONLINE)
    except WindowClosed:
        return _to_notice(poll, "indisponible")

    form = RankingForm(request.POST or None, poll=poll, language=request.LANGUAGE_CODE)
    if request.method == "POST" and form.is_valid():
        try:
            result = services.cast_online(poll, tok, form.cleaned_data["ranking"])
        except WindowClosed:
            return _to_notice(poll, "indisponible")
        except BallotRefused as refused:
            form.add_error(None, str(refused))
        else:
            transaction.on_commit(
                lambda: registrations.send_ballot_receipt(
                    result.registration_id,
                    result.ballot.tracking_code,
                    result.ballot.ranking,
                )
            )
            tokensession.store_receipt(
                request,
                str(poll.pk),
                {
                    "tracking_code": result.ballot.tracking_code,
                    "ranking": result.ballot.ranking,
                    "modified": False,
                },
            )
            return tokensession.protect(redirect("ballots:receipt", poll_id=str(poll.pk)))

    return tokensession.protect(render(request, "ballots/cast.html", {"poll": poll, "form": form}))


def modify(request: HttpRequest, poll_id: str) -> HttpResponse:
    """The token-free modification page (§6.3, R-7.1).

    Reached only from ``access`` having put ``ballot_hash`` in the session; the
    token is already gone from the URL (T-21).
    """
    poll = _reachable_poll_or_404(poll_id)
    digest_hex = tokensession.load_ballot(request, str(poll.pk))
    if not digest_hex:
        return _to_notice(poll, "lien-invalide")
    try:
        check_ballot_window(poll, BallotSource.ONLINE)
    except WindowClosed:
        return _to_notice(poll, "indisponible")

    ballot_hash = BallotHash(bytes.fromhex(digest_hex))
    form = RankingForm(
        request.POST or None,
        poll=poll,
        language=request.LANGUAGE_CODE,
        initial_ranking=services.live_ranking(poll, ballot_hash),
    )
    if request.method == "POST" and form.is_valid():
        try:
            new = services.modify(poll, ballot_hash, form.cleaned_data["ranking"])
        except WindowClosed:
            return _to_notice(poll, "indisponible")
        except BallotRefused as refused:
            form.add_error(None, str(refused))
        else:
            tokensession.store_receipt(
                request,
                str(poll.pk),
                {"tracking_code": new.tracking_code, "ranking": new.ranking, "modified": True},
            )
            return tokensession.protect(redirect("ballots:receipt", poll_id=str(poll.pk)))

    return tokensession.protect(
        render(request, "ballots/modify.html", {"poll": poll, "form": form})
    )


def receipt(request: HttpRequest, poll_id: str) -> HttpResponse:
    """The summary shown after a cast or modification (R-6.4).

    The ranking and tracking code are the voter's own, held in the session only
    to survive the redirect off the token URL — no voter identifier accompanies
    them.
    """
    poll = _reachable_poll_or_404(poll_id)
    data = tokensession.load_receipt(request, str(poll.pk))
    if not data:
        return _to_notice(poll, "lien-invalide")
    context = {
        "poll": poll,
        "tracking_code": format_tracking_code(TrackingCode(str(data["tracking_code"]))),
        "lines": _ranking_display(poll, list(data["ranking"]), request.LANGUAGE_CODE),
        "modified": bool(data.get("modified")),
        "allow_modification": poll.allow_ballot_modification,
    }
    return tokensession.protect(render(request, "ballots/receipt.html", context))


def notice(request: HttpRequest, poll_id: str, kind: str) -> HttpResponse:
    """The token-free dead-end pages: paper elector, spent link, closed poll."""
    poll = _reachable_poll_or_404(poll_id)
    if kind not in _NOTICE_KINDS:
        raise Http404
    messages = {
        "mairie": (
            _("Rendez-vous en mairie"),
            _(
                "Vous avez un bulletin papier pour cette consultation. Le vote en ligne "
                "n'est donc pas possible ; toute modification se fait en mairie."
            ),
        ),
        "enregistre": (
            _("Bulletin déjà enregistré"),
            _(
                "Votre bulletin a été enregistré. Ce scrutin n'autorise pas sa modification, "
                "et le lien reçu par courriel ne peut plus servir."
            ),
        ),
        "indisponible": (
            _("Vote indisponible"),
            _(
                "Ce lien ne donne pas accès à un bulletin : l'inscription n'est pas active, "
                "ou le scrutin n'est pas ouvert au vote en ligne."
            ),
        ),
        "lien-invalide": (
            _("Lien non valide"),
            _("Ce lien n'est pas valide. En cas de doute, adressez-vous à la mairie."),
        ),
    }
    heading, body = messages[kind]
    status = 404 if kind == "lien-invalide" else 200
    return tokensession.protect(
        render(
            request,
            "ballots/message.html",
            {"poll": poll, "heading": heading, "body": body},
            status=status,
        )
    )
