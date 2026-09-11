# SPDX-License-Identifier: 0BSD
# R-3.12, §3.1 bis: `PollOption.details_i18n` (an extra column on an existing
# table) and `OptionImage` (a new one). SQLite rebuilds `elections_polloption`
# for the `ADD COLUMN` and trips over the INV-6 triggers reading it mid-rename
# — the same reason 0003, 0006 and 0007 do the drop/recreate dance. While
# everything is down anyway, `OptionImage` gets its own trigger set: it is a
# separate table with no `poll` column of its own, so "frozen outside draft"
# reads the state through `option_id` rather than directly, unlike every
# other INV-6 trigger here.
import importlib
import uuid

import django.db.models.deletion
from django.db import migrations, models

import apps.elections.models

_invariants = importlib.import_module("apps.elections.migrations.0002_invariant_triggers")
_withdrawn = importlib.import_module("apps.elections.migrations.0007_poll_withdrawn_state")

DROP = _invariants.DROP

OPTIONIMAGE_FROZEN = """
CREATE TRIGGER inv6_optionimage_insert_frozen
BEFORE INSERT ON elections_optionimage
FOR EACH ROW WHEN (
    SELECT state FROM elections_poll WHERE id = (
        SELECT poll_id FROM elections_polloption WHERE id = NEW.option_id
    )
) <> 'draft'
BEGIN
    SELECT RAISE(ABORT, 'INV-6: option images are frozen outside draft');
END;

CREATE TRIGGER inv6_optionimage_update_frozen
BEFORE UPDATE ON elections_optionimage
FOR EACH ROW WHEN (
    SELECT state FROM elections_poll WHERE id = (
        SELECT poll_id FROM elections_polloption WHERE id = OLD.option_id
    )
) <> 'draft'
BEGIN
    SELECT RAISE(ABORT, 'INV-6: option images are frozen outside draft');
END;

CREATE TRIGGER inv6_optionimage_delete_frozen
BEFORE DELETE ON elections_optionimage
FOR EACH ROW WHEN (
    SELECT state FROM elections_poll WHERE id = (
        SELECT poll_id FROM elections_polloption WHERE id = OLD.option_id
    )
) <> 'draft'
BEGIN
    SELECT RAISE(ABORT, 'INV-6: option images are frozen outside draft');
END;
"""

TRIGGERS = [*_withdrawn.TRIGGERS, OPTIONIMAGE_FROZEN]

#: This migration's own reversal drops back to exactly what 0007 left.
PREVIOUS_TRIGGERS = "\n".join(_withdrawn.TRIGGERS)

#: 0002's DROP plus the three new trigger names, so a later migration that
#: must repeat this drop/recreate dance can reverse cleanly back through
#: this one too.
DROP_WITH_OPTIONIMAGE = (
    DROP
    + """
DROP TRIGGER IF EXISTS inv6_optionimage_insert_frozen;
DROP TRIGGER IF EXISTS inv6_optionimage_update_frozen;
DROP TRIGGER IF EXISTS inv6_optionimage_delete_frozen;
"""
)


class Migration(migrations.Migration):
    dependencies = [
        ("elections", "0007_poll_withdrawn_state"),
    ]

    operations = [
        migrations.RunSQL(sql=DROP, reverse_sql=PREVIOUS_TRIGGERS),
        migrations.AddField(
            model_name="polloption",
            name="details_i18n",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.CreateModel(
            name="OptionImage",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("file", models.FileField(upload_to=apps.elections.models.option_image_path)),
                ("content_type", models.CharField(max_length=40)),
                ("content_hash", models.CharField(max_length=64)),
                (
                    "alt_text",
                    models.CharField(blank=True, max_length=300, verbose_name="texte alternatif"),
                ),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                (
                    "option",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="images",
                        to="elections.polloption",
                    ),
                ),
            ],
            options={
                "ordering": ["uploaded_at"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("option", "content_hash"), name="uniq_option_image_content"
                    )
                ],
            },
        ),
        migrations.RunSQL(sql="\n".join(TRIGGERS), reverse_sql=DROP_WITH_OPTIONIMAGE),
    ]
