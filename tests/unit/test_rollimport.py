# SPDX-License-Identifier: 0BSD
"""Parsing, mapping and validation of §6.1, without a database (§12.1).

``apply_import`` needs the ORM and is covered in
``tests/integration/test_roll_import.py``; everything upstream of it is pure
and is pinned here.
"""

from __future__ import annotations

import io

import openpyxl
import pytest

from apps.elections import rollimport


def _csv(text: str, encoding: str = "utf-8") -> bytes:
    return text.encode(encoding)


def _xlsx(rows: list[list[str]]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# --- read_table: encoding sniffing, and the two accepted formats ------------


def test_reads_utf8_csv() -> None:
    table = rollimport.read_table(_csv("Nom,Prénoms,NNE\nDupont,Émile,123456789\n"), "roll.csv")
    assert table.headers == ["Nom", "Prénoms", "NNE"]
    assert table.rows == [["Dupont", "Émile", "123456789"]]


def test_reads_latin1_csv() -> None:
    """§6.1: UTF-8 and Latin-1 are both accepted and sniffed."""
    table = rollimport.read_table(
        _csv("Nom,Prénoms,NNE\nDupont,Émile,123456789\n", encoding="latin-1"), "roll.csv"
    )
    assert table.rows == [["Dupont", "Émile", "123456789"]]


def test_reads_semicolon_delimited_csv() -> None:
    """A French spreadsheet's default export delimiter."""
    table = rollimport.read_table(_csv("Nom;Prénoms;NNE\nDupont;Émile;123456789\n"), "roll.csv")
    assert table.headers == ["Nom", "Prénoms", "NNE"]


def test_reads_xlsx() -> None:
    data = _xlsx([["Nom", "Prénoms", "NNE"], ["Dupont", "Émile", "123456789"]])
    table = rollimport.read_table(data, "roll.xlsx")
    assert table.headers == ["Nom", "Prénoms", "NNE"]
    assert table.rows == [["Dupont", "Émile", "123456789"]]


def test_xlsx_skips_fully_blank_rows() -> None:
    data = _xlsx([["Nom", "Prénoms", "NNE"], ["", "", ""], ["Dupont", "Émile", "123456789"]])
    table = rollimport.read_table(data, "roll.xlsx")
    assert table.rows == [["Dupont", "Émile", "123456789"]]


def test_arbitrary_bytes_still_parse_as_csv_rather_than_raising() -> None:
    """Latin-1 maps every byte 0-255 to a codepoint, so it never fails to
    decode — there is no "wrong encoding" a CSV can be undecodable in. §6.1's
    real defence against garbage content is the validation report downstream,
    not a decode-time refusal."""
    table = rollimport.read_table(b"\xff\xfe\x00\x01", "roll.csv")
    assert table.headers or table.rows  # something came out; nothing raised


def test_an_empty_file_is_refused_cleanly() -> None:
    with pytest.raises(rollimport.UnreadableFile):
        rollimport.read_table(b"", "roll.csv")


def test_a_corrupt_xlsx_is_refused_cleanly() -> None:
    with pytest.raises(rollimport.UnreadableFile):
        rollimport.read_table(b"not an xlsx file at all", "roll.xlsx")


# --- guess_mapping: convenience only ------------------------------------------


def test_guesses_common_header_names() -> None:
    mapping = rollimport.guess_mapping(["Nom", "Prénoms", "NNE"])
    assert mapping == {"last_name": "Nom", "first_names": "Prénoms", "nne": "NNE"}


def test_guesses_are_accent_and_case_insensitive() -> None:
    mapping = rollimport.guess_mapping(["NOM DE FAMILLE", "prenoms", "Numero National Electeur"])
    assert mapping == {
        "last_name": "NOM DE FAMILLE",
        "first_names": "prenoms",
        "nne": "Numero National Electeur",
    }


def test_an_unmatched_header_is_left_unmapped() -> None:
    """A miss is not an error — screen 3's operator maps it by hand."""
    mapping = rollimport.guess_mapping(["Colonne A", "Colonne B", "Colonne C"])
    assert mapping == {}


# --- apply_mapping -------------------------------------------------------------


def test_apply_mapping_extracts_by_the_chosen_columns() -> None:
    table = rollimport.Table(headers=["A", "B", "C"], rows=[["Dupont", "Émile", "123456789"]])
    rows = rollimport.apply_mapping(table, {"last_name": "A", "first_names": "B", "nne": "C"})
    assert rows == [
        rollimport.MappedRow(index=2, last_name="Dupont", first_names="Émile", nne="123456789")
    ]


def test_apply_mapping_normalises_the_nne() -> None:
    """Whitespace in the NNE column must not create a spurious mismatch
    against the same value typed cleanly at registration (§6.2 step 2)."""
    table = rollimport.Table(headers=["N"], rows=[[" 1234 5678 "]])
    rows = rollimport.apply_mapping(table, {"nne": "N"})
    assert rows[0].nne == "12345678"


def test_apply_mapping_tolerates_a_short_row() -> None:
    """A ragged row from a hand-edited CSV must not crash the import."""
    table = rollimport.Table(headers=["A", "B", "C"], rows=[["Dupont"]])
    rows = rollimport.apply_mapping(table, {"last_name": "A", "first_names": "B", "nne": "C"})
    assert rows == [rollimport.MappedRow(index=2, last_name="Dupont", first_names="", nne="")]


def test_row_index_matches_the_spreadsheet_row_number() -> None:
    """Row 1 is the header; the first data row is what a spreadsheet calls 2."""
    table = rollimport.Table(headers=["A"], rows=[["x"], ["y"]])
    rows = rollimport.apply_mapping(table, {"last_name": "A"})
    assert [r.index for r in rows] == [2, 3]


# --- validate: the four report categories -------------------------------------


def _row(
    index: int,
    last_name: str = "Dupont",
    first_names: str = "Émile",
    nne: str = "123456789",
) -> rollimport.MappedRow:
    return rollimport.MappedRow(index=index, last_name=last_name, first_names=first_names, nne=nne)


def test_a_clean_roll_reports_nothing() -> None:
    report = rollimport.validate([_row(2), _row(3, last_name="Martin", nne="987654321")])
    assert report.clean
    assert not report.blocking


def test_a_missing_field_is_reported_and_blocks() -> None:
    report = rollimport.validate([_row(2, nne="")])
    assert report.missing_fields == [_row(2, nne="")]
    assert report.blocking


def test_t11_a_malformed_nne_is_reported_and_blocks_the_whole_import() -> None:
    report = rollimport.validate([_row(2, nne="12"), _row(3)])
    assert report.malformed_nne == [_row(2, nne="12")]
    assert report.blocking


def test_a_malformed_nne_is_not_also_counted_as_missing() -> None:
    """The two categories must not double-count the same row."""
    report = rollimport.validate([_row(2, nne="12")])
    assert report.missing_fields == []
    assert len(report.malformed_nne) == 1


def test_a_blank_nne_is_missing_not_malformed() -> None:
    report = rollimport.validate([_row(2, nne="")])
    assert report.malformed_nne == []
    assert len(report.missing_fields) == 1


def test_a_duplicate_nne_is_reported_and_blocks() -> None:
    rows = [_row(2, nne="123456789"), _row(3, last_name="Martin", nne="123456789")]
    report = rollimport.validate(rows)
    assert report.duplicate_nne == rows
    assert report.blocking


def test_the_same_name_under_two_nnes_is_reported_but_does_not_block() -> None:
    """Informational only: two electors can share a name (R-5.4's reasoning,
    applied here)."""
    a, b = _row(2, nne="123456789"), _row(3, nne="987654321")
    report = rollimport.validate([a, b])
    assert report.duplicate_name_nne_mismatch == [(a, b)]
    assert not report.blocking


def test_diacritics_and_case_do_not_create_a_false_mismatch() -> None:
    a = _row(2, last_name="DUPONT", first_names="EMILE", nne="123456789")
    b = _row(3, last_name="dupont", first_names="émile", nne="987654321")
    report = rollimport.validate([a, b])
    assert report.duplicate_name_nne_mismatch == [(a, b)]
