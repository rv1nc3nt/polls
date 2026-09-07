# SPDX-License-Identifier: 0BSD
"""Registration flow (§6.2).

Never imports ``apps.ballots`` (INV-1). Voting status is written here, on
``Registration.channel``, in the same transaction as the ballot insert — the
ballot service calls ``mark_voted`` below and passes no voter identity back.

TODO(scaffold): steps 1–9 of §6.2. The pure parts they rest on are done and
tested: name matching and address canonicalisation in ``apps.core.names``, the
token and hashes in ``apps.core.crypto``.
"""

from __future__ import annotations

from django.db import transaction

from apps.elections.models import Poll, RollEntry

from .models import Channel, Registration


class RegistrationRefused(Exception):
    """Shown to the visitor as a neutral message.

    Cases 3 and 6 of §6.2 — address already used, NNE already registered — get
    the *same* message and disclose no detail of the existing registration
    (T-2, T-17).
    """


def find_roll_entry(poll: Poll, nne: str) -> RollEntry | None:
    """Step 2: match on NNE against the frozen snapshot (R-5.3)."""
    return RollEntry.objects.filter(poll=poll, nne=nne).first()


def register(poll: Poll, form_data: dict[str, str], language: str) -> Registration:
    """Steps 1–7: match, canonicalise, route to ``pending_email`` or
    ``pending_review``, issue the token, send the confirmation mail.

    The confirmation mail carries the ballot link and the modification link and
    states that losing it loses the ability to modify the ballot, which
    nonetheless still counts (R-5.6, R-7.6). It carries **no tracking code**:
    the code belongs to a ballot, and no ballot exists yet — issuing one here
    would put the same value on a ``Registration`` row and a ``Ballot`` row,
    which is a join in all but name (§6.2, T-25).
    """
    raise NotImplementedError("§6.2 steps 1–7")


def approve(registration: Registration, note: str = "") -> Registration:
    """Step 5: ``pending_review → pending_email``, never straight to ``active``.

    The mailbox is confirmed in every path. ``note`` is prose and is stored on
    this row, where the retention purge takes it — never on the audit event,
    whose ``reason`` is a code (§10).
    """
    raise NotImplementedError("§6.2 step 5")


@transaction.atomic
def mark_voted(registration_id: str, channel: Channel) -> None:
    """Set ``channel`` in the same transaction as the ballot insert (INV-5, §7).

    This is how "has this person voted" is answered, always. Counting ballots
    to answer it is not available and must not be made available.
    """
    raise NotImplementedError("§6.3")
