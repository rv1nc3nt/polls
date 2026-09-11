# SPDX-License-Identifier: 0BSD
"""Roll import (§6.1), end to end: ``apply_import``, the CLI, and screen 3.

The pure parsing, validation and collapse layer is pinned in
``tests/unit/test_rollimport.py``; this file covers what needs the database and
the request/response cycle, and T-64 — the bundled fixture's expected outcome.
"""

from __future__ import annotations

import contextlib
import io
import tempfile
from collections.abc import Iterator
from pathlib import Path

import openpyxl
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.test import Client

from apps.audit.models import Action, AuditEvent
from apps.core.models import PollRole, Role, User
from apps.elections import rollimport
from apps.elections.models import Poll, RollEntry, WorkingRollEntry
from apps.elections.transitions import open_poll

HEADER = "Nom de naissance;Nom d'usage;Prénoms;Date de naissance;Type de liste"
CLEAN_CSV = (
    f"{HEADER}\n"
    "Dupont;;Émile;14/03/1962;Liste principale\n"
    "Martin;;Alice;01/01/1980;Liste principale\n"
)
MAPPING = {
    "birth_name": "Nom de naissance",
    "usual_name": "Nom d'usage",
    "first_names": "Prénoms",
    "date_of_birth": "Date de naissance",
    "list_type": "Type de liste",
}
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "roll-fixture.csv"


def _row(
    index: int = 2,
    birth_name: str = "Dupont",
    first_names: str = "Émile",
    date_of_birth: str = "14/03/1962",
    list_type: str = "Liste principale",
) -> rollimport.MappedRow:
    return rollimport.MappedRow(
        index=index,
        birth_name=birth_name,
        first_names=first_names,
        date_of_birth=date_of_birth,
        list_type=list_type,
    )


@pytest.fixture
def operator(db: None) -> User:
    return User.objects.create_user(username="p.martin", password="x", full_name="P. Martin")


# --- apply_import: the write shared by the CLI and screen 3 -----------------


def test_apply_import_replaces_the_working_roll(operator: User) -> None:
    WorkingRollEntry.objects.create(
        birth_name="Ancien", first_names="Électeur", list_types=["principale"]
    )
    rollimport.apply_import(
        [_row()], MAPPING, filename="roll.csv", file_sha256=b"\x00" * 32, operator=operator
    )
    assert WorkingRollEntry.objects.count() == 1
    entry = WorkingRollEntry.objects.get()
    assert entry.birth_name == "Dupont"
    assert entry.list_types == ["principale"]


def test_t26_a_reimport_does_not_touch_an_open_polls_snapshot(
    operator: User, open_window_poll: Poll
) -> None:
    open_poll(open_window_poll)
    before = list(
        RollEntry.objects.filter(poll=open_window_poll).values_list("birth_name", flat=True)
    )

    rollimport.apply_import(
        [_row(birth_name="Nouveau")],
        MAPPING,
        filename="roll.csv",
        file_sha256=b"\x00" * 32,
        operator=operator,
    )

    after = list(
        RollEntry.objects.filter(poll=open_window_poll).values_list("birth_name", flat=True)
    )
    assert before == after
    assert WorkingRollEntry.objects.get().birth_name == "Nouveau"


def test_t11_apply_import_refuses_and_writes_nothing_on_a_nameless_row(operator: User) -> None:
    WorkingRollEntry.objects.create(
        birth_name="Ancien", first_names="Électeur", list_types=["principale"]
    )
    rows = [_row(), rollimport.MappedRow(index=3, first_names="Y", date_of_birth="01/01/1990")]

    with pytest.raises(rollimport.RollImportRefused) as excinfo:
        rollimport.apply_import(
            rows, MAPPING, filename="roll.csv", file_sha256=b"\x00" * 32, operator=operator
        )

    assert excinfo.value.report.nameless_rows
    assert WorkingRollEntry.objects.count() == 1
    assert WorkingRollEntry.objects.get().birth_name == "Ancien", "nothing written"


def test_t11_apply_import_refuses_on_an_unmapped_mandatory_column(operator: User) -> None:
    with pytest.raises(rollimport.RollImportRefused) as excinfo:
        rollimport.apply_import(
            [_row()],
            {"birth_name": "Nom de naissance", "first_names": "Prénoms"},
            filename="roll.csv",
            file_sha256=b"\x00" * 32,
            operator=operator,
        )
    assert "date_of_birth" in excinfo.value.report.missing_columns


