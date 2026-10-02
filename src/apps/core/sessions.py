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
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any

from django.contrib.sessions.backends.db import SessionStore as DatabaseSessionStore


def _next_midnight(moment: datetime) -> datetime:
    """The first UTC midnight at or after ``moment``."""
    utc = moment.astimezone(UTC)
    midnight = datetime.combine(utc.date(), time.min, tzinfo=UTC)
    return midnight if midnight == utc else midnight + timedelta(days=1)


class SessionStore(DatabaseSessionStore):
    def get_expiry_date(self, **kwargs: Any) -> datetime:
        return _next_midnight(super().get_expiry_date(**kwargs))
