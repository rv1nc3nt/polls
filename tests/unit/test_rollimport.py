# SPDX-License-Identifier: 0BSD
"""Parsing, mapping, validation and collapse of §6.1, without a database (§12.1).

``apply_import`` needs the ORM and is covered in
``tests/integration/test_roll_import.py``; everything upstream of it is pure and
is pinned here, including T-60's collapse step.
"""

from __future__ import annotations

import io
from datetime import date

import openpyxl
import pytest

from apps.elections import rollimport

HEADER = "Nom de naissance;Nom d'usage;Prénoms;Date de naissance;Type de liste"
FULL_MAPPING = {
    "birth_name": "Nom de naissance",
    "usual_name": "Nom d'usage",
    "first_names": "Prénoms",
    "date_of_birth": "Date de naissance",
    "list_type": "Type de liste",
}


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
    table = rollimport.read_table(
        _csv(f"{HEADER}\nDupont;;Émile;14/03/1962;Liste principale\n"), "roll.csv"
    )
    assert table.headers == HEADER.split(";")
    assert table.rows == [["Dupont", "", "Émile", "14/03/1962", "Liste principale"]]


def test_reads_latin1_csv() -> None:
    """§6.1: UTF-8 and Latin-1 are both accepted and sniffed."""
    table = rollimport.read_table(
        _csv(f"{HEADER}\nDupont;;Émile;14/03/1962;Liste principale\n", encoding="latin-1"),
        "roll.csv",
    )
    assert table.rows == [["Dupont", "", "Émile", "14/03/1962", "Liste principale"]]


def test_reads_comma_delimited_csv() -> None:
    text = (
        "Nom de naissance,Prénoms,Date de naissance,Type de liste\n"
        "Dupont,Émile,14/03/1962,Liste principale\n"
    )
    table = rollimport.read_table(_csv(text), "roll.csv")
    assert table.headers[0] == "Nom de naissance"


def test_reads_xlsx() -> None:
    data = _xlsx(
        [
            ["Nom de naissance", "Prénoms", "Date de naissance", "Type de liste"],
            ["Dupont", "Émile", "14/03/1962", "Liste principale"],
        ]
    )
    table = rollimport.read_table(data, "roll.xlsx")
    assert table.rows == [["Dupont", "Émile", "14/03/1962", "Liste principale"]]


def test_arbitrary_bytes_still_parse_as_csv_rather_than_raising() -> None:
    table = rollimport.read_table(b"\xff\xfe\x00\x01", "roll.csv")
    assert table.headers or table.rows


def test_an_empty_file_is_refused_cleanly() -> None:
    with pytest.raises(rollimport.UnreadableFile):
        rollimport.read_table(b"", "roll.csv")


# --- guess_mapping ---------------------------------------------------------


def test_guesses_common_header_names() -> None:
    mapping = rollimport.guess_mapping(HEADER.split(";"))
    assert mapping == FULL_MAPPING


def test_guesses_are_accent_and_case_insensitive() -> None:
    mapping = rollimport.guess_mapping(
        [
            "NOM DE NAISSANCE",
            "nom d'usage",
            "prenoms",
            "Date De Naissance",
            "Libellé du type de liste",
        ]
    )
    assert set(mapping) == set(rollimport.FIELDS)


def test_an_unmatched_header_is_left_unmapped() -> None:
    assert rollimport.guess_mapping(["Colonne A", "Colonne B"]) == {}


# --- apply_mapping -------------------------------------------------------------


def test_apply_mapping_extracts_by_the_chosen_columns() -> None:
    table = rollimport.Table(
        headers=["A", "B", "C", "D", "E"],
        rows=[["Dupont", "Ravanel", "Émile", "14/03/1962", "Liste principale"]],
    )
    rows = rollimport.apply_mapping(
        table,
        {
            "birth_name": "A",
            "usual_name": "B",
            "first_names": "C",
            "date_of_birth": "D",
            "list_type": "E",
        },
    )
    assert rows == [
        rollimport.MappedRow(
            index=2,
            birth_name="Dupont",
            usual_name="Ravanel",
            first_names="Émile",
            date_of_birth="14/03/1962",
            list_type="Liste principale",
        )
    ]


def test_apply_mapping_tolerates_a_short_row() -> None:
    table = rollimport.Table(headers=["A", "B", "C", "D", "E"], rows=[["Dupont"]])
    rows = rollimport.apply_mapping(
        table,
        {
            "birth_name": "A",
            "usual_name": "B",
            "first_names": "C",
            "date_of_birth": "D",
            "list_type": "E",
        },
    )
    assert rows[0].birth_name == "Dupont"
    assert rows[0].first_names == ""


def test_row_index_matches_the_spreadsheet_row_number() -> None:
    table = rollimport.Table(headers=["A"], rows=[["x"], ["y"]])
    rows = rollimport.apply_mapping(table, {"birth_name": "A"})
    assert [r.index for r in rows] == [2, 3]


