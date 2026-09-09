# SPDX-License-Identifier: 0BSD
"""Roll import (§6.1, R-4.2, R-4.5): parsing, mapping, validation, collapse, and
the transactional apply.

Parsing, validation and collapse are pure — a byte string in, dataclasses out —
so they are testable without a request, an uploaded file or a database (§12.1).
The one function that writes, ``apply_import``, is the service screen 3 and the
``import_roll`` command both call: sharing it is what keeps "all-or-nothing"
(T-11) and "replaces the working roll entirely" (T-26) meaning the same thing in
the UI and on the terminal.

**The report informs; it does not gate (R-4.5).** Only a structurally unusable
file is refused, and then nothing is written: a mandatory column left unmapped,
or a row carrying no name at all. Everything else — an unparseable date of birth
(R-4.9), a row with no list type, rows that collapse together, two entries that
share a normalised name and date of birth but do not collapse — is reported and
imported, because it is judgement for a human and not a defect in the file.

**Collapsing (R-4.6).** The export carries one row per elector *per list type*.
Rows that share a normalised identity — birth name, name in use, forenames — and
a parsed date of birth, and that differ only in their list type, are merged into
one entry holding the union of those list types. Rows identical *including* the
list type are left as separate entries and reported: they are either a duplicate
line or genuine homonyms, and only a human can tell (§6.2). A row whose date of
birth will not parse is never collapsed on a parsed value (R-4.9).

``WorkingRollEntry`` is commune-wide, not poll-scoped (§3.2): screen 3 is
reached from one poll's back-office, gated by that poll's roles, but what it
replaces is shared by every poll still in ``draft``.
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import openpyxl
from django.db import transaction
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from apps.audit import services as audit
from apps.audit.models import Action
from apps.core.models import User
from apps.core.names import name_tokens, parse_dob, strip_diacritics

from .models import ListType, RollImport, WorkingRollEntry

#: The fields §6.1's column mapping UI resolves. Order is display order.
FIELDS: tuple[str, ...] = (
    "birth_name",
    "usual_name",
    "first_names",
    "date_of_birth",
    "list_type",
)
#: Of those, the ones whose column must be mapped or the import is refused
#: (R-4.5). ``usual_name`` is often blank and its column may be genuinely
#: absent, so it is optional.
MANDATORY_FIELDS: tuple[str, ...] = ("birth_name", "first_names", "date_of_birth", "list_type")

FIELD_LABELS = {
    "birth_name": _lazy("Nom de naissance"),
    "usual_name": _lazy("Nom d'usage"),
    "first_names": _lazy("Prénoms"),
    "date_of_birth": _lazy("Date de naissance"),
    "list_type": _lazy("Type de liste"),
}

#: Header text (accent- and case-insensitive) guessed against each field, for
#: convenience only (§6.1's mapping UI). A miss is not an error — it just leaves
#: that field for the operator to map by hand.
_GUESS_HEADERS: dict[str, frozenset[str]] = {
    "birth_name": frozenset(
        {"nom de naissance", "nom", "nom de famille", "birth name", "last name", "surname"}
    ),
    "usual_name": frozenset(
        {"nom d'usage", "nom d usage", "usual name", "name in use", "married name"}
    ),
    "first_names": frozenset(
        {"prenom", "prenoms", "prénom", "prénoms", "first name", "first names", "forenames"}
    ),
    "date_of_birth": frozenset(
        {"date de naissance", "date of birth", "dob", "birth date", "naissance"}
    ),
    "list_type": frozenset(
        {
            "libelle du type de liste",
            "libellé du type de liste",
            "type de liste",
            "list type",
            "liste",
        }
    ),
}

#: How a REU export's free-text list label maps to a ``ListType`` (R-4.7). The
#: label is compared after diacritic stripping and case folding; an unrecognised
#: label leaves the row with no list type, which the report flags as incomplete.
_LIST_TYPE_MARKERS: tuple[tuple[str, str], ...] = (
    ("principale", ListType.PRINCIPALE),
    ("municipale", ListType.COMPLEMENTAIRE_MUNICIPALE),
    ("europ", ListType.COMPLEMENTAIRE_EUROPEENNE),
)


class UnreadableFile(ValueError):
    """The upload is neither valid CSV nor a valid .xlsx workbook."""


class RollImportRefused(Exception):
    """``apply_import`` refused: the file is structurally unusable (T-11).

    Carries the report rather than a formatted message, so a caller — the
    command or the back-office view — decides how to show it.
    """

    def __init__(self, report: ValidationReport) -> None:
        super().__init__(_("Le fichier est inexploitable en l'état."))
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
    """One row, resolved to the fields the roll needs. Values are still raw."""

    #: 1-based, matching the row number a spreadsheet would show the operator
    #: (the header is row 1).
    index: int
    birth_name: str = ""
    usual_name: str = ""
    first_names: str = ""
    date_of_birth: str = ""
    list_type: str = ""


def apply_mapping(table: Table, mapping: Mapping[str, str]) -> list[MappedRow]:
    """Extract the fields using the operator's column choices."""
    columns = {name: table.headers.index(mapping[name]) for name in FIELDS if name in mapping}

    def cell(row: list[str], field_name: str) -> str:
        column = columns.get(field_name)
        if column is None or column >= len(row):
            return ""
        return row[column].strip()

    return [
        MappedRow(
            index=offset + 2,
            birth_name=cell(row, "birth_name"),
            usual_name=cell(row, "usual_name"),
            first_names=cell(row, "first_names"),
            date_of_birth=cell(row, "date_of_birth"),
            list_type=cell(row, "list_type"),
        )
        for offset, row in enumerate(table.rows)
    ]


