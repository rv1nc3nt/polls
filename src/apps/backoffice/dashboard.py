# SPDX-License-Identifier: 0BSD
"""The read model behind screen 1, tableau de bord (§6.5.1).

Separate from the view because it is where INV-1 is kept by hand. Two aggregates
are read here from different tables and they are **never joined**: participation
comes from ``Registration.channel``, the countersignature backlog from
``Ballot.status``. They meet as two integers in a template, which is the pair of
irreconcilable lists an administrator is allowed to see (R-7.5) — the same
discipline ``elections.closure`` keeps for the same reason.

"Has this person voted" is answered by ``Registration.channel`` and never by
counting ballots (INV-5). The one ballot count here is the
``pending_countersign`` backlog, which is a queue length rather than a turnout
figure and identifies nobody.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.utils.translation import gettext as _

from apps.core.models import Role
from apps.elections.closure import frozen_counts
from apps.elections.models import Poll, PollState
from apps.elections.transitions import closing_blockers, opening_blockers
from apps.registrations.models import Channel, Registration, RegistrationState


@dataclass(frozen=True)
class Participation:
    """Turnout as the dashboard shows it (§6.5.1).

    ``as_at_closure`` says which of the two sources this came from. Once the
    poll is closed the figures are the ones frozen at closure (§9) and not a
    fresh count: the registrations behind a fresh count are deleted two months
    later by the retention job (§11), at which point counting live would report
    a turnout of zero for a poll that had one (T-58).
    """

    as_at_closure: bool
    registered: int
    voted_online: int
    voted_paper: int
    not_voted: int
    #: Unavailable on a closed poll: §9 freezes turnout, not the review queue.
    confirmed: int | None = None
    pending_review: int | None = None


def participation(poll: Poll) -> Participation:
    if poll.state in {PollState.CLOSED, PollState.PUBLISHED}:
        counts = poll.frozen_counts or frozen_counts(poll)
        return Participation(
            as_at_closure=True,
            registered=counts.get("registered", 0),
            voted_online=counts.get("ballots_online", 0),
            voted_paper=counts.get("ballots_paper", 0),
            not_voted=counts.get("non_voters", 0),
        )

    registrations = Registration.objects.filter(poll=poll)
    active = registrations.filter(state=RegistrationState.ACTIVE)
    online = active.filter(channel=Channel.ONLINE).count()
    paper = active.filter(channel=Channel.PAPER).count()
    confirmed = active.count()
    return Participation(
        as_at_closure=False,
        registered=registrations.count(),
        confirmed=confirmed,
        voted_online=online,
        voted_paper=paper,
        not_voted=confirmed - online - paper,
        pending_review=registrations.filter(state=RegistrationState.PENDING_REVIEW).count(),
    )


def describe_blocker(code: str) -> str:
    """A blocker code (§4) as a sentence a council member can act on.

    ``opening_blockers`` and ``closing_blockers`` return codes so that the
    scheduled commands can log them (§14); this screen is where they become
    French, because the point of naming them before the opening hour is that
    somebody fixes them (§6.5.1).
    """
    head, _sep, rest = code.partition(":")
    match head:
        case "not_draft":
            return _("Le scrutin n'est plus en brouillon.")
        case "not_open":
            return _("Le scrutin n'est pas ouvert.")
        case "fewer_than_two_options":
            return _("Il faut au moins deux propositions.")
        case "no_roll_to_snapshot":
            return _("Aucune liste électorale importée : rien à figer à l'ouverture.")
        case "pending_countersign":
            return _("Clôture bloquée : %(count)s bulletin(s) en attente de contreseing.") % {
                "count": rest
            }
        case "missing_translation":
            what, _sep2, language = rest.rpartition(":")
            if what.startswith("option:"):
                return _("Traduction manquante en %(language)s : proposition « %(option)s ».") % {
                    "language": language,
                    "option": what.removeprefix("option:"),
                }
            labels = {"title": _("le titre"), "description": _("la description")}
            return _("Traduction manquante en %(language)s : %(what)s.") % {
                "language": language,
                "what": labels.get(what, what),
            }
        case _:
            return code


def blockers(poll: Poll) -> list[str]:
    """What would stop the next transition, described (§4, §6.5.1).

    Named while there is still time to act on them: a silent non-opening at the
    advertised hour is the worst outcome available here, and a closure that
    stops on an uncountersigned ballot is the second worst.
    """
    if poll.state == PollState.DRAFT:
        return [describe_blocker(code) for code in opening_blockers(poll)]
    if poll.state == PollState.OPEN:
        return [describe_blocker(code) for code in closing_blockers(poll)]
    return []


@dataclass(frozen=True)
class PermittedAction:
    """One entry in "the actions permitted in the current state" (§6.5.1).

    Permitted means both: the state allows it, and this operator holds the role
    that opens it (§3.7). ``url_name`` is ``None`` for a screen not yet built,
    which the template renders as pending rather than as a dead link.
    """

    label: str
    roles: tuple[Role, ...]
    url_name: str | None = None


def _actions_for_state(poll: Poll) -> list[PermittedAction]:
    """Screens 2–11 of §6.5 against the states that permit them.

    Built per call, not as a module constant: ``gettext`` at import time would
    resolve every label once, in whatever language happened to be active then,
    and the back-office is bilingual (§3.8).

    Roles follow §3.7's separation — keying and countersigning are the entry
    operator's, configuration and closure the poll admin's. A poll admin who
    must key a ballot grants themselves ``entry_operator`` first, and the grant
    is audited (§10): the same reasoning as ``access.py``'s treatment of
    ``commune_admin``.
    """
    match poll.state:
        case PollState.DRAFT:
            return [
                PermittedAction(_("Configurer le scrutin"), (Role.POLL_ADMIN,)),
                PermittedAction(_("Importer la liste électorale"), (Role.POLL_ADMIN,)),
            ]
        case PollState.OPEN:
            actions = [
                PermittedAction(
                    _("Examiner les inscriptions en attente"),
                    (Role.POLL_ADMIN,),
                    url_name="backoffice:registration_queue",
                ),
                PermittedAction(_("Saisir un bulletin papier"), (Role.ENTRY_OPERATOR,)),
                PermittedAction(
                    _("Rectifier ou supprimer un bulletin papier"), (Role.ENTRY_OPERATOR,)
                ),
                PermittedAction(_("Reporter la date de clôture"), (Role.POLL_ADMIN,)),
            ]
            if poll.paper_requires_countersign:
                actions.append(
                    PermittedAction(_("Contresigner des bulletins"), (Role.ENTRY_OPERATOR,))
                )
            return actions
        case PollState.CLOSED:
            return [PermittedAction(_("Dépouiller et publier"), (Role.POLL_ADMIN,))]
        case _:
            return []


def permitted_actions(poll: Poll, roles: frozenset[str]) -> list[PermittedAction]:
    """Filtered by state and by the roles this operator actually holds.

    Offering a link the operator would be refused at is how a purpose-built
    back-office starts to feel like Django admin (§6.5).
    """
    actions = _actions_for_state(poll)
    # Screen 8 is reachable in every state, and is the one already built.
    actions.append(
        PermittedAction(
            _("Consulter le journal d'audit"),
            (Role.AUDITOR, Role.POLL_ADMIN),
            url_name="backoffice:audit_log",
        )
    )
    return [a for a in actions if roles & {str(role) for role in a.roles}]
