# SPDX-License-Identifier: 0BSD
"""Roll import from the terminal (§6.1, R-4.2, R-4.5).

The supported route is screen 3 of the back-office, which has the column
mapping, the validation report and the explicit confirmation the requirement
asks for. This command shares its logic with that screen
(``apps.elections.rollimport``) but skips the wizard: headers are matched by
name, and the run refuses outright if that guess leaves a mandatory field
unmapped, since there is no operator here to correct it by hand — the error
says to use screen 3 instead.

The validation report informs but does not gate (R-4.5): only a structurally
unusable file — a mandatory column unmapped, or a row with no name — rejects the
import and writes nothing (T-11). Unparseable dates, incomplete rows and
collapsed duplicates are printed and imported. A new import replaces the working
roll entirely and does not touch the snapshot of an already-open poll (T-26).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.core.models import User
from apps.elections import rollimport


class Command(BaseCommand):
    help = "Importe la liste électorale de travail depuis un fichier .csv ou .xlsx."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("path")
        parser.add_argument("--operator", required=True, help="Identifiant du compte opérateur.")
        parser.add_argument(
            "--dry-run", action="store_true", help="Valide et affiche le rapport ; n'écrit rien."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        path = Path(options["path"])
        try:
            operator = User.objects.get(username=options["operator"])
        except User.DoesNotExist as exc:
            raise CommandError(f"compte opérateur inconnu : {options['operator']}") from exc

        try:
            data = path.read_bytes()
        except OSError as exc:
            raise CommandError(f"fichier illisible : {exc}") from exc

        try:
            table = rollimport.read_table(data, path.name)
        except rollimport.UnreadableFile as exc:
            raise CommandError(str(exc)) from exc

        mapping = rollimport.guess_mapping(table.headers)
        missing = [f for f in rollimport.MANDATORY_FIELDS if f not in mapping]
        if missing:
            raise CommandError(
                "colonnes non reconnues pour : "
                + ", ".join(missing)
                + " — en-têtes du fichier : "
                + ", ".join(table.headers)
                + " ; utilisez l'écran « Import de la liste électorale » de "
                "l'espace mairie pour un mappage manuel."
            )

        rows = rollimport.apply_mapping(table, mapping)
        report = rollimport.validate(rows, mapping)
        self._print_report(report)

        if report.blocking:
            raise CommandError("import refusé : le fichier est inexploitable en l'état")

        if options["dry_run"]:
            self.stdout.write(f"{len(rows)} ligne(s) valide(s) (dry run, rien n'est écrit)")
            return

        roll_import = rollimport.apply_import(
            rows,
            mapping,
            filename=path.name,
            file_sha256=bytes.fromhex(rollimport.file_digest(data)),
            operator=operator,
        )
        self.stdout.write(f"{roll_import.row_count} ligne(s) importée(s)")

    def _print_report(self, report: rollimport.ValidationReport) -> None:
        if report.missing_columns:
            self.stderr.write(
                f"colonnes obligatoires non associées : {', '.join(report.missing_columns)}"
            )
        if report.nameless_rows:
            self.stderr.write(f"{len(report.nameless_rows)} ligne(s) sans nom")
        if report.date_uncertain:
            self.stdout.write(
                f"{len(report.date_uncertain)} date(s) de naissance illisible(s) "
                "(importées, signalées, jamais rapprochées automatiquement)"
            )
        if report.incomplete:
            self.stdout.write(f"{len(report.incomplete)} ligne(s) sans type de liste (importées)")
        if report.collapsed:
            self.stdout.write(
                f"{len(report.collapsed)} électeur(s) regroupé(s) sur plusieurs listes"
            )
        if report.indistinguishable:
            self.stdout.write(
                f"{len(report.indistinguishable)} entrée(s) indiscernables sur le nom et la "
                "date de naissance (non bloquant)"
            )