def list_type_of(label: str) -> str | None:
    """A REU list label (`Liste complémentaire municipale`, …) as a ``ListType``
    value, or ``None`` where the label is empty or unrecognised (R-4.7)."""
    normalised = strip_diacritics(label).casefold()
    for marker, value in _LIST_TYPE_MARKERS:
        if marker in normalised:
            return value
    return None


@dataclass(frozen=True)
class Entry:
    """One elector, after parsing and collapse — the shape ``apply_import``
    writes and the preview shows."""

    birth_name: str
    usual_name: str
    first_names: str
    #: The date of birth verbatim, exactly as the file gave it (R-4.9).
    date_of_birth: str
    date_of_birth_parsed: date | None
    date_uncertain: bool
    list_types: tuple[str, ...]
    #: The 1-based file rows this entry was built from; one unless collapsed.
    source_rows: tuple[int, ...]


def _identity_key(row: MappedRow) -> tuple[str, ...]:
    return (
        "".join(sorted(name_tokens(row.birth_name))),
        "".join(sorted(name_tokens(row.usual_name))),
        "".join(sorted(name_tokens(row.first_names))),
    )


@dataclass(frozen=True)
class CollapseResult:
    entries: list[Entry]
    #: Entries built from more than one row, merged across list types (R-4.6).
    collapsed: list[Entry]
    #: Groups that share a normalised name and date of birth but were *not*
    #: collapsed — a repeated list type means either a duplicate line or genuine
    #: homonyms, and only a human can tell (§6.2). Flat list of the entries.
    indistinguishable: list[Entry]


def collapse(rows: Iterable[MappedRow]) -> CollapseResult:
    """Parse dates and merge one-row-per-list-type into one entry (R-4.6, R-4.9)."""
    groups: dict[tuple[Any, ...], list[MappedRow]] = {}
    for row in rows:
        parsed = parse_dob(row.date_of_birth)
        if parsed is None:
            # R-4.9: never collapsed on a parsed value — its own group, keyed
            # on the file row so two uncertain rows never merge.
            key: tuple[Any, ...] = ("uncertain", row.index)
        else:
            key = (_identity_key(row), parsed)
        groups.setdefault(key, []).append(row)

    entries: list[Entry] = []
    collapsed: list[Entry] = []
    indistinguishable: list[Entry] = []

    for group in groups.values():
        parsed = parse_dob(group[0].date_of_birth)
        uncertain = parsed is None
        types = [list_type_of(r.list_type) for r in group]
        named = [t for t in types if t]
        homonyms = len(named) != len(set(named))

        if uncertain or homonyms:
            group_entries = [
                Entry(
                    birth_name=r.birth_name,
                    usual_name=r.usual_name,
                    first_names=r.first_names,
                    date_of_birth=r.date_of_birth,
                    date_of_birth_parsed=parse_dob(r.date_of_birth),
                    date_uncertain=parse_dob(r.date_of_birth) is None,
                    list_types=tuple(t for t in (list_type_of(r.list_type),) if t),
                    source_rows=(r.index,),
                )
                for r in group
            ]
            entries.extend(group_entries)
            if homonyms:
                indistinguishable.extend(group_entries)
            continue

        merged = Entry(
            birth_name=group[0].birth_name,
            usual_name=group[0].usual_name,
            first_names=group[0].first_names,
            date_of_birth=group[0].date_of_birth,
            date_of_birth_parsed=parsed,
            date_uncertain=False,
            list_types=tuple(sorted(set(named))),
            source_rows=tuple(r.index for r in group),
        )
        entries.append(merged)
        if len(group) > 1:
            collapsed.append(merged)

    entries.sort(key=lambda e: e.source_rows[0])
    return CollapseResult(entries=entries, collapsed=collapsed, indistinguishable=indistinguishable)


