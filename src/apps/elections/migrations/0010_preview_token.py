# SPDX-License-Identifier: 0BSD
# R-3.10 bis: the draft-preview share link. A lifecycle/access field, not
# configuration (models.py's ``FROZEN_CONFIG_FIELDS`` comment) — no trigger
# *logic* change needed, since INV-6's column list deliberately excludes it.
# SQLite still rebuilds ``elections_poll`` for the ``ADD COLUMN`` regardless
# and trips over every trigger that reads that table mid-rename — the same
# reason 0003, 0006, 0007 and 0008 do the drop/recreate dance. Nothing here
# is redefined; the current set (0008's, with 0009's replacement
# ``poll_state_irreversible``) is dropped and put back unchanged.
import importlib

from django.db import migrations, models

_invariants = importlib.import_module("apps.elections.migrations.0002_invariant_triggers")
_withdrawn = importlib.import_module("apps.elections.migrations.0007_poll_withdrawn_state")
_optionimages = importlib.import_module("apps.elections.migrations.0008_option_details_and_images")
_mandatory_announce = importlib.import_module(
    "apps.elections.migrations.0009_poll_state_mandatory_announce"
)

DROP = _optionimages.DROP_WITH_OPTIONIMAGE

#: The live set as of 0009: 0007/0008's composition, with
#: ``poll_state_irreversible`` swapped for 0009's replacement definition.
CURRENT_TRIGGERS = [
    _invariants.POLL_CONFIG_FROZEN,
    _invariants.POLL_OPTIONS_FROZEN,
    _mandatory_announce.POLL_STATE_IRREVERSIBLE,
    _invariants.AUDIT_APPEND_ONLY,
    _invariants.BALLOT_HISTORY_IMMUTABLE,
    _withdrawn.ROLL_SNAPSHOT_FROZEN,
    _withdrawn.REGISTRATION_WINDOW,
    _withdrawn.BALLOT_WINDOW,
    _optionimages.OPTIONIMAGE_FROZEN,
]


class Migration(migrations.Migration):
    dependencies = [
        ("elections", "0009_poll_state_mandatory_announce"),
    ]

    operations = [
        migrations.RunSQL(sql=DROP, reverse_sql="\n".join(CURRENT_TRIGGERS)),
        migrations.AddField(
            model_name="poll",
            name="preview_token",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.RunSQL(sql="\n".join(CURRENT_TRIGGERS), reverse_sql=DROP),
    ]
