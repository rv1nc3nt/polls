# SPDX-License-Identifier: 0BSD
"""Distinct types over ``bytes`` and ``str``.

§5.1: ``VoterHash`` and ``BallotHash`` are separate ``NewType``s with no
conversion between them, so ``mypy --strict`` catches argument confusion at
check time — the one property the abandoned typestate design transfers.
``Token`` redacts itself in ``repr`` and is never interpolated into a log line.
"""

from __future__ import annotations

from typing import NewType

VoterHash = NewType("VoterHash", bytes)
BallotHash = NewType("BallotHash", bytes)
TokenSalt = NewType("TokenSalt", bytes)
TrackingCode = NewType("TrackingCode", str)
OptionId = NewType("OptionId", str)


class Token(str):
    """A voter's ballot token (§7). Never persisted, never logged.

    Subclasses ``str`` so it can be used where the URL and the hash input need
    it, but ``__repr__`` and ``__str__`` redact: an accidental ``f"{token}"`` in
    a log line is the failure this type exists to prevent. Use
    ``token.reveal()`` at the two places that legitimately need the value — the
    confirmation email and the hash functions of ``crypto``.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "<Token redacted>"

    def __str__(self) -> str:
        return "<Token redacted>"

    def __format__(self, format_spec: str) -> str:
        return "<Token redacted>"

    def reveal(self) -> str:
        """The token's plaintext. Two legitimate callers: mail and crypto."""
        return str.__str__(self)