@dataclass(frozen=True)
class ValidationReport:
    """§6.1's report. Nothing here is logged — the audit event records a count,
    never a row (§10). The first two categories block; the rest are advisory."""

    #: Mandatory columns the operator has not mapped (R-4.5). Blocking.
    missing_columns: list[str] = field(default_factory=list)
    #: Rows with neither a birth name nor a name in use (R-4.5). Blocking.
    nameless_rows: list[MappedRow] = field(default_factory=list)
    #: Entries whose date of birth would not parse, kept verbatim (R-4.9).
    date_uncertain: list[Entry] = field(default_factory=list)
    #: Entries left with no list type at all.
    incomplete: list[Entry] = field(default_factory=list)
    #: Entries merged across list types (R-4.6).
    collapsed: list[Entry] = field(default_factory=list)
    #: Entries sharing a normalised name and date of birth that did not
    #: collapse — judgement for a human, never a refusal.
    indistinguishable: list[Entry] = field(default_factory=list)

    @property
    def blocking(self) -> bool:
        """§6.1, R-4.5: only a structurally unusable file is refused (T-11)."""
        return bool(self.missing_columns or self.nameless_rows)

    @property
    def clean(self) -> bool:
        return not (
            self.missing_columns
            or self.nameless_rows
            or self.date_uncertain
            or self.incomplete
            or self.collapsed
            or self.indistinguishable
        )


def validate(rows: list[MappedRow], mapped_fields: Iterable[str]) -> ValidationReport:
    """Build the report (§6.1). ``mapped_fields`` is the set of ``FIELDS`` the
    operator has assigned a column to; a missing mandatory one blocks."""
    mapped = set(mapped_fields)
    missing_columns = [f for f in MANDATORY_FIELDS if f not in mapped]
    nameless = [r for r in rows if not (r.birth_name or r.usual_name)]

    result = collapse(rows)
    return ValidationReport(
        missing_columns=missing_columns,
        nameless_rows=nameless,
        date_uncertain=[e for e in result.entries if e.date_uncertain],
        incomplete=[e for e in result.entries if not e.list_types],
        collapsed=result.collapsed,
        indistinguishable=result.indistinguishable,
    )


@transaction.atomic
def apply_import(
    rows: list[MappedRow],
    mapped_fields: Iterable[str],
    *,
    filename: str,
    file_sha256: bytes,
    operator: User,
) -> RollImport:
    """The write (§6.1), shared by screen 3 and ``import_roll``.

    All-or-nothing: refuses outright on a structurally unusable file, so a bad
    file writes nothing (T-11, R-4.5). Replaces ``WorkingRollEntry`` entirely;
    it never touches ``RollEntry``, the frozen snapshot an already-open poll
    took at ``draft → open`` — the two live in different apps, and nothing here
    imports the one that holds it (T-26).

    ``row_count`` logged is the number of rows read, not the number of entries
    created after collapse (§6.1).
    """
    mapped = list(mapped_fields)
    report = validate(rows, mapped)
    if report.blocking:
        raise RollImportRefused(report)

    entries = collapse(rows).entries
    WorkingRollEntry.objects.all().delete()
    WorkingRollEntry.objects.bulk_create(
        WorkingRollEntry(
            birth_name=e.birth_name,
            usual_name=e.usual_name,
            first_names=e.first_names,
            date_of_birth=e.date_of_birth,
            date_of_birth_parsed=e.date_of_birth_parsed,
            date_uncertain=e.date_uncertain,
            list_types=list(e.list_types),
        )
        for e in entries
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
            "entry_count": len(entries),
        },
    )
    return roll_import
