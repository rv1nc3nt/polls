# SPDX-License-Identifier: 0BSD
"""Tracking codes (§3.4).

Human-transcribable: a voter reads one off a receipt or an email and finds
their row in the published CSV. The alphabet excludes ``O``/``0`` and ``I``/``1``
for that reason. Uniqueness per poll is a database constraint (INV-11), because
the canonical serialisation of §9 sorts on this value and a collision would make
the closure hash ambiguous; the generator re-rolls on collision and the caller
retries inside the ballot's transaction.
"""

from __future__ import annotations

import secrets

from .types import TrackingCode

ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
LENGTH = 10
GROUP = 5


def new_tracking_code() -> TrackingCode:
    """A fresh code: 10 characters from a 32-symbol alphabet, ~50 bits."""
    return TrackingCode("".join(secrets.choice(ALPHABET) for _ in range(LENGTH)))


def format_tracking_code(code: TrackingCode) -> str:
    """``ABCDE-FGHJK`` for display and print; the stored value has no dash."""
    text = str(code)
    return "-".join(text[i : i + GROUP] for i in range(0, len(text), GROUP))


def parse_tracking_code(text: str) -> TrackingCode | None:
    """Accept what a person is likely to type: dashes, spaces, lower case."""
    cleaned = text.strip().upper().replace("-", "").replace(" ", "")
    if len(cleaned) != LENGTH or any(c not in ALPHABET for c in cleaned):
        return None
    return TrackingCode(cleaned)
