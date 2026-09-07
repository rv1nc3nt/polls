# SPDX-License-Identifier: 0BSD
"""The drawing of lots (§8.3, R-10.5).

    tiebreak_seed = SHA256(poll.opening_seed || poll.closure_hash)
    order tied options by ascending SHA256(tiebreak_seed || option_id)
    first wins

No language PRNG, no ``random.shuffle``, no ``sort`` with a seeded comparator:
reproducibility must not depend on the runtime, and T-44 is the test that
catches a platform-dependent implementation. The seed depends on the closure
hash and therefore on every ballot cast, so the outcome is unpredictable before
closure and cannot be ground by the organiser (R-10.5 bis).

``option_id`` enters the hash as its UTF-8 bytes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from apps.core.types import OptionId


def tiebreak_seed(opening_seed: bytes, closure_hash: bytes) -> bytes:
    return hashlib.sha256(opening_seed + closure_hash).digest()


def tiebreak_order(
    tied: Sequence[OptionId], opening_seed: bytes, closure_hash: bytes
) -> list[tuple[OptionId, bytes]]:
    """The tied options with their draw values, ascending. Published in full."""
    seed = tiebreak_seed(opening_seed, closure_hash)
    drawn = [
        (option, hashlib.sha256(seed + str(option).encode("utf-8")).digest()) for option in tied
    ]
    drawn.sort(key=lambda pair: pair[1])
    return drawn


def break_tie(tied: Sequence[OptionId], opening_seed: bytes, closure_hash: bytes) -> OptionId:
    """The winner of a computed tie-break. First in the order above."""
    if not tied:
        raise ValueError("break_tie called with no tied options")
    return tiebreak_order(tied, opening_seed, closure_hash)[0][0]
