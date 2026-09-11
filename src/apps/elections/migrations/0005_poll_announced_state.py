# SPDX-License-Identifier: 0BSD
# R-3.10: the optional ``announced`` waypoint between ``draft`` and ``open``.
# Adds a choice to an existing CharField — no schema change (``sqlmigrate``
# shows a no-op on SQLite), so none of 0003's trigger drop/recreate dance is
# needed here.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("elections", "0004_polltemplate"),
    ]

    operations = [
        migrations.AlterField(
            model_name="poll",
            name="state",
            field=models.CharField(
                choices=[
                    ("draft", "brouillon"),
                    ("announced", "annoncé"),
                    ("open", "ouvert"),
                    ("closed", "clos"),
                    ("published", "publié"),
                ],
                default="draft",
                max_length=20,
            ),
        ),
    ]
