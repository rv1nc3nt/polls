# SPDX-License-Identifier: 0BSD
# R-3.7: `poll_deleted`, and `AuditEvent.poll` stops being a constrained,
# protected foreign key so that the log survives the deletion of a sandbox poll
# (INV-3 is absolute: the events stay, they are not cascaded away). Dropping the
# constraint makes SQLite rebuild `audit_auditevent`, which would take its
# append-only triggers down with the old table — they are dropped first and put
# back after, exactly as the elections migrations do around their own rebuilds.

import importlib

import django.db.models.deletion
from django.db import migrations, models

_invariants = importlib.import_module("apps.elections.migrations.0002_invariant_triggers")

DROP = """
DROP TRIGGER IF EXISTS inv3_audit_no_update;
DROP TRIGGER IF EXISTS inv3_audit_no_delete;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0010_alter_auditevent_action"),
        ("elections", "0013_sandbox_deletion"),
    ]

    operations = [
        migrations.RunSQL(sql=DROP, reverse_sql=_invariants.AUDIT_APPEND_ONLY),
        migrations.AlterField(
            model_name="auditevent",
            name="action",
            field=models.CharField(
                choices=[
                    ("poll_created", "scrutin créé"),
                    ("poll_config_changed", "configuration modifiée"),
                    ("poll_image_added", "image du scrutin ajoutée"),
                    ("poll_image_removed", "image du scrutin supprimée"),
                    ("poll_state_changed", "transition d'état"),
                    ("poll_closes_at_extended", "clôture repoussée"),
                    ("poll_withdrawn", "scrutin retiré"),
                    ("poll_deleted", "scrutin d'essai supprimé"),
                    ("preview_link_generated", "lien d'aperçu généré"),
                    ("preview_link_revoked", "lien d'aperçu révoqué"),
                    ("roll_imported", "liste électorale importée"),
                    ("roll_snapshot_taken", "copie figée prise"),
                    ("registration_reviewed", "inscription examinée"),
                    ("registration_duplicate", "tentative de doublon d'inscription"),
                    ("registration_ineligible", "inscription refusée : type de liste non autorisé"),
                    ("paper_ballot_created", "bulletin papier saisi"),
                    ("paper_ballot_corrected", "bulletin papier rectifié"),
                    ("paper_ballot_deleted", "bulletin papier supprimé"),
                    ("paper_ballot_countersigned", "bulletin contresigné"),
                    ("reconciliation_recorded", "rapprochement papier enregistré"),
                    ("closure_override", "clôture forcée"),
                    ("tally_run", "dépouillement effectué"),
                    ("tiebreak_entered", "tirage au sort physique saisi"),
                    ("results_published", "résultats publiés"),
                    ("role_assigned", "rôle attribué"),
                    ("role_revoked", "rôle retiré"),
                    ("mail_settings_changed", "paramètres de messagerie modifiés"),
                    ("commune_settings_changed", "paramètres de la commune modifiés"),
                    ("commune_branding_changed", "image de la commune ajoutée"),
                    ("commune_branding_removed", "image de la commune supprimée"),
                    ("template_created", "modèle enregistré"),
                    ("template_renamed", "modèle renommé"),
                    ("template_deleted", "modèle supprimé"),
                    ("audit_log_accessed", "journal consulté"),
                    ("retention_purge", "purge de rétention"),
                    ("working_roll_purged", "liste de travail purgée"),
                    ("job_refused", "tâche planifiée refusée"),
                ],
                max_length=40,
            ),
        ),
        migrations.AlterField(
            model_name="auditevent",
            name="poll",
            field=models.ForeignKey(
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="audit_events",
                to="elections.poll",
            ),
        ),
        migrations.RunSQL(sql=_invariants.AUDIT_APPEND_ONLY, reverse_sql=DROP),
    ]
