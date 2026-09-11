# SPDX-License-Identifier: 0BSD
# R-3.10: `draft -> announced` and `announced -> open` join the legal
# transitions `poll_state_irreversible` enforces (R-3.2) — the actual
# enforcement of the state machine, distinct from `TRANSITIONS` in
# transitions.py, which is reference only. Every other trigger is unchanged;
# all are dropped and recreated together only because SQLite has no ALTER
# TRIGGER (§5.1: "database triggers are the real enforcement"), the same
# reason 0003 and 0005 do the same dance.
import importlib

from django.db import migrations

_invariants = importlib.import_module("apps.elections.migrations.0002_invariant_triggers")

POLL_STATE_IRREVERSIBLE = """
CREATE TRIGGER poll_state_irreversible
BEFORE UPDATE OF state ON elections_poll
FOR EACH ROW WHEN NEW.state <> OLD.state AND NOT (
       (OLD.state = 'draft'     AND NEW.state = 'announced')
    OR (OLD.state = 'draft'     AND NEW.state = 'open')
    OR (OLD.state = 'announced' AND NEW.state = 'open')
    OR (OLD.state = 'open'      AND NEW.state = 'closed')
    OR (OLD.state = 'closed'    AND NEW.state = 'published')
)
BEGIN
    SELECT RAISE(ABORT, 'R-3.2: illegal state transition');
END;
"""

TRIGGERS = [
    _invariants.POLL_CONFIG_FROZEN,
    _invariants.POLL_OPTIONS_FROZEN,
    POLL_STATE_IRREVERSIBLE,
    _invariants.AUDIT_APPEND_ONLY,
    _invariants.BALLOT_HISTORY_IMMUTABLE,
    _invariants.ROLL_SNAPSHOT_FROZEN,
    _invariants.REGISTRATION_WINDOW,
    _invariants.BALLOT_WINDOW,
]
DROP = _invariants.DROP


class Migration(migrations.Migration):
    dependencies = [
        ("elections", "0005_poll_announced_state"),
    ]

    operations = [
        # Reversal restores the trigger set exactly as 0002/0003/0005 left it
        # (``_invariants.TRIGGERS``, the original ``POLL_STATE_IRREVERSIBLE``
        # included) — not the new one, which is what forward just dropped.
        migrations.RunSQL(sql=DROP, reverse_sql="\n".join(_invariants.TRIGGERS)),
        migrations.RunSQL(sql="\n".join(TRIGGERS), reverse_sql=DROP),
    ]
