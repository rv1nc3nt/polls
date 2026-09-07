# SPDX-License-Identifier: 0BSD
"""Roll import from the terminal (§6.1, R-4.2, R-4.5).

The supported route is screen 3 of the back-office, which has the column
mapping, the validation report and the explicit confirmation the requirement
asks for; this command is the same transactional apply for a headless run.

All-or-nothing: one malformed NNE rejects the whole import and writes nothing
(T-11). A new import replaces the working roll entirely and does not touch the
snapshot of an already-open poll (T-26).
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Importe la liste électorale de travail depuis un fichier .csv ou .xlsx."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("path")
        parser.add_argument("--operator", required=True, help="Identifiant du compte opérateur.")

    def handle(self, *args: Any, **options: Any) -> None:
        # TODO(scaffold): §6.1 — sniff encoding, map columns, validate, apply in
        # one transaction, record RollImport (filename, SHA-256, row count,
        # operator) and the audit event.
        raise NotImplementedError("§6.1")
