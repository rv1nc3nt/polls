# SPDX-License-Identifier: 0BSD
"""Canonical serialisation of the live ballot set and the closure hash (§9).

``json.dumps`` defaults are not a canonicalisation guarantee, so the bytes are
produced explicitly here. A third party must be able to recompute the hash from
the published CSV alone; ``docs/canonical-serialisation.md`` states the same
rules in prose, and the Rust verifier implements them independently.

The rules, in full:

1.  The set is exactly the ballots with ``status = live`` (§3.4). Superseded,
    deleted and ``pending_countersign`` rows are excluded, without exception.
2.  A ranking is a list of groups, each group a list of option **ids** — never
    labels (§3.8): the hash is built from ids alone and is independent of the
    labels and their translations. A strict ranking is a list of one-element
    groups. Ids within a group are sorted by code point, since a tie is
    unordered and two orderings of the same tie must not produce two hashes.
3.  A record is the JSON object ``{"tracking_code": …, "ranking": …}`` with the
    keys in that order, no insignificant whitespace (separators ``,`` and
    ``:``), non-ASCII left as UTF-8 rather than escaped.
4.  Records are sorted by tracking code, ascending, comparing UTF-8 bytes. The
    tracking-code alphabet is ASCII, so this is the obvious ordering; it is
    stated because it is what the verifier must match. INV-11 makes the key
    unique, so the sort is total.
5.  Each record is followed by ``\\n``, including the last. The serialisation
    is the concatenation of those lines, UTF-8.
6.  ``closure_hash = SHA256`` of those bytes. An empty live set serialises to
    zero bytes and hashes to SHA256 of the empty string — a poll with no
    ballots still has a closure hash.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence

from .types import OptionId, TrackingCode

Ranking = Sequence[Sequence[OptionId]]


class CanonicalBallot:
    """One row of the live ballot set, as the serialiser sees it."""

    __slots__ = ("ranking", "tracking_code")

    def __init__(self, tracking_code: TrackingCode, ranking: Ranking) -> None:
        self.tracking_code = tracking_code
        self.ranking = ranking


def canonical_record(ballot: CanonicalBallot) -> bytes:
    """Rule 2 and 3: one ballot as its canonical JSON object, without newline."""
    ranking = [sorted(group) for group in ballot.ranking]
    payload = {"tracking_code": str(ballot.tracking_code), "ranking": ranking}
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_serialisation(ballots: Iterable[CanonicalBallot]) -> bytes:
    """Rules 4 and 5: the whole live set as the bytes the closure hash covers."""
    ordered = sorted(ballots, key=lambda b: str(b.tracking_code).encode("utf-8"))
    return b"".join(canonical_record(b) + b"\n" for b in ordered)


def closure_hash(ballots: Iterable[CanonicalBallot]) -> bytes:
    """Rule 6 (§9). Computed on entry to ``closed``, published, verifier-checked."""
    return hashlib.sha256(canonical_serialisation(ballots)).digest()
