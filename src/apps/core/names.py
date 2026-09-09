# SPDX-License-Identifier: 0BSD
"""Name and date comparison for registration matching (§6.2, R-5.3).

Pure functions, tested without a database (T-40, T-41, T-59). The comparison
decides between ``pending_email`` and ``pending_review``; it never refuses a
registration on its own, so a false negative costs a human review and a false
positive is the one to avoid.

There is no national identifier here any more (R-4.8): a match is a normalised
name tried against **both** the roll's birth surname and its name in use,
together with the date of birth, which carries most of the discriminating power
(R-5.3). The date is parsed by ``parse_dob``; where it will not parse the entry
is flagged ``date_uncertain`` and never matched automatically (R-4.9).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

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


def surname_matches(declared_last: str, roll_birth_name: str, roll_usual_name: str) -> bool:
    """The declared surname tried against **both** roll surnames (R-5.3).

    ``roll_usual_name`` is often blank; when it is, only the birth surname is
    compared. A registrant may write either — a married name or the name on the
    roll — and neither is the wrong answer.
    """
    declared = name_tokens(declared_last)
    if not declared:
        return False
    if declared == name_tokens(roll_birth_name):
        return True
    return bool(roll_usual_name) and declared == name_tokens(roll_usual_name)


def names_match(
    declared_last: str,
    declared_first: str,
    roll_birth_name: str,
    roll_usual_name: str,
    roll_first: str,
) -> bool:
    """Whether a self-declared name is consistent with the roll entry (R-5.3).

    The surname must agree as a set with the birth surname or the name in use
    (``surname_matches``). First names agree if either side's tokens are a
    subset of the other's: a roll holding every given name ("Marie Claire
    Josèphe") and a person writing one of them ("Marie") is the common case, and
    it is a match; a person writing a name absent from the roll is not.
    """
    if not surname_matches(declared_last, roll_birth_name, roll_usual_name):
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


#: Accepted written forms of a date of birth. ``%d/%m/%Y`` is what a REU export
#: and a French registrant both write; the ISO form is accepted so a machine-fed
#: file is not rejected for its punctuation.
_DOB_FORMATS = ("%d/%m/%Y", "%Y-%m-%d")


def parse_dob(raw: str) -> date | None:
    """The date of birth as a ``date``, or ``None`` when it will not parse.

    ``None`` covers an empty cell, a bare year (``1961``), an impossible date
    (``00/00/1953``) and a real date in an unrecognised layout — everything
    R-4.9 keeps verbatim and flags ``date_uncertain``. The raw string is stored
    beside this value, never replaced by it.
    """
    text = raw.strip()
    if not text:
        return None
    for fmt in _DOB_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
