# SPDX-License-Identifier: 0BSD
"""Rate limiting for the registration and mail endpoints (R-5.8, §6.2 step 9).

Counting happens in Django's cache. There is no Redis and no queue (§14), and a
commune-sized instance does not need one; the cost is that the default
``LocMemCache`` counts per process, so production configures the database
backend and the limit is only as good as that configuration. That is stated in
``settings/base.py`` beside the setting rather than left to be discovered.

**No IP address is stored.** R-13.5 keeps addresses only as long as
rate-limiting requires, so the counter is keyed on a salted digest of the
address and the cache entry expires with the window. Nothing anywhere can turn a
key back into an address, which also means the limiter cannot be used as a
by-the-back-door log of who visited.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.http import HttpRequest

_SPEC = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*([smhd])\s*$")
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


@dataclass(frozen=True)
class Limit:
    """``count`` actions permitted per ``window`` seconds."""

    count: int
    window: int

    @classmethod
    def parse(cls, spec: str) -> Limit:
        """``"5/1h"`` — five per hour. The form the settings use (§13)."""
        match = _SPEC.match(spec)
        if not match:
            raise ValueError(f"unparsable rate limit: {spec!r}")
        count, amount, unit = match.groups()
        return cls(count=int(count), window=int(amount) * _UNITS[unit])


def _serialised() -> transaction.Atomic:
    """The block an increment runs in (review A-4).

    ``cache.incr`` is a read then a write, on every backend but LocMem's, so
    two requests could read the same count and both write it plus one,
    undercounting a burst. Production's ``DatabaseCache`` lives in the
    application's database, whose transactions are ``IMMEDIATE``
    (``settings/base.py``): the block takes the write lock before the read,
    so concurrent increments run one after the other."""
    return transaction.atomic()


def client_digest(request: HttpRequest) -> str:
    """A stable, non-reversible handle for the caller.

    Behind the proxy (``SECURE_PROXY_SSL_HEADER`` set), the address is read from
    ``X-Forwarded-For`` counting from the **right**: nginx *appends* the address
    it saw (``$proxy_add_x_forwarded_for``, §14), so everything left of that is
    whatever the client chose to send. With ``TRUSTED_PROXY_HOPS`` proxies in
    front, each appending, the entry that many places from the end is the
    first one no client could write. Reading the first entry instead let any
    client evade the limit, or fill someone else's (review note M3). Salted
    with ``SECRET_KEY`` so the digest is meaningless outside this instance
    (R-13.5).
    """
    address = request.META.get("REMOTE_ADDR", "")
    if getattr(settings, "SECURE_PROXY_SSL_HEADER", None):
        entries = [
            e.strip() for e in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if e.strip()
        ]
        if entries:
            hops = max(1, settings.TRUSTED_PROXY_HOPS)
            address = entries[max(0, len(entries) - hops)]
    salted = f"{settings.SECRET_KEY}:{address}".encode()
    return hashlib.sha256(salted).hexdigest()[:32]


def allow(bucket: str, request: HttpRequest, limit: Limit) -> bool:
    """Count one action, and say whether it is within the limit.

    Increments even when refusing: a caller hammering the endpoint keeps their
    own window full, which is the behaviour wanted. Fails **open** if the cache
    is unavailable — a broken cache must not make registration impossible, and
    the endpoint has other defences (INV-4, INV-10, the honour declaration).
    """
    key = f"ratelimit:{bucket}:{client_digest(request)}"
    try:
        with _serialised():
            cache.add(key, 0, timeout=limit.window)
            return int(cache.incr(key)) <= limit.count
    except ValueError:
        # The entry expired between `add` and `incr`; this attempt starts a
        # fresh window.
        cache.set(key, 1, timeout=limit.window)
        return True
    except Exception:  # a cache outage must not close registration
        return True


def registration_limit() -> Limit:
    """``settings.RATE_LIMIT_REGISTRATION``, parsed on every call (so
    ``override_settings`` takes effect). Raises ``ValueError`` if malformed."""
    return Limit.parse(settings.RATE_LIMIT_REGISTRATION)


def email_limit() -> Limit:
    """``settings.RATE_LIMIT_EMAIL``, parsed like ``registration_limit``."""
    return Limit.parse(settings.RATE_LIMIT_EMAIL)


# --- sign-in failures (review A-7) ---------------------------------------------
#
# Unlike ``allow``, which counts every attempt, these count only *failures*:
# an operator who signs in correctly costs nothing, and one locked out is
# locked out by wrong passwords alone. Two counters, by caller and by account:
# the first stops one address guessing at many accounts, the second one
# account being guessed from many addresses. The second can be used to keep an
# operator out on purpose, which is why its window is wider than the first's
# and its count higher (decision log #43). Both fail open, like ``allow``.


def account_digest(username: str) -> str:
    """The account a sign-in names, salted like ``client_digest``, case-folded
    so ``Admin`` and ``admin`` share one counter."""
    salted = f"{settings.SECRET_KEY}:account:{username.strip().casefold()}".encode()
    return hashlib.sha256(salted).hexdigest()[:32]


def exceeded(bucket: str, ident: str, limit: Limit) -> bool:
    """Whether ``ident`` has already used up ``limit`` in ``bucket``."""
    try:
        return int(cache.get(f"ratelimit:{bucket}:{ident}", 0)) >= limit.count
    except Exception:  # a cache outage must not lock every operator out
        return False


def count_failure(bucket: str, ident: str, limit: Limit) -> None:
    """Record one failure for ``ident`` in ``bucket``."""
    key = f"ratelimit:{bucket}:{ident}"
    try:
        with _serialised():
            cache.add(key, 0, timeout=limit.window)
            cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=limit.window)
    except Exception:  # noqa: S110 — fail open, as above
        pass


def clear(bucket: str, ident: str) -> None:
    """Forget ``ident``'s failures in ``bucket``: a correct sign-in."""
    try:
        cache.delete(f"ratelimit:{bucket}:{ident}")
    except Exception:  # noqa: S110 — fail open, as above
        pass


def login_address_limit() -> Limit:
    """``settings.RATE_LIMIT_LOGIN_ADDRESS``: failures per caller."""
    return Limit.parse(settings.RATE_LIMIT_LOGIN_ADDRESS)


def login_account_limit() -> Limit:
    """``settings.RATE_LIMIT_LOGIN_ACCOUNT``: failures per account named."""
    return Limit.parse(settings.RATE_LIMIT_LOGIN_ACCOUNT)
