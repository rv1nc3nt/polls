# SPDX-License-Identifier: 0BSD
"""Name and address comparison for registration matching (§6.2, R-5.3).

Pure functions, tested without a database (T-40, T-41). The comparison decides
between ``pending_email`` and ``pending_review``; it never refuses a
registration on its own, so a false negative costs a human review and a false
positive is the one to avoid.
"""

from __future__ import annotations

import re
import unicodedata

# Particles are dropped before comparison: rolls and self-declarations disagree
# about them constantly ("de La Fontaine" / "Lafontaine" stays a divergence, but
# "De Broglie" / "de Broglie" must not be one).
PARTICLES = frozenset(
    {"de", "du", "des", "d", "le", "la", "les", "van", "von", "der", "den", "el", "al", "di", "da"}
)

_APOSTROPHES = dict.fromkeys(map(ord, "’ʼ`´"), "'")
_SEPARATORS = re.compile(r"[\s\-_'.]+")


def strip_diacritics(text: str) -> str:
    """NFKD, then drop combining marks. ``Émile`` and ``Emile`` agree."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalise_name_part(text: str) -> str:
    """One name component reduced to its comparison form."""
    text = text.translate(_APOSTROPHES)
    text = strip_diacritics(text)
    return text.casefold()


def name_tokens(text: str) -> frozenset[str]:
    """The comparison tokens of a name: order-insensitive, particle-free.

    Hyphens, apostrophes, dots and runs of whitespace all split, so
    ``Jean-Pierre``, ``Jean Pierre`` and ``jean pierre`` agree, and so do
    ``Marie-Claire Dupont`` and ``Dupont Claire Marie``.
    """
    parts = _SEPARATORS.split(normalise_name_part(text))
    return frozenset(p for p in parts if p and p not in PARTICLES)


def names_match(declared_last: str, declared_first: str, roll_last: str, roll_first: str) -> bool:
    """Whether a self-declared name is consistent with the roll entry (R-5.3).

    Last names must agree as sets. First names agree if either side's tokens are
    a subset of the other's: a roll holding every given name ("Marie Claire
    Josèphe") and a person writing one of them ("Marie") is the common case, and
    it is a match; a person writing a name absent from the roll is not.
    """
    if name_tokens(declared_last) != name_tokens(roll_last):
        return False
    declared = name_tokens(declared_first)
    roll = name_tokens(roll_first)
    if not declared or not roll:
        return declared == roll
    return declared <= roll or roll <= declared


def canonical_email(address: str) -> str:
    """The address lower-cased and stripped, nothing more (§3.3).

    Deliberately no alias normalisation: ``+suffix`` and dot handling are
    provider conventions, and any rule about them either merges distinct people
    or gives false assurance about the ones it misses (T-41).
    """
    return address.strip().lower()


NNE_PATTERN = re.compile(r"^\d{8,9}$")


def normalise_nne(value: str) -> str:
    """An NNE with its whitespace removed. Validation is separate."""
    return re.sub(r"\s+", "", value.strip())


def is_valid_nne(value: str) -> bool:
    """8 or 9 digits (§2). Format only — the roll decides whether it exists."""
    return bool(NNE_PATTERN.match(value))
