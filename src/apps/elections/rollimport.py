# SPDX-License-Identifier: 0BSD
"""Roll import (§6.1, R-4.2, R-4.5): parsing, mapping, validation, and the
transactional apply.

Parsing and validation are pure — a byte string in, a dataclass out — so they
are testable without a request, an uploaded file or a database (§12.1). The one
function that writes, ``apply_import``, is the service screen 3 and the
``import_roll`` command both call: sharing it is what keeps "all-or-nothing"
(T-11) and "replaces the working roll entirely" (T-26) meaning the same thing
in the UI and on the terminal.

``WorkingRollEntry`` is commune-wide, not poll-scoped (§3.2): screen 3 is
reached from one poll's back-office, gated by that poll's roles, but what it
replaces is shared by every poll still in ``draft``. That is the design — a
second import a week later should not require re-entering electors who have not
changed — and the confirmation screen says so, since a consequence reaching
outside the poll the operator is looking at is exactly what an explicit
confirmation (R-4.5) exists to surface.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from typing import Any

import openpyxl
from django.db import transaction
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from apps.audit import services as audit
from apps.audit.models import Action
from apps.core.models import User
from apps.core.names import is_valid_nne, name_tokens, normalise_nne, strip_diacritics

from .models import RollImport, WorkingRollEntry

#: The three fields §6.1's column mapping UI resolves. Order is display order.
FIELDS: tuple[str, ...] = ("last_name", "first_names", "nne")
FIELD_LABELS = {
    "last_name": _lazy("Nom"),
    "first_names": _lazy("Prénoms"),
    "nne": _lazy("NNE"),
}

#: Header text (accent- and case-insensitive) guessed against each field, for
#: convenience only (§6.1's mapping UI). A miss is not an error — it just
#: leaves that field for the operator to map by hand.
_GUESS_HEADERS: dict[str, frozenset[str]] = {
    "last_name": frozenset({"nom", "nom de famille", "last name", "last_name", "surname"}),
    "first_names": frozenset(
        {"prenom", "prenoms", "prénom", "prénoms", "first name", "first names", "first_names"}
    ),
    "nne": frozenset(
        {
            "nne",
            "numero national electeur",
            "numéro national électeur",
            "national elector number",
        }
    ),
}


class UnreadableFile(ValueError):
    """The upload is neither valid CSV nor a valid .xlsx workbook."""


class RollImportRefused(Exception):
    """``apply_import`` refused: the file failed validation (T-11).

    Carries the report rather than a formatted message, so a caller — the
    command or the back-office view — decides how to show it; neither is
    forced through the other's rendering.
    """

    def __init__(self, report: ValidationReport) -> None:
        super().__init__(_("Le fichier contient des lignes invalides."))
        self.report = report


@dataclass(frozen=True)
class Table:
    """A file's rows, before any field mapping is applied."""

    headers: list[str]
    rows: list[list[str]]


def file_digest(data: bytes) -> str:
    """SHA-256 of the uploaded bytes, hex — logged per §6.1, never the content."""
    return hashlib.sha256(data).hexdigest()


def read_table(data: bytes, filename: str) -> Table:
    """§6.1: accept .xlsx and .csv, UTF-8 or Latin-1, sniffed and confirmed."""
    if filename.lower().endswith(".xlsx"):
        return _read_xlsx(data)
    return _read_csv(data)


def _read_xlsx(data: bytes) -> Table:
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        sheet = workbook.active
        if sheet is None:
            raise UnreadableFile(_("Le classeur ne contient aucune feuille."))
        rows_iter = sheet.iter_rows(values_only=True)
        header_row: tuple[Any, ...] = next(rows_iter)
    except UnreadableFile:
        raise
    except StopIteration as exc:
        raise UnreadableFile(_("Le fichier est vide.")) from exc
    except Exception as exc:
        raise UnreadableFile(_("Fichier .xlsx illisible.")) from exc

    headers = [str(cell).strip() if cell is not None else "" for cell in header_row]
    rows = [
        [str(cell).strip() if cell is not None else "" for cell in row]
        for row in rows_iter
        if any(cell not in (None, "") for cell in row)
    ]
    return Table(headers=headers, rows=rows)


def _read_csv(data: bytes) -> Table:
    text = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise UnreadableFile(_("Encodage non reconnu (ni UTF-8 ni Latin-1)."))

    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(
            text[:4096], delimiters=",;\t"
        )
    except csv.Error:
        dialect = csv.excel

    reader = csv.reader(io.StringIO(text), dialect=dialect)
    try:
        headers = [cell.strip() for cell in next(reader)]
    except StopIteration as exc:
        raise UnreadableFile(_("Le fichier est vide.")) from exc
    rows = [[cell.strip() for cell in row] for row in reader if any(cell.strip() for cell in row)]
    return Table(headers=headers, rows=rows)


def _normalise_header(header: str) -> str:
    return strip_diacritics(header).strip().casefold()


