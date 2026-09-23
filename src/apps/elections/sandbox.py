# SPDX-License-Identifier: 0BSD
"""Sandbox polls (R-3.7): reaching one without being public, and deleting one.

A sandbox poll is a rehearsal — it runs the whole lifecycle so that everything
can be checked with real ballots, and counts for nothing. It is kept off every
public page, listing, result and statistic (INV-8), yet must stay reachable by
the people asked to try it out. Two things open it to a browser:

* the poll's share link (``sharelink``), which leads to the poll page and the
  registration form. The session remembers *which token* was presented, not
  merely that one was, so regenerating or revoking the link ends the access of
  everyone who arrived through the old one;
* a valid voter token on the ballot routes. The confirmation mail is sent to a
  tester who registered through the link and the token in it is already a
  secret only they hold, so it needs no second one; what it opens is remembered
  so the token-free pages that follow (§6.3) still resolve.

Neither stores a voter reference: the session holds a poll id and the share
token, which identifies a link, not a person (INV-1).

**Deletion is the one place a poll leaves the database.** It is confined to
sandbox polls by ``inv3_poll_no_delete`` and by the sandbox exemption in the
delete triggers of INV-2, INV-3, INV-6 and INV-7 (elections migration 0013) —
the application check below only produces the good error message. The audit
log is never touched: its events stay, naming a poll that no longer exists
(INV-3).
"""

from __future__ import annotations

import secrets
from functools import partial

from django.contrib.sessions.backends.base import SessionBase
from django.db import transaction

from apps.audit import services as audit
from apps.audit.models import Action
from apps.ballots.models import PaperBallotLink
from apps.core.models import User
from apps.registrations.models import DuplicateAttempt, Registration

from .models import Poll, RollEntry

_LINK_KEY = "sandbox_link"
_VOTER_KEY = "sandbox_voter"


class NotASandbox(Exception):
    """Deletion was asked of a poll that is not a sandbox poll (R-3.7)."""


def grant_link(session: SessionBase, poll: Poll) -> None:
    """Remember that this browser arrived through the poll's current share link."""
    granted = dict(session.get(_LINK_KEY, {}))
    granted[str(poll.pk)] = poll.preview_token
    session[_LINK_KEY] = granted


def grant_voter(session: SessionBase, poll: Poll) -> None:
    """Remember that this browser presented a valid voter token for the poll."""
    granted = set(session.get(_VOTER_KEY, []))
    granted.add(str(poll.pk))
    session[_VOTER_KEY] = sorted(granted)


def link_granted(session: SessionBase, poll: Poll) -> bool:
    """Is the share link this browser used still the poll's current one?"""
    presented = str(session.get(_LINK_KEY, {}).get(str(poll.pk), ""))
    # A blank ``preview_token`` means no link exists; it must match nothing,
    # including the blank a session never stored.
    return bool(poll.preview_token) and secrets.compare_digest(
        presented.encode(), poll.preview_token.encode()
    )


def may_reach(session: SessionBase, poll: Poll) -> bool:
    """INV-8: may this browser see the voter-facing pages of ``poll``?

    Always for a real poll — its public pages already say what state it is in.
    For a sandbox poll only with the share link or a voter token of its own.
    """
    if not poll.is_sandbox:
        return True
    return link_granted(session, poll) or str(poll.pk) in session.get(_VOTER_KEY, [])


@transaction.atomic
def delete_poll(poll: Poll, *, actor: User) -> None:
    """Delete a sandbox poll and everything it holds, from any state (R-3.7).

    The event is written first, inside the same transaction: had the delete
    raised it would roll back with it, and there is nothing to log after a
    poll that no longer exists. Registrations, roll entries and paper links go
    first, in the order of the retention purge, so that the ``SET_NULL`` on
    ``Registration.roll_entry`` never issues an ``UPDATE`` against a
    registration the INV-2 window would refuse; the rest — ballots, options,
    images, roles, the reconciliation record — cascade from the poll itself.
    Uploaded image files are removed from storage afterwards, and only once the
    database has committed to the deletion.
    """
    if not poll.is_sandbox:
        raise NotASandbox(str(poll.pk))
    files = [
        (image.file.storage, image.file.name) for image in poll.images.all() if image.file.name
    ]
    audit.record(
        action=Action.POLL_DELETED,
        poll=poll,
        actor=actor,
        object_ref=audit.ref(poll),
        # The title is what lets a reader of the log tell which rehearsal this
        # was once the row is gone; it identifies no elector (§10).
        before={"state": str(poll.state), "title": poll.title()},
    )
    PaperBallotLink.objects.filter(poll=poll).delete()
    DuplicateAttempt.objects.filter(poll=poll).delete()
    Registration.objects.filter(poll=poll).delete()
    RollEntry.objects.filter(poll=poll).delete()
    poll.delete()
    for storage, name in files:
        transaction.on_commit(partial(storage.delete, name))
