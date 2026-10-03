# SPDX-License-Identifier: 0BSD
# An option id is part of every record the closure hash covers, and the
# canonical serialisation has no escaping rule: it relies on ids drawn from
# [A-Za-z0-9_-], 1 to 50 characters, which JSON never escapes
# (docs/canonical-serialisation.md, "Alphabets"; review B-7). The form and the
# SlugField already hold to that; these triggers make the database hold to it
# too, for a write that bypasses them, so a poll cannot reach closure with an
# id the serialiser would refuse.
#
# Rows already stored are checked first: the triggers do not look back, and an
# id outside the alphabet would otherwise surface only when its poll closed.
import re
from typing import Any

from django.db import migrations

OUTSIDE = "option_id GLOB '*[^A-Za-z0-9_-]*' OR length(option_id) NOT BETWEEN 1 AND 50"

TRIGGERS = f"""
CREATE TRIGGER polloption_id_alphabet_insert
BEFORE INSERT ON elections_polloption
FOR EACH ROW WHEN {OUTSIDE.replace("option_id", "NEW.option_id")}
BEGIN
    SELECT RAISE(ABORT, 'an option id is 1 to 50 characters of A-Z, a-z, 0-9, _ and -');
END;
CREATE TRIGGER polloption_id_alphabet_update
BEFORE UPDATE OF option_id ON elections_polloption
FOR EACH ROW WHEN {OUTSIDE.replace("option_id", "NEW.option_id")}
BEGIN
    SELECT RAISE(ABORT, 'an option id is 1 to 50 characters of A-Z, a-z, 0-9, _ and -');
END;
"""


def refuse_stored_outliers(apps: Any, schema_editor: Any) -> None:
    # The same alphabet as OUTSIDE, as a regular expression: apps.core.canonical
    # is not imported, since a migration must not change when it does.
    alphabet = re.compile(r"[A-Za-z0-9_-]{1,50}")
    rows = apps.get_model("elections", "PollOption").objects.values_list("poll_id", "option_id")
    outliers = [(poll, option) for poll, option in rows if not alphabet.fullmatch(option)]
    if outliers:
        listed = ", ".join(f"{poll}:{option!r}" for poll, option in outliers)
        raise RuntimeError(
            f"option ids outside [A-Za-z0-9_-]{{1,50}}: {listed}. "
            "Only a write past the form could have stored them; settle each "
            "before deploying this release."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("elections", "0016_commitments_write_once"),
    ]

    operations = [
        migrations.RunPython(refuse_stored_outliers, migrations.RunPython.noop),
        migrations.RunSQL(
            sql=TRIGGERS,
            reverse_sql=(
                "DROP TRIGGER polloption_id_alphabet_insert;"
                "DROP TRIGGER polloption_id_alphabet_update;"
            ),
        ),
    ]
