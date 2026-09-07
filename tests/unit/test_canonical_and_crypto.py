# SPDX-License-Identifier: 0BSD
"""T-42 and T-43 — the closure hash and the anonymity scheme (§7, §9)."""

from __future__ import annotations

import hashlib

from apps.core.canonical import (
    CanonicalBallot,
    canonical_record,
    canonical_serialisation,
    closure_hash,
)
from apps.core.crypto import ballot_hash, new_token, voter_hash
from apps.core.types import OptionId, Token, TokenSalt, TrackingCode

SALT = TokenSalt(bytes(range(32)))
TOKEN = Token("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")


def ballot(code: str, *groups: list[str]) -> CanonicalBallot:
    return CanonicalBallot(TrackingCode(code), [[OptionId(o) for o in group] for group in groups])


def test_t42_canonical_record_is_a_fixed_byte_string() -> None:
    record = canonical_record(ballot("AAAAABBBBB", ["a"], ["b"], ["c"]))
    assert record == b'{"tracking_code":"AAAAABBBBB","ranking":[["a"],["b"],["c"]]}'


def test_t42_records_are_newline_separated_and_sorted_by_tracking_code() -> None:
    serialised = canonical_serialisation(
        [ballot("ZZZZZZZZZZ", ["b"], ["a"]), ballot("AAAAAAAAAA", ["a"], ["b"])]
    )
    assert serialised == (
        b'{"tracking_code":"AAAAAAAAAA","ranking":[["a"],["b"]]}\n'
        b'{"tracking_code":"ZZZZZZZZZZ","ranking":[["b"],["a"]]}\n'
    )


def test_t42_tie_groups_are_order_insensitive() -> None:
    """Two orderings of the same tie must not produce two hashes."""
    assert closure_hash([ballot("AAAAAAAAAA", ["b", "a"])]) == closure_hash(
        [ballot("AAAAAAAAAA", ["a", "b"])]
    )


def test_t42_closure_hash_matches_its_stored_value() -> None:
    ballots = [ballot("AAAAAAAAAA", ["a"], ["b"], ["c"]), ballot("BBBBBBBBBB", ["c"], ["b"], ["a"])]
    # The vector below was computed from the two record lines assembled by
    # hand, not from this implementation: it is what a third party recomputing
    # the hash from the published CSV must arrive at (§9, T-10).
    expected = hashlib.sha256(canonical_serialisation(ballots)).digest()
    assert closure_hash(ballots) == expected
    assert closure_hash(ballots).hex() == (
        "87694cf068ba44eca50e15bd4b7c1195fc4a1fae9ad3b0ba640deec22f7948e6"
    )


def test_t42_empty_live_set_still_has_a_closure_hash() -> None:
    assert closure_hash([]) == hashlib.sha256(b"").digest()


def test_t43_voter_and_ballot_hashes_differ_and_are_stable() -> None:
    # ``bytes(...)`` is needed on the first line and is the point: under
    # ``mypy --strict`` a direct ``voter_hash(...) != ballot_hash(...)`` is a
    # non-overlapping comparison, because the two NewTypes are distinct and
    # nothing converts between them (§5.1). The confusion this test guards
    # against at runtime is already a check-time error.
    assert bytes(voter_hash(SALT, TOKEN)) != bytes(ballot_hash(SALT, TOKEN))
    assert voter_hash(SALT, TOKEN) == voter_hash(SALT, TOKEN)
    assert ballot_hash(SALT, TOKEN) == ballot_hash(SALT, TOKEN)


def test_t43_hashes_change_with_the_poll_salt() -> None:
    """§7: token_salt is per poll, so participation cannot be correlated across
    polls by the application (R-13.4)."""
    other = TokenSalt(bytes(range(1, 33)))
    assert voter_hash(SALT, TOKEN) != voter_hash(other, TOKEN)
    assert ballot_hash(SALT, TOKEN) != ballot_hash(other, TOKEN)


def test_token_redacts_itself() -> None:
    """§5.1: Token defines __repr__ to redact and is never interpolated into a
    log message."""
    token = new_token()
    assert "redacted" in repr(token)
    assert "redacted" in f"{token}"
    assert token.reveal() not in f"{token!r} {token} {token:>10}"
