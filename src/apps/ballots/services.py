# SPDX-License-Identifier: 0BSD
"""Casting, modification and paper entry (§6.3, §6.4).

Never imports ``apps.registrations`` models (INV-1); it calls that app's
services with a registration or snapshot-entry id and a bare channel string, and
receives ids and strings back — never a ``Registration``. Every write path here
calls ``check_ballot_window`` first (INV-2), including countersignature and
paper correction, which are themselves ballot writes (T-56).

``cast_online`` and ``modify`` are still §6.3 scaffold; the paper flows of §6.4
are implemented.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.audit.models import Action, Reason
from apps.core.codes import new_tracking_code
from apps.core.models import User
from apps.core.types import Token
from apps.elections.models import Poll, RollEntry
from apps.elections.windows import check_ballot_window
from apps.registrations import services as registrations

from .models import Ballot, BallotSource, BallotStatus, PaperBallotLink

# Re-exported: callers have always caught ``services.BallotRefused``; it now
# lives with the validation that raises it (§6.3, T-29).
from .ranking import BallotRefused as BallotRefused
from .ranking import validate_ranking

# ``apps.registrations.models.Channel`` values, compared as bare strings so this
# module imports no registrations model (INV-1).
_CHANNEL_NONE = "none"
_CHANNEL_ONLINE = "online"

# Tracking codes are ~50 bits and re-rolled on collision (§3.4); a handful of
# attempts covers any realistic table.
_CODE_ATTEMPTS = 6

_EDITABLE = (BallotStatus.LIVE, BallotStatus.PENDING_COUNTERSIGN)


def cast_online(poll: Poll, token: Token, ranking: list[list[str]]) -> Ballot:
    """First cast (§6.3).

    Where ``allow_ballot_modification`` is false, ``ballot_hash`` is **not
    computed and not stored**: nothing whatever then connects a cast ballot to
    the token that cast it, and the tracking code is the voter's sole handle
    (§7, T-48). The token is spent and any later use of the link is refused.
    """
    raise NotImplementedError("§6.3")


def modify(poll: Poll, token: Token, ranking: list[list[str]]) -> Ballot:
    """A modification inserts ``version + 1`` and marks the prior row
    ``superseded`` (R-7.2, T-1). The tracking code is unchanged across versions.

    Concurrency: exactly one row stays ``live`` (T-35), so the insert and the
    supersede happen under a row lock on the poll's live ballot.
    """
    raise NotImplementedError("§6.3")


# --- §6.4 paper entry -----------------------------------------------------


def _validate(poll: Poll, ranking: list[list[str]]) -> None:
    validate_ranking(
        ranking,
        [option.option_id for option in poll.options.all()],
        require_complete=poll.require_complete_ranking,
        allow_ties=poll.allow_ties_in_ballot,
    )


def _insert(
    poll: Poll,
    ranking: list[list[str]],
    status: str,
    *,
    version: int = 1,
    tracking_code: str = "",
) -> Ballot:
    """Insert one paper ``Ballot``. With no ``tracking_code`` a fresh one is
    generated and re-rolled on the INV-11 collision the caller retries through
    (§3.4); ``correct_paper`` passes the code of the version it replaces."""
    if tracking_code:
        return Ballot.objects.create(
            poll=poll,
            tracking_code=tracking_code,
            version=version,
            ranking=ranking,
            source=BallotSource.PAPER,
            status=status,
        )
    for _attempt in range(_CODE_ATTEMPTS):
        try:
            with transaction.atomic():
                return Ballot.objects.create(
                    poll=poll,
                    tracking_code=new_tracking_code(),
                    version=version,
                    ranking=ranking,
                    source=BallotSource.PAPER,
                    status=status,
                )
        except IntegrityError as clash:
            # A trigger ABORT (INV-2 window, say) is not a code collision.
            if "INV-" in str(clash):
                raise
            continue
    raise BallotRefused(_("Impossible d'attribuer un code de suivi ; réessayez."))


def _link(
    poll: Poll,
    ballot: Ballot,
    roll_entry: RollEntry,
    operator: User,
    language: str,
    note: str,
) -> PaperBallotLink:
    return PaperBallotLink.objects.create(
        poll=poll,
        ballot=ballot,
        roll_entry=roll_entry,
        operator=operator,
        language=language,
        note=note,
    )


@transaction.atomic
def enter_paper(
    poll: Poll,
    roll_entry_id: str,
    ranking: list[list[str]],
    operator_id: str,
    language: str,
    *,
    identity_confirmed: bool = False,
    collision_reason: str = "",
    note: str = "",
) -> Ballot:
    """Operator keying (§6.4, R-8.1–8.4).

    The operator has already confirmed the elector against the frozen snapshot
    (R-8.3); ``roll_entry_id`` is that entry and is what ``PaperBallotLink``
    records. Then:

    * a live or pending paper ballot already exists → refuse; correcting it is
      screen 6's job, not a second entry;
    * the elector has voted online (R-9.3) → the override: written
      ``not_in_force_collision`` so it is recorded and linked but never counted,
      the online ballot standing (§7 makes it unlocatable, so it cannot be
      superseded). Proceeds only with ``collision_reason``, logged;
    * otherwise → written ``live``, or ``pending_countersign`` where the poll
      requires a second operator (R-8.7), and the elector's channel indicator is
      set to ``paper``.
    """
    check_ballot_window(poll, BallotSource.PAPER)
    _validate(poll, ranking)
    entry = RollEntry.objects.get(poll=poll, pk=roll_entry_id)
    operator = User.objects.get(pk=operator_id)

    if PaperBallotLink.objects.filter(
        poll=poll, roll_entry=entry, ballot__status__in=_EDITABLE
    ).exists():
        raise BallotRefused(
            _("Cet électeur a déjà un bulletin papier ; passez par l'écran de rectification.")
        )

    registration_id, channel = registrations.ensure_paper_registration(poll, roll_entry_id)

    if channel == _CHANNEL_ONLINE:
        if not collision_reason:
            raise BallotRefused(
                _(
                    "Cet électeur a déjà voté en ligne : confirmez et indiquez un motif "
                    "pour enregistrer tout de même un bulletin papier."
                )
            )
        ballot = _insert(poll, ranking, BallotStatus.NOT_IN_FORCE_COLLISION)
        _link(poll, ballot, entry, operator, language, note)
        audit.record(
            action=Action.CHANNEL_COLLISION_OVERRIDE,
            poll=poll,
            actor=operator,
            object_ref=audit.ref(ballot),
            after={"status": ballot.status, "source": ballot.source, "counted": False},
            reason=collision_reason,
        )
        return ballot

    status = (
        BallotStatus.PENDING_COUNTERSIGN if poll.paper_requires_countersign else BallotStatus.LIVE
    )
    ballot = _insert(poll, ranking, status)
    _link(poll, ballot, entry, operator, language, note)
    if channel == _CHANNEL_NONE:
        # An existing registration on the ``none`` channel; a freshly created
        # one is already ``paper`` and needs no second write (§6.4, D2).
        registrations.mark_voted(registration_id, "paper")
    audit.record(
        action=Action.PAPER_BALLOT_CREATED,
        poll=poll,
        actor=operator,
        object_ref=audit.ref(ballot),
        after={"status": ballot.status, "source": ballot.source},
        reason=Reason.IDENTITY_CONFIRMED_AT_MAIRIE if identity_confirmed else "",
    )
    return ballot


@transaction.atomic
def correct_paper(
    ballot: Ballot, ranking: list[list[str]], operator_id: str, reason: str, note: str
) -> Ballot:
    """R-8.5: reason mandatory, before/after logged. The repair of a keying
    error, not the voter changing their mind — available whether or not the poll
    permits electors to modify their votes.

    Inserts ``version + 1`` keeping the tracking code, marks the prior row
    ``superseded``, and gives the new version its own ``PaperBallotLink``
    inheriting the countersignature (D5): a typo fix does not re-enter screen 7.
    """
    check_ballot_window(ballot.poll, BallotSource.PAPER)
    if not reason:
        raise BallotRefused(_("Un motif est obligatoire pour rectifier un bulletin."))
    poll = ballot.poll
    _validate(poll, ranking)
    operator = User.objects.get(pk=operator_id)

    locked = Ballot.objects.select_for_update().get(pk=ballot.pk)
    if locked.status not in _EDITABLE:
        raise BallotRefused(_("Ce bulletin ne peut pas être rectifié."))
    prior_link = locked.paper_link
    before = list(locked.ranking)
    in_force = locked.status
    prior_version = locked.version
    prior_code = locked.tracking_code

    # Supersede first: ``uniq_ballot_poll_tracking_code`` admits only one
    # non-superseded row per code, so the old version must step aside before the
    # new one lands.
    locked.status = BallotStatus.SUPERSEDED
    locked.save(update_fields=["status"])
    new = _insert(poll, ranking, in_force, version=prior_version + 1, tracking_code=prior_code)
    PaperBallotLink.objects.create(
        poll=poll,
        ballot=new,
        roll_entry=prior_link.roll_entry,
        operator=operator,
        countersigned_by=prior_link.countersigned_by,
        language=prior_link.language,
        note=note,
    )
    audit.record(
        action=Action.PAPER_BALLOT_CORRECTED,
        poll=poll,
        actor=operator,
        object_ref=audit.ref(new),
        before={"ranking": before, "version": prior_version},
        after={"ranking": ranking, "version": new.version},
        reason=reason,
    )
    return new


@transaction.atomic
def delete_paper(ballot: Ballot, operator_id: str, reason: str, note: str) -> Ballot:
    """R-8.5, R-9.4, T-31: status ``deleted`` — never physically removed —
    ``channel`` cleared so online voting is re-enabled, and both moves recorded
    on one event with a mandatory reason."""
    check_ballot_window(ballot.poll, BallotSource.PAPER)
    if not reason:
        raise BallotRefused(_("Un motif est obligatoire pour supprimer un bulletin."))

    locked = Ballot.objects.select_for_update().get(pk=ballot.pk)
    if locked.status not in _EDITABLE:
        raise BallotRefused(_("Ce bulletin ne peut pas être supprimé."))
    link = locked.paper_link
    operator = User.objects.get(pk=operator_id)

    before_status = locked.status
    locked.status = BallotStatus.DELETED
    locked.save(update_fields=["status"])
    if note and link.note != note:
        link.note = note
        link.save(update_fields=["note"])
    if link.roll_entry_id is not None:
        registrations.clear_paper_channel(locked.poll, str(link.roll_entry_id))

    audit.record(
        action=Action.PAPER_BALLOT_DELETED,
        poll=locked.poll,
        actor=operator,
        object_ref=audit.ref(locked),
        before={"status": before_status, "channel": "paper"},
        after={"status": BallotStatus.DELETED, "channel": "none"},
        reason=reason,
    )
    return locked


@transaction.atomic
def countersign(ballot: Ballot, operator_id: str) -> Ballot:
    """Second operator validates a pending entry (R-8.7), which sets it ``live``.

    A write to the ballot, so the paper window applies and the queue stays
    usable up to ``paper_entry_deadline`` (T-56). Refused for the operator who
    keyed it: R-8.7 wants a *second* named operator.
    """
    check_ballot_window(ballot.poll, BallotSource.PAPER)
    locked = Ballot.objects.select_for_update().get(pk=ballot.pk)
    if locked.status != BallotStatus.PENDING_COUNTERSIGN:
        raise BallotRefused(_("Ce bulletin n'est pas en attente de contreseing."))
    link = locked.paper_link
    if str(link.operator_id) == str(operator_id):
        raise BallotRefused(_("Le contreseing doit être apposé par un second opérateur."))
    operator = User.objects.get(pk=operator_id)

    locked.status = BallotStatus.LIVE
    locked.save(update_fields=["status"])
    link.countersigned_by = operator
    link.save(update_fields=["countersigned_by"])
    audit.record(
        action=Action.PAPER_BALLOT_COUNTERSIGNED,
        poll=locked.poll,
        actor=operator,
        object_ref=audit.ref(locked),
        before={"status": BallotStatus.PENDING_COUNTERSIGN},
        after={"status": BallotStatus.LIVE},
    )
    return locked
