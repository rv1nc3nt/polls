# SPDX-License-Identifier: 0BSD
"""The voting window (INV-2), in one place (§5.1).

Every ballot write path calls this, and it does not consult ``Poll.state``: the
scheduled transition may not have run yet, may have run twice, or may not run at
all (§4), and a ballot outside the window must be refused whatever the state
field says (T-52). Elapsing time is not a method call, so the clock is consulted
at the point of use.

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

from .models import Poll


class WindowClosed(Exception):
    """A write refused because it falls outside the poll's window."""


def check_ballot_window(poll: Poll, source: str, now: datetime | None = None) -> None:
    """Raise unless a ballot of ``source`` may be written to ``poll`` now."""
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


def check_registration_window(poll: Poll, now: datetime | None = None) -> None:
    """No registration write after ``closes_at`` (INV-2).

    The retention purge is the sole exception and is not a caller here: it goes
    through ``apps.elections.retention``, of which it is the only user, and the
    database trigger names the exception rather than being disabled for it
    (§11).
    """
    now = now or timezone.now()
    if now >= poll.closes_at:
        raise WindowClosed(_("Les inscriptions sont closes."))
