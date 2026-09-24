# SPDX-License-Identifier: 0BSD
"""What each definitive action on a poll will do, for its confirmation page
(R-2.4, decision log #35).

Read model only: every function here reads the poll as it is at that moment
and returns a ``Confirmation``; nothing is written. The view renders it with
``backoffice/confirm.html`` and acts only on the second POST, the one carrying
``confirmed=1`` — so a forged or double-clicked single POST changes nothing,
and the consequences shown are computed from the poll the operator is about
to act on, not from the page they clicked on.

Consequences name counts and instants, never an elector (§10): the page is a
back-office screen but the same rule as the audit log keeps it from becoming
one more place a name turns up.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import formats, timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.audit.models import Reason
from apps.ballots.models import Ballot, BallotSource
from apps.elections import closure
from apps.elections.models import Poll
from apps.elections.transitions import closing_blockers, is_early_closure

from . import dashboard


@dataclass(frozen=True)
class Confirmation:
    """One confirmation page: the poll acted on, its question, its button and
    what will happen.

    ``irreversible`` adds the sentence saying the action cannot be undone; it
    is true of every action here, and stays a field so the page never states
    it of one that is not.
    """

    poll: Poll
    title: str
    button: str
    consequences: list[str] = field(default_factory=list)
    irreversible: bool = True


def _when(poll: Poll, instant: datetime) -> str:
    """An instant in the poll's own timezone, in the active locale's format."""
    local = timezone.localtime(instant, ZoneInfo(poll.timezone))
    return str(formats.date_format(local, "DATETIME_FORMAT"))


def _reason(code: str) -> str:
    return str(dict(Reason.choices).get(code, code))


def announce(poll: Poll) -> Confirmation:
    return Confirmation(
        poll=poll,
        title=_("Annoncer le scrutin ?"),
        button=_("Annoncer le scrutin"),
        consequences=[
            _("Le scrutin devient visible sur le site public : propositions et calendrier."),
            _("La configuration est figée : elle ne pourra plus être modifiée."),
            _("Ni inscription ni vote ne sont possibles avant l'ouverture."),
        ],
    )


def open_(poll: Poll) -> Confirmation:
    now = timezone.now()
    consequences = [
        _("Les inscriptions et le vote s'ouvrent immédiatement."),
        _("La liste électorale en vigueur est figée pour ce scrutin."),
    ]
    if poll.opens_at > now:
        consequences.append(
            _("Ouverture avancée : prévue le %(planned)s, elle devient l'instant présent.")
            % {"planned": _when(poll, poll.opens_at)}
        )
    return Confirmation(
        poll=poll,
        title=_("Ouvrir le scrutin ?"),
        button=_("Ouvrir le scrutin"),
        consequences=consequences,
    )


def close(poll: Poll, reason: str) -> Confirmation:
    consequences = [
        _(
            "Plus aucune inscription, aucun vote en ligne ni aucune saisie de bulletin "
            "papier ne sera accepté."
        ),
        _("L'empreinte de clôture et les compteurs de participation sont figés."),
    ]
    if is_early_closure(poll):
        consequences.append(
            _(
                "Clôture anticipée : la fin de saisie prévue le %(planned)s devient "
                "l'instant présent. Elle sera affichée sur la page publique avec le "
                "motif « %(reason)s »."
            )
            % {"planned": _when(poll, poll.paper_entry_deadline), "reason": _reason(reason)}
        )
    participation = dashboard.participation(poll)
    if participation.pending_review:
        consequences.append(
            ngettext(
                "%(count)d inscription en attente d'examen ne pourra plus voter.",
                "%(count)d inscriptions en attente d'examen ne pourront plus voter.",
                participation.pending_review,
            )
            % {"count": participation.pending_review}
        )
    if participation.pending_email:
        consequences.append(
            ngettext(
                "%(count)d électeur n'a pas confirmé son adresse et ne pourra plus voter.",
                "%(count)d électeurs n'ont pas confirmé leur adresse et ne pourront plus voter.",
                participation.pending_email,
            )
            % {"count": participation.pending_email}
        )
    pending = [b for b in closing_blockers(poll) if b.startswith("pending_countersign:")]
    if pending:
        count = int(pending[0].split(":", 1)[1])
        consequences.append(
            ngettext(
                "%(count)d bulletin papier non contresigné sera exclu du décompte et "
                "publié à part (motif « %(reason)s »).",
                "%(count)d bulletins papier non contresignés seront exclus du décompte et "
                "publiés à part (motif « %(reason)s »).",
                count,
            )
            % {"count": count, "reason": _reason(reason)}
        )
    return Confirmation(
        poll=poll,
        title=_("Clore le scrutin ?"),
        button=_("Clore le scrutin"),
        consequences=consequences,
    )


def extend(poll: Poll, new_closes_at: datetime, reason: str) -> Confirmation:
    return Confirmation(
        poll=poll,
        title=_("Reporter la clôture ?"),
        button=_("Reporter la clôture"),
        consequences=[
            _(
                "La clôture passe du %(old)s au %(new)s ; la fin de saisie papier est "
                "décalée d'autant."
            )
            % {"old": _when(poll, poll.closes_at), "new": _when(poll, new_closes_at)},
            _("Le report est affiché sur la page publique avec le motif « %(reason)s ».")
            % {"reason": _reason(reason)},
        ],
    )


def withdraw(poll: Poll, reason: str) -> Confirmation:
    return Confirmation(
        poll=poll,
        title=_("Retirer le scrutin ?"),
        button=_("Retirer le scrutin"),
        consequences=[
            _(
                "Plus rien du scrutin ne reste visible sur le site public, y compris son "
                "résultat s'il a été publié."
            ),
            _("Aucune inscription ni aucun vote n'est plus accepté."),
            _("Motif enregistré : « %(reason)s ».") % {"reason": _reason(reason)},
            _("Les bulletins et le journal d'audit sont conservés."),
        ],
    )


def publish(poll: Poll) -> Confirmation:
    _ballots, _options, result = closure.tallied(poll)
    labels = {o.option_id: o.label(poll.default_language) for o in poll.options.all()}
    consequences = [
        _(
            "Le résultat, la liste anonymisée des bulletins et l'empreinte de clôture "
            "deviennent publics."
        )
    ]
    if result.winner is not None:
        consequences.append(
            _("Proposition publiée comme gagnante : %(label)s.")
            % {"label": labels.get(result.winner, result.winner)}
        )
    return Confirmation(
        poll=poll,
        title=_("Publier les résultats ?"),
        button=_("Publier les résultats"),
        consequences=consequences,
    )


def reconciliation(poll: Poll, forms_retained: int) -> Confirmation:
    recorded = Ballot.live.filter(poll=poll, source=BallotSource.PAPER).count()
    return Confirmation(
        poll=poll,
        title=_("Signer le procès-verbal de rapprochement ?"),
        button=_("Signer le procès-verbal"),
        consequences=[
            _(
                "%(forms)d formulaire(s) conservé(s) pour %(recorded)d bulletin(s) papier "
                "enregistré(s) : écart de %(gap)d."
            )
            % {"forms": forms_retained, "recorded": recorded, "gap": forms_retained - recorded},
            _("Le procès-verbal est signé à votre nom et ne pourra plus être modifié."),
        ],
    )


def delete_sandbox(poll: Poll) -> Confirmation:
    return Confirmation(
        poll=poll,
        title=_("Supprimer ce scrutin d'essai ?"),
        button=_("Supprimer définitivement"),
        consequences=[
            _(
                "Le scrutin d'essai et tout ce qu'il contient — inscriptions, bulletins, "
                "liste figée, images — sont supprimés."
            ),
            _("Le journal d'audit conserve la trace de la suppression."),
        ],
    )