def guess_mapping(headers: list[str]) -> dict[str, str]:
    """A first guess at which column is which — never authoritative.

    The operator confirms or corrects it on screen 3 before anything is
    validated; a wrong guess costs a dropdown change, not a bad import.
    """
    mapping: dict[str, str] = {}
    for field_name, candidates in _GUESS_HEADERS.items():
        for header in headers:
            if _normalise_header(header) in candidates:
                mapping[field_name] = header
                break
    return mapping


@dataclass(frozen=True)
class MappedRow:
    """One row, resolved to the three fields the roll needs."""

    #: 1-based, matching the row number a spreadsheet would show the operator
    #: (the header is row 1).
    index: int
    last_name: str
    first_names: str
    nne: str


def apply_mapping(table: Table, mapping: dict[str, str]) -> list[MappedRow]:
    """Extract the three fields using the operator's column choices."""
    columns = {name: table.headers.index(mapping[name]) for name in FIELDS if name in mapping}

    def cell(row: list[str], field_name: str) -> str:
        column = columns.get(field_name)
        if column is None or column >= len(row):
            return ""
        return row[column].strip()

    return [
        MappedRow(
            index=offset + 2,
            last_name=cell(row, "last_name"),
            first_names=cell(row, "first_names"),
            nne=normalise_nne(cell(row, "nne")),
        )
        for offset, row in enumerate(table.rows)
    ]


@dataclass(frozen=True)
class ValidationReport:
    """§6.1's report, minus the personal data staying only on screen: nothing
    here is logged — the audit event records a count, never a row (§10)."""

    missing_fields: list[MappedRow] = field(default_factory=list)
    malformed_nne: list[MappedRow] = field(default_factory=list)
    duplicate_nne: list[MappedRow] = field(default_factory=list)
    #: Same normalised name, different NNE across two rows. Informational: two
    #: electors can share a name, so this is judgement for the operator, the
    #: same way a divergent registration is (R-5.4) — never a block.
    duplicate_name_nne_mismatch: list[tuple[MappedRow, MappedRow]] = field(default_factory=list)

    @property
    def blocking(self) -> bool:
        """§6.1: any of these rejects the whole import outright (T-11)."""
        return bool(self.missing_fields or self.malformed_nne or self.duplicate_nne)

    @property
    def clean(self) -> bool:
        return not (
            self.missing_fields
            or self.malformed_nne
            or self.duplicate_nne
            or self.duplicate_name_nne_mismatch
        )


def validate(rows: list[MappedRow]) -> ValidationReport:
    missing = [r for r in rows if not (r.last_name and r.first_names and r.nne)]
    # Blank NNEs are ``missing``, not ``malformed`` — the two categories must
    # not double-count the same row.
    malformed = [r for r in rows if r.nne and not is_valid_nne(r.nne)]

    by_nne: dict[str, list[MappedRow]] = {}
    for r in rows:
        if r.nne:
            by_nne.setdefault(r.nne, []).append(r)
    duplicate_nne = [r for group in by_nne.values() if len(group) > 1 for r in group]

    by_name: dict[frozenset[str], list[MappedRow]] = {}
    for r in rows:
        key = name_tokens(r.last_name) | name_tokens(r.first_names)
        if key:
            by_name.setdefault(key, []).append(r)
    mismatches = [
        (group[i], group[j])
        for group in by_name.values()
        if len(group) > 1
        for i in range(len(group))
        for j in range(i + 1, len(group))
        if group[i].nne != group[j].nne
    ]

    return ValidationReport(
        missing_fields=missing,
        malformed_nne=malformed,
        duplicate_nne=duplicate_nne,
        duplicate_name_nne_mismatch=mismatches,
    )


@transaction.atomic
def apply_import(
    rows: list[MappedRow], *, filename: str, file_sha256: bytes, operator: User
) -> RollImport:
    """The write (§6.1), shared by screen 3 and ``import_roll``.

    All-or-nothing: refuses outright on a blocking issue, so a bad file writes
    nothing (T-11). Replaces ``WorkingRollEntry`` entirely; it never touches
    ``RollEntry``, the frozen snapshot an already-open poll took at ``draft →
    open`` — the two live in different apps, and nothing here imports the one
    that holds it (T-26).
    """
    report = validate(rows)
    if report.blocking:
        raise RollImportRefused(report)

    WorkingRollEntry.objects.all().delete()
    WorkingRollEntry.objects.bulk_create(
        WorkingRollEntry(last_name=r.last_name, first_names=r.first_names, nne=r.nne) for r in rows
    )
    roll_import = RollImport.objects.create(
        filename=filename, file_sha256=file_sha256, row_count=len(rows), imported_by=operator
    )
    # §6.1: "Log filename, SHA-256 of the file, row count, operator." None of
    # the four is personal data — the row_count is the roll, not a row of it.
    audit.record(
        action=Action.ROLL_IMPORTED,
        actor=operator,
        object_ref=audit.ref(roll_import),
        after={
            "filename": filename,
            "file_sha256": file_sha256.hex(),
            "row_count": len(rows),
        },
    )
    return roll_import
