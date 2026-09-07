# SPDX-License-Identifier: 0BSD
"""T-40 and T-41 — name and address comparison (§6.2, R-5.3)."""

from __future__ import annotations

import pytest

from apps.core.names import canonical_email, is_valid_nne, names_match, normalise_nne


@pytest.mark.parametrize(
    ("declared_last", "declared_first", "roll_last", "roll_first"),
    [
        ("Dupont", "Émile", "DUPONT", "Emile"),  # diacritics and case
        ("de Broglie", "Louis", "De Broglie", "Louis"),  # particle
        ("Broglie", "Louis", "de Broglie", "Louis"),  # particle absent one side
        ("Martin", "Jean-Pierre", "Martin", "Jean Pierre"),  # hyphen
        ("Martin", "Pierre Jean", "Martin", "Jean Pierre"),  # first-name order
        ("O'Brien", "Marie", "O’Brien", "Marie"),  # apostrophe glyph
        ("Martin", "Marie", "Martin", "Marie Claire Josephe"),  # subset of given names
    ],
)
def test_t40_normalisation_matches_the_same_person(
    declared_last: str, declared_first: str, roll_last: str, roll_first: str
) -> None:
    assert names_match(declared_last, declared_first, roll_last, roll_first)


@pytest.mark.parametrize(
    ("declared_last", "declared_first", "roll_last", "roll_first"),
    [
        ("Dupond", "Jean", "Dupont", "Jean"),  # one letter apart
        ("Martin", "Claire", "Martin", "Marie"),
        ("Lafontaine", "Jean", "de La Fontaine", "Jean"),
        ("Martin", "", "Martin", "Jean"),  # nothing declared is not a match
    ],
)
def test_t40_genuinely_different_names_do_not_collide(
    declared_last: str, declared_first: str, roll_last: str, roll_first: str
) -> None:
    assert not names_match(declared_last, declared_first, roll_last, roll_first)


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


def test_nne_format() -> None:
    assert is_valid_nne("12345678")
    assert is_valid_nne("123456789")
    assert not is_valid_nne("1234567")
    assert not is_valid_nne("12345678A")
    assert normalise_nne(" 1234 5678 ") == "12345678"
