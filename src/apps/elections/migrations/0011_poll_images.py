# SPDX-License-Identifier: 0BSD
# R-3.12, §3.1 bis (revised): images move from per-option (`OptionImage`,
# migration 0008) to a shared per-poll library (`PollImage`), each row now
# carrying its own `short_id` instead of being addressed by its UUID. No
# migration path for existing rows: pre-1.0, no deployment carries data
# through this (docs/specification-decision-log.md). SQLite rebuilds
# `elections_polloption`-adjacent tables under `CreateModel`/`DeleteModel`
# and trips the INV-6 triggers mid-rename — the same drop/recreate dance
# 0003, 0006, 0007, 0008 and 0010 already do. `inv6_pollimage_*_frozen`
# reads `poll_id` directly, unlike `inv6_optionimage_*_frozen`'s join
# through `elections_polloption`, since `PollImage` now has its own.
import importlib
import uuid

import django.db.models.deletion
from django.db import migrations, models

import apps.elections.models

_invariants = importlib.import_module("apps.elections.migrations.0002_invariant_triggers")
_withdrawn = importlib.import_module("apps.elections.migrations.0007_poll_withdrawn_state")
_optionimages = importlib.import_module("apps.elections.migrations.0008_option_details_and_images")
_mandatory_announce = importlib.import_module(
    "apps.elections.migrations.0009_poll_state_mandatory_announce"
)
_preview_token = importlib.import_module("apps.elections.migrations.0010_preview_token")

#: Drops the full set currently live (0010's), including the per-option
#: image triggers this migration retires.
DROP = _preview_token.DROP

POLLIMAGE_FROZEN = """
CREATE TRIGGER inv6_pollimage_insert_frozen
BEFORE INSERT ON elections_pollimage
FOR EACH ROW WHEN (
    SELECT state FROM elections_poll WHERE id = NEW.poll_id
) <> 'draft'
BEGIN
    SELECT RAISE(ABORT, 'INV-6: poll images are frozen outside draft');
END;

CREATE TRIGGER inv6_pollimage_update_frozen
BEFORE UPDATE ON elections_pollimage
FOR EACH ROW WHEN (
    SELECT state FROM elections_poll WHERE id = OLD.poll_id
) <> 'draft'
BEGIN
    SELECT RAISE(ABORT, 'INV-6: poll images are frozen outside draft');
END;

CREATE TRIGGER inv6_pollimage_delete_frozen
BEFORE DELETE ON elections_pollimage
FOR EACH ROW WHEN (
    SELECT state FROM elections_poll WHERE id = OLD.poll_id
) <> 'draft'
BEGIN
    SELECT RAISE(ABORT, 'INV-6: poll images are frozen outside draft');
END;
"""

#: 0010's live set with the per-option image trigger swapped for the
#: per-poll one above.
CURRENT_TRIGGERS = [
    _invariants.POLL_CONFIG_FROZEN,
    _invariants.POLL_OPTIONS_FROZEN,
    _mandatory_announce.POLL_STATE_IRREVERSIBLE,
    _invariants.AUDIT_APPEND_ONLY,
    _invariants.BALLOT_HISTORY_IMMUTABLE,
    _withdrawn.ROLL_SNAPSHOT_FROZEN,
    _withdrawn.REGISTRATION_WINDOW,
    _withdrawn.BALLOT_WINDOW,
    POLLIMAGE_FROZEN,
]

#: 0010's DROP plus the three new trigger names, so a later migration that
#: must repeat this drop/recreate dance can reverse cleanly back through
#: this one too.
DROP_WITH_POLLIMAGE = (
    DROP
    + """
DROP TRIGGER IF EXISTS inv6_pollimage_insert_frozen;
DROP TRIGGER IF EXISTS inv6_pollimage_update_frozen;
DROP TRIGGER IF EXISTS inv6_pollimage_delete_frozen;
"""
)

#: What 0010 left, restated here so this migration's own reversal puts it
#: back exactly.
PREVIOUS_TRIGGERS = "\n".join(_preview_token.CURRENT_TRIGGERS)


class Migration(migrations.Migration):
    dependencies = [
        ("elections", "0010_preview_token"),
    ]

    operations = [
        migrations.RunSQL(sql=DROP, reverse_sql=PREVIOUS_TRIGGERS),
        migrations.DeleteModel(name="OptionImage"),
        migrations.CreateModel(
            name="PollImage",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("short_id", models.PositiveIntegerField()),
                ("file", models.FileField(upload_to=apps.elections.models.poll_image_path)),
                ("content_type", models.CharField(max_length=40)),
                ("content_hash", models.CharField(max_length=64)),
                (
                    "alt_text",
                    models.CharField(blank=True, max_length=300, verbose_name="texte alternatif"),
                ),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                (
                    "poll",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="images",
                        to="elections.poll",
                    ),
                ),
            ],
            options={
                "ordering": ["short_id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("poll", "short_id"), name="uniq_poll_image_short_id"
                    ),
                    models.UniqueConstraint(
                        fields=("poll", "content_hash"), name="uniq_poll_image_content"
                    ),
                ],
            },
        ),
        migrations.RunSQL(sql="\n".join(CURRENT_TRIGGERS), reverse_sql=DROP_WITH_POLLIMAGE),
    ]
