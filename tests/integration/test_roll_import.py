# SPDX-License-Identifier: 0BSD
"""Roll import (§6.1), end to end: ``apply_import``, the CLI, and screen 3.

The pure parsing and validation layer is pinned in
``tests/unit/test_rollimport.py``; this file covers what needs the database and
the request/response cycle.
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

CLEAN_CSV = "Nom,Prénoms,NNE\nDupont,Émile,123456789\nMartin,Alice,987654321\n"


def _row(nne: str = "123456789") -> rollimport.MappedRow:
    return rollimport.MappedRow(index=2, last_name="Dupont", first_names="Émile", nne=nne)


@pytest.fixture
def operator(db: None) -> User:
    return User.objects.create_user(username="p.martin", password="x", full_name="P. Martin")


# --- apply_import: the write shared by the CLI and screen 3 -----------------


def test_apply_import_replaces_the_working_roll(operator: User) -> None:
    WorkingRollEntry.objects.create(last_name="Ancien", first_names="Électeur", nne="11111111")
    rollimport.apply_import(
        [_row()], filename="roll.csv", file_sha256=b"\x00" * 32, operator=operator
    )
    assert WorkingRollEntry.objects.count() == 1
    assert WorkingRollEntry.objects.get().nne == "123456789"


def test_t26_a_reimport_does_not_touch_an_open_polls_snapshot(
    operator: User, open_window_poll: Poll
) -> None:
    """The frozen snapshot lives in a different table and a different app;
    nothing in this module imports it."""
    open_poll(open_window_poll)
    before = list(RollEntry.objects.filter(poll=open_window_poll).values_list("nne", flat=True))

    rollimport.apply_import(
        [_row(nne="999999999")], filename="roll.csv", file_sha256=b"\x00" * 32, operator=operator
    )

    after = list(RollEntry.objects.filter(poll=open_window_poll).values_list("nne", flat=True))
    assert before == after
    assert WorkingRollEntry.objects.get().nne == "999999999"


def test_t11_apply_import_refuses_and_writes_nothing_on_a_malformed_nne(
    operator: User,
) -> None:
    WorkingRollEntry.objects.create(last_name="Ancien", first_names="Électeur", nne="11111111")
    rows = [_row(), rollimport.MappedRow(index=3, last_name="X", first_names="Y", nne="12")]

    with pytest.raises(rollimport.RollImportRefused) as excinfo:
        rollimport.apply_import(
            rows, filename="roll.csv", file_sha256=b"\x00" * 32, operator=operator
        )

    assert excinfo.value.report.malformed_nne
    assert WorkingRollEntry.objects.count() == 1
    assert WorkingRollEntry.objects.get().nne == "11111111", "nothing written, old roll intact"


def test_apply_import_logs_filename_hash_and_row_count_never_a_row(operator: User) -> None:
    """§6.1: "Log filename, SHA-256 of the file, row count, operator." Nothing
    about an individual elector belongs here (§10)."""
    rollimport.apply_import(
        [_row(), _row(nne="222222222")],
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


def test_the_command_refuses_and_writes_nothing_on_a_malformed_nne(operator: User) -> None:
    with tempfile_csv("Nom,Prénoms,NNE\nDupont,Émile,12\n") as path:
        with pytest.raises(CommandError):
            call_command("import_roll", path, "--operator", operator.username)
    assert WorkingRollEntry.objects.count() == 0


def test_the_command_dry_run_writes_nothing(operator: User) -> None:
    with tempfile_csv(CLEAN_CSV) as path:
        call_command("import_roll", path, "--operator", operator.username, "--dry-run")
    assert WorkingRollEntry.objects.count() == 0


def test_the_command_refuses_an_unknown_operator(db: None) -> None:
    with tempfile_csv(CLEAN_CSV) as path:
        with pytest.raises(CommandError):
            call_command("import_roll", path, "--operator", "personne")


def test_the_command_refuses_unrecognised_headers_and_points_at_screen_3(
    operator: User,
) -> None:
    with tempfile_csv("A,B,C\nx,y,z\n") as path:
        with pytest.raises(CommandError) as excinfo:
            call_command("import_roll", path, "--operator", operator.username)
    assert "écran" in str(excinfo.value)
    assert WorkingRollEntry.objects.count() == 0


# --- Screen 3, end to end ----------------------------------------------------


def _grant(poll: Poll, user: User) -> None:
    PollRole.objects.create(poll=poll, user=user, role=Role.POLL_ADMIN)


def _xlsx_bytes(rows: list[list[str]]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_the_upload_step_stores_a_draft_and_redirects_to_review(
    client: Client, open_window_poll: Poll, operator: User
) -> None:
    _grant(open_window_poll, operator)
    client.force_login(operator)

    upload = SimpleUploadedFile("roll.csv", CLEAN_CSV.encode(), content_type="text/csv")
    response = client.post(
        f"/fr/mairie/scrutin/{open_window_poll.pk}/liste-electorale/", {"file": upload}
    )

    assert response.status_code == 302
    assert response["Location"].endswith("/verification/")
    # The fixture's own entry, untouched: nothing is written before confirmation.
    assert WorkingRollEntry.objects.count() == 1


def test_an_unreadable_upload_is_reported_and_writes_nothing(
    client: Client, open_window_poll: Poll, operator: User
) -> None:
    _grant(open_window_poll, operator)
    client.force_login(operator)

    upload = SimpleUploadedFile("roll.xlsx", b"not a workbook", content_type="application/xlsx")
    response = client.post(
        f"/fr/mairie/scrutin/{open_window_poll.pk}/liste-electorale/", {"file": upload}
    )
    assert response.status_code == 200
    assert "illisible" in response.content.decode()


def test_the_review_step_shows_the_guessed_mapping_and_the_report(
    client: Client, open_window_poll: Poll, operator: User
) -> None:
    _grant(open_window_poll, operator)
    client.force_login(operator)
    upload = SimpleUploadedFile("roll.csv", CLEAN_CSV.encode(), content_type="text/csv")
    client.post(f"/fr/mairie/scrutin/{open_window_poll.pk}/liste-electorale/", {"file": upload})

    body = client.get(
        f"/fr/mairie/scrutin/{open_window_poll.pk}/liste-electorale/verification/"
    ).content.decode()
    assert "Dupont" in body, "preview row"
    assert "2 lignes à traiter" in body


def test_confirming_applies_the_import_and_clears_the_draft(
    client: Client, open_window_poll: Poll, operator: User
) -> None:
    _grant(open_window_poll, operator)
    client.force_login(operator)
    upload = SimpleUploadedFile("roll.csv", CLEAN_CSV.encode(), content_type="text/csv")
    client.post(f"/fr/mairie/scrutin/{open_window_poll.pk}/liste-electorale/", {"file": upload})

    review_url = f"/fr/mairie/scrutin/{open_window_poll.pk}/liste-electorale/verification/"
    response = client.post(
        review_url,
        {
            "col_last_name": "Nom",
            "col_first_names": "Prénoms",
            "col_nne": "NNE",
            "action": "confirm",
        },
        follow=True,
    )

    assert response.status_code == 200
    assert WorkingRollEntry.objects.count() == 2
    assert AuditEvent.objects.filter(action=Action.ROLL_IMPORTED).exists()
    assert "roll_import_draft" not in client.session


def test_confirming_a_blocking_report_is_refused_and_writes_nothing(
    client: Client, open_window_poll: Poll, operator: User
) -> None:
    """The disabled attribute on the confirm button is UI only; the view must
    refuse the POST itself, since a form can be submitted directly."""
    _grant(open_window_poll, operator)
    client.force_login(operator)
    bad = "Nom,Prénoms,NNE\nDupont,Émile,12\n"
    upload = SimpleUploadedFile("roll.csv", bad.encode(), content_type="text/csv")
    client.post(f"/fr/mairie/scrutin/{open_window_poll.pk}/liste-electorale/", {"file": upload})

    review_url = f"/fr/mairie/scrutin/{open_window_poll.pk}/liste-electorale/verification/"
    client.post(
        review_url,
        {
            "col_last_name": "Nom",
            "col_first_names": "Prénoms",
            "col_nne": "NNE",
            "action": "confirm",
        },
    )
    # The fixture's own entry, untouched: a blocking report writes nothing.
    assert WorkingRollEntry.objects.count() == 1


def test_review_with_no_draft_sends_back_to_upload(
    client: Client, open_window_poll: Poll, operator: User
) -> None:
    _grant(open_window_poll, operator)
    client.force_login(operator)
    response = client.get(
        f"/fr/mairie/scrutin/{open_window_poll.pk}/liste-electorale/verification/", follow=True
    )
    assert "Import de la liste" in response.content.decode()
    assert response.redirect_chain


def test_xlsx_upload_works_end_to_end(
    client: Client, open_window_poll: Poll, operator: User
) -> None:
    _grant(open_window_poll, operator)
    client.force_login(operator)
    data = _xlsx_bytes([["Nom", "Prénoms", "NNE"], ["Dupont", "Émile", "123456789"]])
    upload = SimpleUploadedFile(
        "roll.xlsx", data, content_type="application/vnd.openxmlformats-officedocument"
    )
    client.post(f"/fr/mairie/scrutin/{open_window_poll.pk}/liste-electorale/", {"file": upload})

    review_url = f"/fr/mairie/scrutin/{open_window_poll.pk}/liste-electorale/verification/"
    client.post(
        review_url,
        {
            "col_last_name": "Nom",
            "col_first_names": "Prénoms",
            "col_nne": "NNE",
            "action": "confirm",
        },
    )
    assert WorkingRollEntry.objects.count() == 1


def test_an_entry_operator_cannot_reach_the_screen(
    client: Client, open_window_poll: Poll, operator: User
) -> None:
    PollRole.objects.create(poll=open_window_poll, user=operator, role=Role.ENTRY_OPERATOR)
    client.force_login(operator)
    assert (
        client.get(f"/fr/mairie/scrutin/{open_window_poll.pk}/liste-electorale/").status_code == 403
    )
