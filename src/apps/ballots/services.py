# SPDX-License-Identifier: 0BSD
"""Casting, modification and paper entry (§6.3, §6.4).

Never imports ``apps.registrations`` models (INV-1); it calls that app's
``mark_voted`` service with a registration id and a channel, and receives
nothing back. Every write path here calls ``check_ballot_window`` first
(INV-2) — including countersignature, which is itself a write (T-56).

TODO(scaffold): the flows. The pieces they compose are done: the window check
(``apps.elections.windows``), the hashes (``apps.core.crypto``), tracking codes
(``apps.core.codes``) and the canonical serialisation (``apps.core.canonical``).
"""

from __future__ import annotations

from apps.core.types import Token
from apps.elections.models import Poll

from .models import Ballot


class BallotRefused(Exception):
    """A cast or modification the server refuses, whatever the browser allowed.

    Ranking constraints are validated here as well as in the page, since a
    ballot can be posted straight to the endpoint (T-29).
    """


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


def enter_paper(
    poll: Poll, roll_entry_id: str, ranking: list[list[str]], operator_id: str
) -> Ballot:
    """Operator keying (§6.4).

    The operator has already searched the snapshot by name or date of birth and
    confirmed the elector (R-8.3); ``roll_entry_id`` is that snapshot entry, and
    it is what ``PaperBallotLink`` records. Checks ``Registration.channel``
    first: ``paper`` is an edit of the existing ballot; ``online`` raises the
    blocking interstitial of R-9.3, which proceeds only on explicit confirmation
    with a mandatory reason code, both logged; ``none`` proceeds. Where
    ``paper_requires_countersign`` is set the row is written
    ``pending_countersign`` and is not counted until a second named operator
    validates it.
    """
    raise NotImplementedError("§6.4")


def countersign(ballot: Ballot, operator_id: str) -> Ballot:
    """Second operator validates a pending entry (R-8.7).

    A write to the ballot, so the paper window applies (T-56), and the queue
    stays usable up to ``paper_entry_deadline``.
    """
    raise NotImplementedError("§6.4")


def correct_paper(ballot: Ballot, ranking: list[list[str]], reason: str, note: str) -> Ballot:
    """R-8.5: reason mandatory, before/after logged. The repair of a keying
    error, not the voter changing their mind — unaffected by
    ``allow_ballot_modification``."""
    raise NotImplementedError("§6.4")


def delete_paper(ballot: Ballot, reason: str, note: str) -> Ballot:
    """R-8.5, R-9.4: status ``deleted``, never physically removed; clears
    ``channel`` so online voting is re-enabled; both actions logged (T-31)."""
    raise NotImplementedError("§6.4")