# --- list_type_of -----------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Liste principale", "principale"),
        ("Liste complémentaire municipale", "complementaire_municipale"),
        ("Liste complémentaire européenne", "complementaire_europeenne"),
        ("LISTE PRINCIPALE", "principale"),
        ("", None),
        ("quelque chose", None),
    ],
)
def test_list_type_of_maps_the_reu_labels(label: str, expected: str | None) -> None:
    assert rollimport.list_type_of(label) == expected


# --- collapse (T-60) ------------------------------------------------------


def _row(
    index: int,
    birth_name: str = "Dupont",
    usual_name: str = "",
    first_names: str = "Émile",
    date_of_birth: str = "14/03/1962",
    list_type: str = "Liste principale",
) -> rollimport.MappedRow:
    return rollimport.MappedRow(
        index=index,
        birth_name=birth_name,
        usual_name=usual_name,
        first_names=first_names,
        date_of_birth=date_of_birth,
        list_type=list_type,
    )


def test_t60_one_elector_on_two_lists_collapses_to_one_entry() -> None:
    result = rollimport.collapse(
        [
            _row(2, list_type="Liste complémentaire municipale"),
            _row(3, list_type="Liste complémentaire européenne"),
        ]
    )
    assert len(result.entries) == 1
    entry = result.entries[0]
    assert set(entry.list_types) == {"complementaire_municipale", "complementaire_europeenne"}
    assert entry.source_rows == (2, 3)
    assert result.collapsed == [entry]


def test_t60_a_date_uncertain_row_is_not_collapsed_on_a_parsed_value() -> None:
    result = rollimport.collapse(
        [
            _row(2, date_of_birth="00/00/1953"),
            _row(3, date_of_birth="00/00/1953"),
        ]
    )
    assert len(result.entries) == 2
    assert all(e.date_uncertain for e in result.entries)
    assert all(e.date_of_birth == "00/00/1953" for e in result.entries)


def test_two_rows_identical_including_list_type_do_not_collapse() -> None:
    """Genuine homonyms — same name, same date of birth, same list — stay two
    entries and are flagged, never merged (§6.1, fixture README)."""
    result = rollimport.collapse([_row(2), _row(3)])
    assert len(result.entries) == 2
    assert result.indistinguishable == result.entries
    assert result.collapsed == []


def test_a_certain_date_parses_onto_the_entry() -> None:
    (entry,) = rollimport.collapse([_row(2)]).entries
    assert entry.date_of_birth_parsed == date(1962, 3, 14)
    assert not entry.date_uncertain


# --- validate: what blocks and what only informs -------------------------


def test_a_clean_roll_reports_nothing() -> None:
    report = rollimport.validate(
        [_row(2), _row(3, birth_name="Martin", first_names="Alice", date_of_birth="01/01/1980")],
        FULL_MAPPING,
    )
    assert report.clean
    assert not report.blocking


def test_an_unmapped_mandatory_column_blocks() -> None:
    report = rollimport.validate([_row(2)], {"birth_name": "A", "first_names": "B"})
    assert "date_of_birth" in report.missing_columns
    assert "list_type" in report.missing_columns
    assert report.blocking


def test_usual_name_is_not_a_mandatory_column() -> None:
    mapping_without_usual = {k: v for k, v in FULL_MAPPING.items() if k != "usual_name"}
    report = rollimport.validate([_row(2)], mapping_without_usual)
    assert report.missing_columns == []
    assert not report.blocking


def test_a_row_with_no_name_at_all_blocks() -> None:
    report = rollimport.validate([_row(2, birth_name="", usual_name="")], FULL_MAPPING)
    assert len(report.nameless_rows) == 1
    assert report.blocking


def test_a_row_with_only_a_name_in_use_is_not_nameless() -> None:
    report = rollimport.validate([_row(2, birth_name="", usual_name="Ravanel")], FULL_MAPPING)
    assert report.nameless_rows == []


def test_t63_duplicates_incomplete_rows_and_bad_dates_are_reported_not_blocked() -> None:
    """R-4.5: no missing column, no nameless row → the import succeeds and every
    oddity is listed rather than refused."""
    report = rollimport.validate(
        [
            _row(2, date_of_birth="pas une date"),
            _row(3, birth_name="Martin", first_names="Alice", list_type=""),
            _row(4, birth_name="Noirtier", first_names="Victorin", date_of_birth="30/04/1965"),
            _row(5, birth_name="Noirtier", first_names="Victorin", date_of_birth="30/04/1965"),
        ],
        FULL_MAPPING,
    )
    assert not report.blocking
    assert len(report.date_uncertain) == 1
    assert len(report.incomplete) == 1
    assert len(report.indistinguishable) == 2
