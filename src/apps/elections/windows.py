# SPDX-License-Identifier: 0BSD
"""The voting window (INV-2), in one place (§5.1).

Every ballot write path calls this, and it does not consult ``Poll.state``: the
scheduled transition may not have run yet, may have run twice, or may not run at
all (§4), and a ballot outside the window must be refused whatever the state
field says (T-52). Elapsing time is not a method call, so the clock is consulted
at the point of use.

One exception: ``withdrawn`` (R-3.11) is never a scheduled transition — it is a
deliberate, one-off action with a mandatory reason — so both functions here
refuse unconditionally the instant a poll reaches it, before looking at the
clock at all. The INV-2 trigger carries the same exception on ``INSERT`` and
``UPDATE``, the mirror of the ``DELETE`` carve-out §11 grants the retention
purge (T-78).

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


def check_ballot_window(poll: Poll, source: str, now: datetime | None = None) -> None:
    """Raise unless a ballot of ``source`` may be written to ``poll`` now."""
    if poll.state == PollState.WITHDRAWN:
        raise WindowClosed(_("Ce scrutin a été retiré."))
    now = now or timezone.now()
    if now < poll.opens_at:
        raise WindowClosed(_("Le scrutin n'est pas encore ouvert."))
    deadline = poll.closes_at if source == BallotSource.ONLINE else poll.paper_entry_deadline
    if now >= deadline:
        raise WindowClosed(
            _("Le vote en ligne est clos.")
            if source == BallotSource.ONLINE
            else _("La saisie des bulletins papier est close.")
        )


def check_registration_window(
    poll: Poll, now: datetime | None = None, *, channel: str | None = None
) -> None:
    """No registration write after ``closes_at`` (INV-2), nor before ``opens_at``.

    INV-2 names only the closing bound. The opening one is here because
    matching is against the frozen snapshot (R-5.3), and the snapshot does not
    exist until ``draft → open`` writes it (§4): registering earlier would not
    fail, it would route every applicant to ``pending_review`` for want of a
    roll to match against, which is worse. Like the ballot window this consults
    the clock and not ``Poll.state``, since the scheduled transition may run
    late (§4).

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
    if poll.state == PollState.WITHDRAWN:
        raise WindowClosed(_("Ce scrutin a été retiré."))
    now = now or timezone.now()
    if now < poll.opens_at:
        raise WindowClosed(_("Les inscriptions ne sont pas encore ouvertes."))
    deadline = poll.paper_entry_deadline if channel == BallotSource.PAPER else poll.closes_at
    if now >= deadline:
        raise WindowClosed(_("Les inscriptions sont closes."))
