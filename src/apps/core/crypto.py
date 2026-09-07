# SPDX-License-Identifier: 0BSD
"""The anonymity scheme of §7, implemented exactly as specified.

    token        = 256 bits from a CSPRNG, base32-encoded
    voter_hash   = SHA256("voter"  || poll.token_salt || token)
    ballot_hash  = SHA256("ballot" || poll.token_salt || token)

Byte-level reading of ``||``, fixed here so the two hashes stay reproducible:
the domain prefix is its ASCII bytes, ``token_salt`` its 32 raw bytes, and the
token its base32 ASCII text (the form the voter receives), un-padded and
upper-case. Nothing else is concatenated; there is no separator, and the domain
prefixes ``voter``/``ballot`` differ in their first byte, so no two inputs
collide by re-parsing.

The plaintext token is never persisted: not in the database, not in a log, and
the confirmation mail is the only place it is written out.
"""

from __future__ import annotations

import base64
import hashlib
import secrets

from .types import BallotHash, Token, TokenSalt, VoterHash

TOKEN_BITS = 256
SALT_BYTES = 32
_VOTER_DOMAIN = b"voter"
_BALLOT_DOMAIN = b"ballot"


def new_token() -> Token:
    """A fresh 256-bit token from the system CSPRNG, base32 without padding."""
    raw = secrets.token_bytes(TOKEN_BITS // 8)
    return Token(base64.b32encode(raw).decode("ascii").rstrip("="))


def new_token_salt() -> TokenSalt:
    """A poll's per-poll salt (§3.1). Generated at creation, never published."""
    return TokenSalt(secrets.token_bytes(SALT_BYTES))


def new_opening_seed() -> bytes:
    """A poll's opening seed (§3.1). Generated at ``open``, published."""
    return secrets.token_bytes(SALT_BYTES)


def _digest(domain: bytes, salt: TokenSalt, token: Token) -> bytes:
    return hashlib.sha256(domain + bytes(salt) + token.reveal().encode("ascii")).digest()


def voter_hash(salt: TokenSalt, token: Token) -> VoterHash:
    """The value stored on the ``Registration`` row (§7)."""
    return VoterHash(_digest(_VOTER_DOMAIN, salt, token))


def ballot_hash(salt: TokenSalt, token: Token) -> BallotHash:
    """The value stored on an online ``Ballot`` row (§7).

    Not computed at all where ``allow_ballot_modification`` is false: the
    token → ballot link exists only to serve modification, and omitting it is
    what makes that configuration the closest approach to a secret ballot.
    Callers must check the flag; this function does not know the poll.
    """
    return BallotHash(_digest(_BALLOT_DOMAIN, salt, token))
