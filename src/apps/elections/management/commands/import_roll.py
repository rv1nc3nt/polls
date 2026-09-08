# SPDX-License-Identifier: 0BSD
"""Roll import from the terminal (§6.1, R-4.2, R-4.5).

The supported route is screen 3 of the back-office, which has the column
mapping, the validation report and the explicit confirmation the requirement
asks for. This command shares its logic with that screen
(``apps.elections.rollimport``) but skips the wizard: headers are matched by
name, and the run refuses outright if that guess leaves a required field
unmapped, since there is no operator here to correct it by hand — the error
says to use screen 3 instead.

All-or-nothing: one malformed NNE rejects the whole import and writes nothing
(T-11). A new import replaces the working roll entirely and does not touch the
snapshot of an already-open poll (T-26).
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
        missing = [f for f in rollimport.FIELDS if f not in mapping]
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
        report = rollimport.validate(rows)
        self._print_report(report)

        if report.blocking:
            raise CommandError("import refusé : le fichier contient des lignes invalides")

        if options["dry_run"]:
            self.stdout.write(f"{len(rows)} ligne(s) valide(s) (dry run, rien n'est écrit)")
            return

        roll_import = rollimport.apply_import(
            rows,
            filename=path.name,
            file_sha256=bytes.fromhex(rollimport.file_digest(data)),
            operator=operator,
        )
        self.stdout.write(f"{roll_import.row_count} ligne(s) importée(s)")

    def _print_report(self, report: rollimport.ValidationReport) -> None:
        if report.missing_fields:
            self.stderr.write(f"{len(report.missing_fields)} ligne(s) avec un champ manquant")
        if report.malformed_nne:
            self.stderr.write(f"{len(report.malformed_nne)} ligne(s) avec un NNE mal formé")
        if report.duplicate_nne:
            self.stderr.write(f"{len(report.duplicate_nne)} ligne(s) avec un NNE en doublon")
        if report.duplicate_name_nne_mismatch:
            self.stdout.write(
                f"{len(report.duplicate_name_nne_mismatch)} doublon(s) de nom à vérifier "
                "(non bloquant)"
            )
