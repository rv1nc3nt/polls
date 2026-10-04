# SPDX-License-Identifier: 0BSD
"""The session store: Django's database backend, with expiry dates to the day.

The session table records when each session was last saved, as its expiry date
(that instant plus ``SESSION_COOKIE_AGE``). A voter's session is saved in the
request that casts their ballot — it then holds the receipt shown after the
redirect (``tokensession``) — so its expiry, to the microsecond, would date the
ballot and line it up with the registration confirmed just before it (INV-1,
decision log #42). Rounding it up to the next midnight, UTC, keeps only the day.
Every session gets it, the back office's too: a session lasting until the end
of its last day costs nothing.

The table keeps no insertion order either (``WITHOUT ROWID``, core migration
0011): the voter's row holds their tracking code or ballot hash, and its place
in an ordinary table would list ballots in the order they were cast (decision
log #53). Django never deletes an expired row by itself, so the daily
``retention_purge`` does (``purge_expired``): a receipt is no use past its
session's life.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any, override

from django.contrib.sessions.backends.db import SessionStore as DatabaseSessionStore
from django.utils import timezone


def _next_midnight(moment: datetime) -> datetime:
    """The first UTC midnight at or after ``moment``."""
    utc = moment.astimezone(UTC)
    midnight = datetime.combine(utc.date(), time.min, tzinfo=UTC)
    return midnight if midnight == utc else midnight + timedelta(days=1)


class SessionStore(DatabaseSessionStore):
    """Django's database sessions, with every expiry rounded up to midnight
    UTC: an exact expiry dates the request that saved the session, and the
    one that saves it at casting would date the ballot (INV-1)."""

    @override
    def get_expiry_date(self, **kwargs: Any) -> datetime:
        return _next_midnight(super().get_expiry_date(**kwargs))


def purge_expired() -> int:
    """Delete every expired session and say how many went.

    ``clearsessions`` does the same but reports nothing, and nothing scheduled
    it: expired receipts and ballot hashes stayed in the table for good."""
    deleted, _by_model = (
        SessionStore.get_model_class().objects.filter(expire_date__lt=timezone.now()).delete()
    )
    return deleted
