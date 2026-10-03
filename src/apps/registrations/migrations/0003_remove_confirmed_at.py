# SPDX-License-Identifier: 0BSD
# INV-1 (decision log #42): ``Registration.confirmed_at`` recorded, to the
# microsecond, when the elector first followed the mailed link — and their first
# ballot is cast from that same page minutes later, so the two lists §7 keeps
# apart could be paired by time. Nothing read it; it goes, with every value it
# held.
#
# ``inv2_registration_update_window`` names it in the equality list that confines
# the paper carve-out to the channel field (INV-2), and SQLite refuses to drop a
# column a trigger names. The trigger is taken as it stands, the one line naming
# the column removed, and recreated after the column is dropped. ``DROP COLUMN``
# (SQLite 3.35+, which uv's managed Python ships) rewrites the table in place, so
# no other trigger reading it is disturbed. Not reversible: the values are gone.
from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

TRIGGER = "inv2_registration_update_window"
LINE = "            AND NEW.confirmed_at IS OLD.confirmed_at\n"


def drop_confirmed_at(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = %s", [TRIGGER]
        )
        (current,) = cursor.fetchone()
        assert current.count(LINE) == 1, "the INV-2 trigger has drifted from 0014's definition"
        cursor.execute(f"DROP TRIGGER {TRIGGER}")
        cursor.execute('ALTER TABLE registrations_registration DROP COLUMN "confirmed_at"')
        cursor.execute(current.replace(LINE, ""))


class Migration(migrations.Migration):
    dependencies = [
        ("registrations", "0002_allow_blank_address_after_paper_delete"),
        ("elections", "0016_commitments_write_once"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name="registration", name="confirmed_at")
            ],
            database_operations=[migrations.RunPython(drop_confirmed_at)],
        ),
    ]
