# SPDX-License-Identifier: 0BSD
# R-10.2: the §9 artefacts are stored when a poll is published and served from
# there, never re-derived, so a later change to the tally code cannot restate a
# published result (decision log #41).
#
# Both columns are nullable, NULL until publication: SQLite then adds them with
# a plain ``ALTER TABLE ADD COLUMN`` instead of rebuilding ``elections_poll``,
# which would trip every trigger reading that table (0010's comment) and call
# for the drop/recreate dance. The trigger below makes them write-once: once a
# document is stored, neither it nor the CSV beside it may change. A sandbox
# poll's deletion is a DELETE, which this does not concern.
from django.db import migrations, models

PUBLICATION_WRITE_ONCE = """
CREATE TRIGGER inv3_poll_publication_write_once
BEFORE UPDATE ON elections_poll
FOR EACH ROW WHEN OLD.published_document IS NOT NULL AND (
       OLD.published_document IS NOT NEW.published_document
    OR OLD.published_csv      IS NOT NEW.published_csv
)
BEGIN
    SELECT RAISE(ABORT, 'R-10.2: a published result is stored once and never rewritten');
END;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("elections", "0014_inv2_requires_open"),
    ]

    operations = [
        migrations.AddField(
            model_name="poll",
            name="published_csv",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="poll",
            name="published_document",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.RunSQL(
            sql=PUBLICATION_WRITE_ONCE,
            reverse_sql="DROP TRIGGER inv3_poll_publication_write_once;",
        ),
    ]
