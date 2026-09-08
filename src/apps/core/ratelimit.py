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


def client_digest(request: HttpRequest) -> str:
    """A stable, non-reversible handle for the caller.

    ``X-Forwarded-For``'s first entry is the client where nginx sets it (§14);
    trusting it unconditionally would let anyone forge the header and evade the
    limit, so it is read only when the proxy header configuration says there is
    a proxy in front. Salted with ``SECRET_KEY`` so the digest is meaningless
    outside this instance (R-13.5).
    """
    address = request.META.get("REMOTE_ADDR", "")
    if getattr(settings, "SECURE_PROXY_SSL_HEADER", None):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            address = forwarded.split(",")[0].strip()
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
    return Limit.parse(settings.RATE_LIMIT_REGISTRATION)


def email_limit() -> Limit:
    return Limit.parse(settings.RATE_LIMIT_EMAIL)