def test_apply_import_logs_filename_hash_and_row_count_never_a_row(operator: User) -> None:
    rollimport.apply_import(
        [_row(), _row(index=3, birth_name="Martin", first_names="Alice")],
        MAPPING,
        filename="liste_2026.csv",
        file_sha256=b"\xab" * 32,
        operator=operator,
    )
    event = AuditEvent.objects.get(action=Action.ROLL_IMPORTED)
    assert event.actor == operator
    assert event.after["filename"] == "liste_2026.csv"
    assert event.after["file_sha256"] == "ab" * 32
    assert event.after["row_count"] == 2
    assert "Dupont" not in str(event.after)


# --- T-64: the bundled fixture ---------------------------------------------


def test_t64_the_fixture_imports_to_the_documented_outcome(operator: User) -> None:
    """``tests/fixtures/roll-fixture.csv`` → 58 entries from 60 rows; 57
    eligible; the European-list-only entry ineligible; 2 flagged
    ``date_uncertain``; one indistinguishable pair (per the fixture README)."""
    data = FIXTURE.read_bytes()
    table = rollimport.read_table(data, FIXTURE.name)
    mapping = rollimport.guess_mapping(table.headers)
    rows = rollimport.apply_mapping(table, mapping)

    assert len(rows) == 60
    result = rollimport.collapse(rows)
    assert len(result.entries) == 58, "two electors collapsed across list types"

    report = rollimport.validate(rows, mapping)
    assert not report.blocking
    assert len(report.date_uncertain) == 2
    assert len(report.indistinguishable) == 2, "the NOIRTIER Victorin pair"

    eligible = {"principale", "complementaire_municipale"}
    eligible_entries = [e for e in result.entries if set(e.list_types) & eligible]
    assert len(eligible_entries) == 57
    ineligible = [e for e in result.entries if e.list_types and not set(e.list_types) & eligible]
    assert len(ineligible) == 1
    assert set(ineligible[0].list_types) == {"complementaire_europeenne"}

    rollimport.apply_import(
        rows, mapping, filename=FIXTURE.name, file_sha256=b"\x00" * 32, operator=operator
    )
    assert WorkingRollEntry.objects.count() == 58


# --- The CLI --------------------------------------------------------------


@contextlib.contextmanager
def tempfile_csv(text: str) -> Iterator[Path]:
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as handle:
        handle.write(text.encode("utf-8"))
        path = Path(handle.name)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def test_the_command_imports_a_clean_csv(operator: User) -> None:
    with tempfile_csv(CLEAN_CSV) as path:
        call_command("import_roll", path, "--operator", operator.username)
    assert WorkingRollEntry.objects.count() == 2


def test_the_command_refuses_and_writes_nothing_on_a_nameless_row(operator: User) -> None:
    with tempfile_csv(f"{HEADER}\n;;Émile;14/03/1962;Liste principale\n") as path:
        with pytest.raises(CommandError):
            call_command("import_roll", path, "--operator", operator.username)
    assert WorkingRollEntry.objects.count() == 0


def test_the_command_imports_unparseable_dates_rather_than_refusing(operator: User) -> None:
    """R-4.5: a bad date is reported and imported, not a blocker."""
    with tempfile_csv(f"{HEADER}\nDupont;;Émile;00/00/1953;Liste principale\n") as path:
        call_command("import_roll", path, "--operator", operator.username)
    entry = WorkingRollEntry.objects.get()
    assert entry.date_uncertain
    assert entry.date_of_birth == "00/00/1953"


def test_the_command_dry_run_writes_nothing(operator: User) -> None:
    with tempfile_csv(CLEAN_CSV) as path:
        call_command("import_roll", path, "--operator", operator.username, "--dry-run")
    assert WorkingRollEntry.objects.count() == 0


def test_the_command_refuses_an_unknown_operator(db: None) -> None:
    with tempfile_csv(CLEAN_CSV) as path:
        with pytest.raises(CommandError):
            call_command("import_roll", path, "--operator", "personne")


def test_the_command_refuses_unrecognised_headers_and_points_at_screen_3(operator: User) -> None:
    with tempfile_csv("A;B;C\nx;y;z\n") as path:
        with pytest.raises(CommandError) as excinfo:
            call_command("import_roll", path, "--operator", operator.username)
    assert "écran" in str(excinfo.value)
    assert WorkingRollEntry.objects.count() == 0


# --- Screen 3, end to end ----------------------------------------------------


def _make_commune_admin(user: User) -> None:
    user.is_commune_admin = True
    user.save(update_fields=["is_commune_admin"])


