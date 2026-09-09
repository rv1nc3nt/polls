# SPDX-License-Identifier: 0BSD
# §8.3: the ordering a poll admin records after a physical tie-break draw.
import importlib

from django.db import migrations, models

# SQLite has no ADD COLUMN that preserves triggers: it rebuilds the whole table,
# and the rebuild trips over the INV-6/INV-7 triggers of 0002 that read
# ``elections_poll`` (``no such table: main.elections_poll`` mid-rename). Drop
# every invariant trigger for the column add, then recreate them byte-for-byte
# from 0002 — the trigger set is unchanged, only momentarily absent.
_invariants = importlib.import_module("apps.elections.migrations.0002_invariant_triggers")
CREATE = "\n".join(_invariants.TRIGGERS)
DROP = _invariants.DROP


class Migration(migrations.Migration):
    dependencies = [
        ("elections", "0002_invariant_triggers"),
    ]

    operations = [
        migrations.RunSQL(sql=DROP, reverse_sql=CREATE),
        migrations.AddField(
            model_name="poll",
            name="physical_tiebreak_order",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunSQL(sql=CREATE, reverse_sql=DROP),
    ]
