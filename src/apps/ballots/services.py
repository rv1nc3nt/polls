# SPDX-License-Identifier: 0BSD
"""Casting, modification and paper entry (§6.3, §6.4).

Never imports ``apps.registrations`` models (INV-1); it calls that app's
services with a registration or snapshot-entry id and a bare channel string, and
receives ids and strings back — never a ``Registration``. Every write path here
calls ``check_ballot_window`` first (INV-2), including countersignature and
paper correction, which are themselves ballot writes (T-56).

**Online casting and modification write no audit event.** §10's minimum list
covers paper create/correct/delete and countersignatures, not the online
channel: an event referencing a ballot, written in the same transaction as the
``Registration.channel`` flip, would be a timing side-channel joining a voter to
their ballot (INV-1). The version history on the ballot chain itself is the
record R-7.3 asks for.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.audit.models import Action, Reason
from apps.core.codes import new_tracking_code
from apps.core.crypto import ballot_hash as ballot_hash_of
from apps.core.models import User
from apps.core.types import BallotHash, Token, TokenSalt
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


@dataclass(frozen=True)
class CastResult:
    """What the view needs after a cast, without holding a ``Ballot`` and a
    voter in one scope longer than the write itself."""

    ballot: Ballot
    registration_id: str


@transaction.atomic
def cast_online(poll: Poll, token: Token, ranking: list[list[str]]) -> CastResult:
    """First cast (§6.3, R-6.1, R-6.4).

    The token is the request's, never the session's (§7): this runs in the one
    request that carries it. From it come both handles — ``voter_hash`` locates
    the registration whose ``channel`` this flips to ``online`` (INV-5), and,
    where the poll permits modification, ``ballot_hash`` is stored on the new
    row so the modification link can find it later. Where modification is off,
    ``ballot_hash`` is **not computed and not stored**: nothing then connects
    the ballot to the token that cast it and the tracking code is the sole
    handle (§7, R-7.4 bis, T-48).

    The channel flip and the ballot insert share this transaction (§7). Any
    later use of the link is refused because ``channel`` is no longer ``none``.
    """
    check_ballot_window(poll, BallotSource.ONLINE)
    _validate(poll, ranking)

    resolved = registrations.token_channel(poll, token)
    if resolved is None:
        raise BallotRefused(_("Ce lien n'est pas valide."))
    registration_id, channel = resolved
    if channel != _CHANNEL_NONE:
        # Already voted online, or has a paper ballot. A double-clicked link
        # lands here; so does a spent link on a no-modification poll (R-7.1).
        raise BallotRefused(_("Un bulletin a déjà été enregistré pour cet électeur."))

    digest: bytes | None = None
    if poll.allow_ballot_modification:
        digest = ballot_hash_of(TokenSalt(bytes(poll.token_salt)), token)

    ballot = _insert(
        poll, ranking, BallotStatus.LIVE, source=BallotSource.ONLINE, ballot_hash=digest
    )
    registrations.mark_voted(registration_id, _CHANNEL_ONLINE)
    return CastResult(ballot=ballot, registration_id=registration_id)


@transaction.atomic
def modify(poll: Poll, ballot_hash: BallotHash, ranking: list[list[str]]) -> Ballot:
    """Replace the live version of a ballot (§6.3, R-7.1, R-7.2, T-1).

    Reached from a session holding only ``ballot_hash`` — never the token, never
    a voter reference (INV-1): the modification link exchanged the token for it
    and redirected token-free (R-7.4 ter, T-21). It follows that a modification
    writes no confirmation mail — there is no path back to the address — which
    is recorded in ``docs/spec-divergences.md``; the tracking code is unchanged
    and was mailed at the first cast.

    Inserts ``version + 1`` keeping the tracking code and the hash, and marks
    the prior row ``superseded``. The current live row is locked first, so two
    concurrent modifications leave exactly one live version and no lost update
    (T-35).
    """
    check_ballot_window(poll, BallotSource.ONLINE)
    if not poll.allow_ballot_modification:
        raise BallotRefused(_("Ce scrutin n'autorise pas la modification d'un bulletin."))
    _validate(poll, ranking)

    locked = (
        Ballot.objects.select_for_update()
        .filter(poll=poll, ballot_hash=bytes(ballot_hash), status=BallotStatus.LIVE)
        .first()
    )
    if locked is None:
        raise BallotRefused(_("Aucun bulletin à modifier pour ce lien."))

    locked.status = BallotStatus.SUPERSEDED
    locked.save(update_fields=["status"])
    return _insert(
        poll,
        ranking,
        BallotStatus.LIVE,
        version=locked.version + 1,
        tracking_code=locked.tracking_code,
        source=BallotSource.ONLINE,
        ballot_hash=bytes(ballot_hash),
    )


def online_ballot_hash(poll: Poll, token: Token) -> BallotHash:
    """The ``ballot_hash`` a token maps to (§7).

    The view puts it in the modification session entry; it is the same value
    ``cast_online`` stored on the ballot. Only meaningful where the poll permits
    modification — otherwise no such value exists anywhere (R-7.4 bis).
    """
    return ballot_hash_of(TokenSalt(bytes(poll.token_salt)), token)


def live_ranking(poll: Poll, ballot_hash: BallotHash) -> list[list[str]] | None:
    """The current ranking of the ballot a modification session points at, to
    prefill the form. Read-only; ``None`` when the hash matches no live row."""
    ballot = Ballot.live.filter(poll=poll, ballot_hash=bytes(ballot_hash)).first()
    return list(ballot.ranking) if ballot is not None else None


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
    source: str = BallotSource.PAPER,
    ballot_hash: bytes | None = None,
) -> Ballot:
    """Insert one ``Ballot``. With no ``tracking_code`` a fresh one is generated
    and re-rolled on the INV-11 collision the caller retries through (§3.4); a
    modification or ``correct_paper`` passes the code of the version it replaces.

    ``ballot_hash`` is set only for an online cast on a modification-enabled
    poll (§7); it is null for every paper row and for a no-modification poll.
    """
    fields = {
        "poll": poll,
        "version": version,
        "ranking": ranking,
        "source": source,
        "status": status,
        "ballot_hash": ballot_hash,
    }
    if tracking_code:
        return Ballot.objects.create(tracking_code=tracking_code, **fields)
    for _attempt in range(_CODE_ATTEMPTS):
        try:
            with transaction.atomic():
                return Ballot.objects.create(tracking_code=new_tracking_code(), **fields)
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
    note: str = "",
) -> Ballot:
    """Operator keying (§6.4, R-8.1–8.4).

    The operator has already confirmed the elector against the frozen snapshot
    (R-8.3); ``roll_entry_id`` is that entry and is what ``PaperBallotLink``
    records. Then:

    * a live or pending paper ballot already exists → refuse; correcting it is
      screen 6's job, not a second entry;
    * the elector has already voted online → refuse. §7 makes that ballot
      unlocatable from the registration, so a paper entry could neither replace
      it nor be counted beside it without double-counting the voter. This
      diverges from R-9.3 / T-8, which provide for a reasoned override —
      recorded in ``docs/spec-divergences.md``. Where the poll permits
      modification the elector changes their own ballot online instead;
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
        raise BallotRefused(
            _(
                "Cet électeur a déjà voté en ligne ; ce vote fait foi et ne peut pas être "
                "remplacé par un bulletin papier."
            )
        )

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
