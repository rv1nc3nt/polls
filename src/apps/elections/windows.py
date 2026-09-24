# SPDX-License-Identifier: 0BSD
"""The voting window (INV-2), in one place (§5.1).

Every ballot and registration write path calls this. **The clock refuses, the
state admits** (``docs/specification-decision-log.md`` #33): a write needs the
poll to be ``open`` *and* the clock inside the window for its source.

The two halves are not interchangeable. Nothing here relies on ``state`` to
refuse a write past a deadline: the scheduled ``close_poll`` may run late,
twice, or not at all (§4), so ``closes_at`` and ``paper_entry_deadline`` are
enforced on the clock alone, whatever the state field says (T-52). Requiring
``open`` can only refuse more, never less. At the opening end it is what the
write paths need anyway — ``open_poll`` takes the snapshot every match,
approval and paper entry reads — so a late ``open_poll`` delays the start of
voting without admitting anything outside the window. ``withdrawn`` (R-3.11,
T-78) and a ``draft`` or ``announced`` poll (R-3.10) are refused by the same
rule. Elapsing time is not a method call, so the clock is consulted at the
point of use; the INV-2 triggers enforce the same rule (migration 0014).

The window differs by source. Keying a paper ballot is transcription, not
voting: the ballot was cast physically before ``closes_at`` and the signed form
evidences that, while the keystroke timestamp is a clerical artefact (§6.4).
Countersignature is itself a write to the ballot and gets the same window, so
the countersign queue stays usable to the deadline (T-56).
"""

from __future__ import annotations

from datetime import datetime

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.ballots.models import BallotSource

from .models import Poll, PollState


class WindowClosed(Exception):
    """A write refused because it falls outside the poll's window."""


def _require_open(poll: Poll, *, not_yet: str, over: str) -> None:
    """The state half of the rule: admit only an ``open`` poll.

    ``closed`` and ``published`` get the same message as the clock would give,
    since both are only ever reached past the deadline (§4)."""
    if poll.state == PollState.OPEN:
        return
    if poll.state == PollState.WITHDRAWN:
        raise WindowClosed(_("Ce scrutin a été retiré."))
    if poll.state in (PollState.DRAFT, PollState.ANNOUNCED):
        raise WindowClosed(not_yet)
    raise WindowClosed(over)


def check_ballot_window(poll: Poll, source: str, now: datetime | None = None) -> None:
    """Raise unless a ballot of ``source`` may be written to ``poll`` now."""
    over = (
        _("Le vote en ligne est clos.")
        if source == BallotSource.ONLINE
        else _("La saisie des bulletins papier est close.")
    )
    _require_open(poll, not_yet=_("Le scrutin n'est pas encore ouvert."), over=over)
    now = now or timezone.now()
    if now < poll.opens_at:
        raise WindowClosed(_("Le scrutin n'est pas encore ouvert."))
    deadline = poll.closes_at if source == BallotSource.ONLINE else poll.paper_entry_deadline
    if now >= deadline:
        raise WindowClosed(over)


def online_voting_closed(poll: Poll, now: datetime | None = None) -> bool:
    """True once online voting has actually stopped, by the clock (§5.1) —
    not ``poll.state``, which still reads ``open`` for the whole paper-keying
    stretch that follows ``closes_at`` (§6.4) until ``close_poll`` runs, late
    or not at all (§4). ``closes_at > opens_at`` is a database constraint
    (``models.py``), so state ``open`` past ``closes_at`` already implies
    ``opens_at`` has passed too.

    Shared by the public page (``apps.publicsite``) and the back-office
    dashboard (§6.5.1), so an operator sees the same "vote en ligne clos"
    notice a visitor already does, rather than the raw ``open`` state alone.
    """
    now = now or timezone.now()
    return poll.state == PollState.OPEN and now >= poll.closes_at


def check_registration_window(
    poll: Poll, now: datetime | None = None, *, channel: str | None = None
) -> None:
    """No registration write outside an ``open`` poll's window (INV-2).

    ``open`` because matching is against the frozen snapshot (R-5.3), which
    exists only once the poll has opened (§4): registering earlier would not
    fail, it would route every applicant to ``pending_review`` for want of a
    roll to match against, and R-3.10 offers no registration while
    ``announced``. The ``opens_at`` check is kept beside it as the clock's own
    lower bound (T-52).

    ``channel`` is set to ``paper`` by the paper-entry path only: the
    voting-channel indicator of a paper voter tracks the *ballot* window, not
    the registration window, because keying is transcription of a vote cast
    before ``closes_at`` (§6.4) and the INV-2 trigger admits the same. Every
    other registration write still stops at ``closes_at``.

    The retention purge is the sole exception and is not a caller here: it goes
    through ``apps.elections.retention``, of which it is the only user, and the
    database trigger names the exception rather than being disabled for it
    (§11).
    """
    _require_open(
        poll,
        not_yet=_("Les inscriptions ne sont pas encore ouvertes."),
        over=_("Les inscriptions sont closes."),
    )
    now = now or timezone.now()
    if now < poll.opens_at:
        raise WindowClosed(_("Les inscriptions ne sont pas encore ouvertes."))
    deadline = poll.paper_entry_deadline if channel == BallotSource.PAPER else poll.closes_at
    if now >= deadline:
        raise WindowClosed(_("Les inscriptions sont closes."))
