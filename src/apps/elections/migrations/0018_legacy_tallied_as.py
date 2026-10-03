# SPDX-License-Identifier: 0BSD
# Decision log #52. Until migration 0015 (#41) the method version was free
# text that nothing read: every poll was tallied under version 1, whatever its
# label said. A poll whose configuration froze then (announced, opened, closed
# or published) and whose label names no version records here the version it
# was in fact tallied under, so it is still tallied and published under it.
# Its label is left as it is: the configuration is frozen (INV-6), and the
# label is part of what was announced.
#
# Only these polls: one recording a version a later release added would also
# fail to name a version here, and must stay refused, not be tallied under 1.
# A poll still in draft is not touched either; its version can be corrected,
# and announcing refuses it until it is.
#
# A nullable column, so SQLite adds it in place: a default would have rebuilt
# the table and dropped every trigger on it.
from typing import Any

from django.db import migrations, models

#: The versions this migration knows. Not imported from apps.tally: a
#: migration must not change meaning when the code around it does.
KNOWN_VERSIONS = ("1",)


def mark_legacy_labels(apps: Any, schema_editor: Any) -> None:
    Poll = apps.get_model("elections", "Poll")
    (
        Poll.objects.exclude(state="draft")
        .exclude(tally_method_version__in=KNOWN_VERSIONS)
        .update(legacy_tallied_as="1")
    )


def unmark(apps: Any, schema_editor: Any) -> None:
    apps.get_model("elections", "Poll").objects.update(legacy_tallied_as=None)


class Migration(migrations.Migration):
    dependencies = [
        ("elections", "0017_option_id_alphabet"),
    ]

    operations = [
        migrations.AddField(
            model_name="poll",
            name="legacy_tallied_as",
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.RunPython(mark_legacy_labels, unmark),
    ]
