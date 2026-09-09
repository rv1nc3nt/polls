# SPDX-License-Identifier: 0BSD
"""T-40, T-41 and T-59 — name, address and date-of-birth comparison (§6.2,
R-5.3, R-4.9)."""

from __future__ import annotations

from datetime import date

import pytest

from apps.core.names import canonical_email, names_match, parse_dob, surname_matches


@pytest.mark.parametrize(
    ("declared_last", "declared_first", "birth_name", "usual_name", "roll_first"),
    [
        ("Dupont", "Émile", "DUPONT", "", "Emile"),  # diacritics and case
        ("de Broglie", "Louis", "De Broglie", "", "Louis"),  # particle
        ("Broglie", "Louis", "de Broglie", "", "Louis"),  # particle absent one side
        ("Martin", "Jean-Pierre", "Martin", "", "Jean Pierre"),  # hyphen
        ("Martin", "Pierre Jean", "Martin", "", "Jean Pierre"),  # first-name order
        ("O'Brien", "Marie", "O’Brien", "", "Marie"),  # apostrophe glyph
        ("Martin", "Marie", "Martin", "", "Marie Claire Josephe"),  # subset of given names
        ("Ravanel", "Apolline", "Delavigne", "RAVANEL", "Apolline"),  # name in use, not birth name
        (
            "Delavigne",
            "Apolline",
            "Delavigne",
            "RAVANEL",
            "Apolline",
        ),  # birth name, not name in use
    ],
)
def test_t40_normalisation_matches_the_same_person(
    declared_last: str,
    declared_first: str,
    birth_name: str,
    usual_name: str,
    roll_first: str,
) -> None:
    assert names_match(declared_last, declared_first, birth_name, usual_name, roll_first)


@pytest.mark.parametrize(
    ("declared_last", "declared_first", "birth_name", "usual_name", "roll_first"),
    [
        ("Dupond", "Jean", "Dupont", "", "Jean"),  # one letter apart
        ("Martin", "Claire", "Martin", "", "Marie"),
        ("Lafontaine", "Jean", "de La Fontaine", "", "Jean"),
        ("Martin", "", "Martin", "", "Jean"),  # nothing declared is not a match
        ("Ravanel", "Apolline", "Delavigne", "SOUBEYRAN", "Apolline"),  # neither surname
    ],
)
def test_t40_genuinely_different_names_do_not_collide(
    declared_last: str,
    declared_first: str,
    birth_name: str,
    usual_name: str,
    roll_first: str,
) -> None:
    assert not names_match(declared_last, declared_first, birth_name, usual_name, roll_first)


def test_t40_surname_tried_against_both_roll_surnames() -> None:
    assert surname_matches("Ravanel", "Delavigne", "Ravanel")
    assert surname_matches("Delavigne", "Delavigne", "Ravanel")
    assert not surname_matches("Ravanel", "Delavigne", "")
    assert not surname_matches("Soubeyran", "Delavigne", "Ravanel")


def test_t41_addresses_differing_only_by_case_canonicalise_equal() -> None:
    assert canonical_email("Jean.Dupont@Example.FR") == canonical_email("jean.dupont@example.fr")


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("jean@example.fr", "jean+mairie@example.fr"),  # +suffix is a distinct address
        ("jean.dupont@example.fr", "jeandupont@example.fr"),  # dots are provider convention
    ],
)
def test_t41_aliases_are_treated_as_distinct_addresses(left: str, right: str) -> None:
    """§3.3: no alias normalisation. Any rule about them either merges distinct
    people or gives false assurance about the ones it misses."""
    assert canonical_email(left) != canonical_email(right)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("14/03/1962", date(1962, 3, 14)),  # the well-formed case
        ("1962-03-14", date(1962, 3, 14)),  # ISO, accepted
        (" 14/03/1962 ", date(1962, 3, 14)),  # surrounding whitespace
        ("1961", None),  # a bare year
        ("00/00/1953", None),  # an impossible date
        ("31/02/2000", None),  # a date that does not exist
        ("", None),  # an empty cell
        ("le 3 mars", None),  # free text
    ],
)
def test_t59_parse_dob(raw: str, expected: date | None) -> None:
    """R-4.9: the well-formed one parses; everything else returns ``None`` and
    the caller keeps the raw string and flags ``date_uncertain``."""
    assert parse_dob(raw) == expected