def _xlsx_bytes(rows: list[list[str]]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


_CONFIRM = {
    "col_birth_name": "Nom de naissance",
    "col_usual_name": "Nom d'usage",
    "col_first_names": "Prénoms",
    "col_date_of_birth": "Date de naissance",
    "col_list_type": "Type de liste",
    "action": "confirm",
}


def test_the_upload_step_stores_a_draft_and_redirects_to_review(
    client: Client, operator: User
) -> None:
    _make_commune_admin(operator)
    client.force_login(operator)

    upload = SimpleUploadedFile("roll.csv", CLEAN_CSV.encode(), content_type="text/csv")
    response = client.post("/fr/mairie/liste-electorale/", {"file": upload})

    assert response.status_code == 302
    assert response["Location"].endswith("/verification/")
    assert WorkingRollEntry.objects.count() == 0


def test_an_unreadable_upload_is_reported_and_writes_nothing(
    client: Client, operator: User
) -> None:
    _make_commune_admin(operator)
    client.force_login(operator)

    upload = SimpleUploadedFile("roll.xlsx", b"not a workbook", content_type="application/xlsx")
    response = client.post("/fr/mairie/liste-electorale/", {"file": upload})
    assert response.status_code == 200
    assert "illisible" in response.content.decode()


def test_the_review_step_shows_the_preview_and_the_report(client: Client, operator: User) -> None:
    _make_commune_admin(operator)
    client.force_login(operator)
    upload = SimpleUploadedFile("roll.csv", CLEAN_CSV.encode(), content_type="text/csv")
    client.post("/fr/mairie/liste-electorale/", {"file": upload})

    body = client.get("/fr/mairie/liste-electorale/verification/").content.decode()
    assert "Dupont" in body
    assert "2 lignes à traiter" in body


def test_confirming_applies_the_import_and_clears_the_draft(client: Client, operator: User) -> None:
    _make_commune_admin(operator)
    client.force_login(operator)
    upload = SimpleUploadedFile("roll.csv", CLEAN_CSV.encode(), content_type="text/csv")
    client.post("/fr/mairie/liste-electorale/", {"file": upload})

    response = client.post("/fr/mairie/liste-electorale/verification/", _CONFIRM, follow=True)

    assert response.status_code == 200
    assert WorkingRollEntry.objects.count() == 2
    assert AuditEvent.objects.filter(action=Action.ROLL_IMPORTED).exists()
    assert "roll_import_draft" not in client.session


def test_confirming_a_blocking_report_is_refused_and_writes_nothing(
    client: Client, operator: User
) -> None:
    _make_commune_admin(operator)
    client.force_login(operator)
    bad = f"{HEADER}\n;;Émile;14/03/1962;Liste principale\n"
    upload = SimpleUploadedFile("roll.csv", bad.encode(), content_type="text/csv")
    client.post("/fr/mairie/liste-electorale/", {"file": upload})

    client.post("/fr/mairie/liste-electorale/verification/", _CONFIRM)
    assert WorkingRollEntry.objects.count() == 0


def test_review_with_no_draft_sends_back_to_upload(client: Client, operator: User) -> None:
    _make_commune_admin(operator)
    client.force_login(operator)
    response = client.get("/fr/mairie/liste-electorale/verification/", follow=True)
    assert "Liste électorale" in response.content.decode()
    assert response.redirect_chain


def test_xlsx_upload_works_end_to_end(client: Client, operator: User) -> None:
    _make_commune_admin(operator)
    client.force_login(operator)
    data = _xlsx_bytes(
        [
            ["Nom de naissance", "Nom d'usage", "Prénoms", "Date de naissance", "Type de liste"],
            ["Dupont", "", "Émile", "14/03/1962", "Liste principale"],
        ]
    )
    upload = SimpleUploadedFile(
        "roll.xlsx", data, content_type="application/vnd.openxmlformats-officedocument"
    )
    client.post("/fr/mairie/liste-electorale/", {"file": upload})

    client.post("/fr/mairie/liste-electorale/verification/", _CONFIRM)
    assert WorkingRollEntry.objects.count() == 1


def test_a_poll_admin_without_the_commune_flag_cannot_reach_the_screen(
    client: Client, open_window_poll: Poll, operator: User
) -> None:
    """R-2.1: importing the roll is the commune administrator's, not a poll
    admin's — holding ``poll_admin`` on some poll grants nothing here."""
    PollRole.objects.create(poll=open_window_poll, user=operator, role=Role.POLL_ADMIN)
    client.force_login(operator)
    assert client.get("/fr/mairie/liste-electorale/").status_code == 403


# --- Screen 3's read-only counterpart on a poll's own menu -------------------


def test_a_poll_admin_sees_the_current_import_read_only(
    client: Client, open_window_poll: Poll, operator: User
) -> None:
    PollRole.objects.create(poll=open_window_poll, user=operator, role=Role.POLL_ADMIN)
    importer = User.objects.create_user(username="importer", full_name="Importeuse")
    rollimport.apply_import(
        [_row()], MAPPING, filename="roll.csv", file_sha256=b"\x00" * 32, operator=importer
    )
    client.force_login(operator)

    body = client.get(
        f"/fr/mairie/scrutin/{open_window_poll.pk}/liste-electorale/"
    ).content.decode()
    assert "roll.csv" in body
    assert "Importeuse" in body


def test_roll_status_carries_no_form_to_import_from(
    client: Client, open_window_poll: Poll, operator: User
) -> None:
    """No importation from a poll submenu — the whole point of moving screen 3
    to the general menu (§3.2)."""
    PollRole.objects.create(poll=open_window_poll, user=operator, role=Role.POLL_ADMIN)
    client.force_login(operator)
    body = client.get(
        f"/fr/mairie/scrutin/{open_window_poll.pk}/liste-electorale/"
    ).content.decode()
    assert 'type="file"' not in body
    assert "Charger le fichier" not in body


# --- T-65: R-4.4, once the poll has left draft --------------------------------


def test_t65_poll_admin_and_auditor_browse_the_frozen_copy_once_open(
    client: Client, open_window_poll: Poll, operator: User
) -> None:
    """From ``open`` onward ``roll_status`` browses this poll's own frozen
    copy, not the working roll — open to poll_admin and, per R-4.4, auditor."""
    open_poll(open_window_poll)
    poll = Poll.objects.get(pk=open_window_poll.pk)
    url = f"/fr/mairie/scrutin/{poll.pk}/liste-electorale/"

    PollRole.objects.create(poll=poll, user=operator, role=Role.POLL_ADMIN)
    client.force_login(operator)
    assert "Dupont" in client.get(url).content.decode()

    auditor = User.objects.create_user(username="v.leroy", password="x", full_name="V. Leroy")
    PollRole.objects.create(poll=poll, user=auditor, role=Role.AUDITOR)
    client.force_login(auditor)
    assert "Dupont" in client.get(url).content.decode()


def test_t65_entry_operator_is_refused_roll_status_even_though_open(
    client: Client, open_window_poll: Poll, operator: User
) -> None:
    """R-4.4 names ``poll_admin`` and ``auditor``, not every per-poll role."""
    open_poll(open_window_poll)
    poll = Poll.objects.get(pk=open_window_poll.pk)
    PollRole.objects.create(poll=poll, user=operator, role=Role.ENTRY_OPERATOR)
    client.force_login(operator)
    assert client.get(f"/fr/mairie/scrutin/{poll.pk}/liste-electorale/").status_code == 403


def test_roll_status_search_narrows_the_frozen_copy(
    client: Client, open_window_poll: Poll, operator: User
) -> None:
    WorkingRollEntry.objects.create(
        birth_name="Nguyen",
        first_names="Thi Lan",
        date_of_birth="21/11/1990",
        date_of_birth_parsed="1990-11-21",
        list_types=["principale"],
    )
    open_poll(open_window_poll)
    poll = Poll.objects.get(pk=open_window_poll.pk)
    PollRole.objects.create(poll=poll, user=operator, role=Role.POLL_ADMIN)
    client.force_login(operator)
    url = f"/fr/mairie/scrutin/{poll.pk}/liste-electorale/"

    body = client.get(url, {"q": "Nguyen"}).content.decode()
    assert "Nguyen" in body
    assert "Dupont" not in body


# --- Screen 3's own search over the working roll -----------------------------


def test_screen_3_search_narrows_the_working_roll(client: Client, operator: User) -> None:
    """A plain browse of ``WorkingRollEntry``, distinct from R-8.3's near-match
    confirmation (§6.5.5): no scoring, just a substring across the roll.

    Names deliberately avoid the operator's own ("P. Martin", shown in the
    page chrome on every screen) so a hit there cannot be mistaken for one in
    the roll table.
    """
    _make_commune_admin(operator)
    WorkingRollEntry.objects.create(
        birth_name="Dupont", first_names="Émile", date_of_birth="14/03/1962", list_types=["a"]
    )
    WorkingRollEntry.objects.create(
        birth_name="Lefevre", first_names="Alice", date_of_birth="01/01/1980", list_types=["a"]
    )
    client.force_login(operator)

    body = client.get("/fr/mairie/liste-electorale/", {"q": "Dupont"}).content.decode()
    assert "Dupont" in body
    assert "Lefevre" not in body

    unfiltered = client.get("/fr/mairie/liste-electorale/").content.decode()
    assert "Dupont" in unfiltered
    assert "Lefevre" in unfiltered
