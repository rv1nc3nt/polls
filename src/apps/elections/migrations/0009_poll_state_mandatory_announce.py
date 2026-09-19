# SPDX-License-Identifier: 0BSD
# R-3.2/R-3.10: `announced` becomes a mandatory waypoint — `draft → open`
# direct is no longer a legal edge (docs/specification-decision-log.md #19).
# No column changes here, unlike 0007, so this needs none of that migration's
# drop/rebuild dance: `poll_state_irreversible` is the only trigger touched,
# dropped and recreated in place. The previous definition is referenced from
# 0007, not retyped, so `test_single_transition_point.py`'s regex — which
# reads every migration's literal source text for "CREATE TRIGGER
# poll_state_irreversible" — finds this file's current definition only, not
# a second, stale copy sitting in its own reverse_sql.
import importlib

from django.db import migrations

_previous = importlib.import_module("apps.elections.migrations.0007_poll_withdrawn_state")

POLL_STATE_IRREVERSIBLE = """
CREATE TRIGGER poll_state_irreversible
BEFORE UPDATE OF state ON elections_poll
FOR EACH ROW WHEN NEW.state <> OLD.state AND NOT (
       (OLD.state = 'draft'     AND NEW.state = 'announced')
    OR (OLD.state = 'announced' AND NEW.state = 'open')
    OR (OLD.state = 'open'      AND NEW.state = 'closed')
    OR (OLD.state = 'closed'    AND NEW.state = 'published')
    OR (OLD.state = 'announced' AND NEW.state = 'withdrawn')
    OR (OLD.state = 'open'      AND NEW.state = 'withdrawn')
    OR (OLD.state = 'closed'    AND NEW.state = 'withdrawn')
    OR (OLD.state = 'published' AND NEW.state = 'withdrawn')
)
BEGIN
    SELECT RAISE(ABORT, 'R-3.2: illegal state transition');
END;
"""

DROP = "DROP TRIGGER poll_state_irreversible;\n"

# Reversal restores 0007's definition exactly, including its `draft → open`
# edge — referenced from that migration's own module, not retyped here.
PREVIOUS_POLL_STATE_IRREVERSIBLE = _previous.POLL_STATE_IRREVERSIBLE


class Migration(migrations.Migration):
    dependencies = [
        ("elections", "0008_option_details_and_images"),
    ]

    operations = [
        migrations.RunSQL(
            sql=DROP + POLL_STATE_IRREVERSIBLE,
            reverse_sql=DROP + PREVIOUS_POLL_STATE_IRREVERSIBLE,
        ),
    ]
