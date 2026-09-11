# SPDX-License-Identifier: 0BSD
# R-3.11: the terminal ``withdrawn`` state, reachable only from ``announced``,
# ``open``, ``closed`` or ``published``. ``withdrawn_at`` is a new column, so
# this needs the drop/recreate dance of 0003 (SQLite rebuilds the table on
# ADD COLUMN and trips over the INV-6/INV-7 triggers reading it mid-rename);
# while everything is down anyway, ``poll_state_irreversible`` (R-3.2) grows
# the four new edges, the INV-2/INV-7 ``DELETE`` carve-outs of §11 admit
# ``withdrawn`` alongside ``closed``/``published`` so a poll withdrawn before
# ever closing has an anchor for its own retention purge (R-13.3), and the
# INV-2 ``INSERT``/``UPDATE`` windows refuse unconditionally once a poll is
# withdrawn, ahead of the clock check (T-78).
import importlib

from django.db import migrations, models

_invariants = importlib.import_module("apps.elections.migrations.0002_invariant_triggers")
_announced = importlib.import_module(
    "apps.elections.migrations.0006_poll_state_irreversible_announced"
)

DROP = _invariants.DROP

POLL_STATE_IRREVERSIBLE = """
CREATE TRIGGER poll_state_irreversible
BEFORE UPDATE OF state ON elections_poll
FOR EACH ROW WHEN NEW.state <> OLD.state AND NOT (
       (OLD.state = 'draft'     AND NEW.state = 'announced')
    OR (OLD.state = 'draft'     AND NEW.state = 'open')
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

# The insert/update windows grow a ``withdrawn`` short-circuit ahead of the
# clock check — R-3.11's write-side mirror of ``windows.py``'s application
# check (T-78): a withdrawn poll is never mid-schedule, so there is no "the
# job hasn't run yet" case to stay permissive for, unlike every other value of
# ``state`` this trigger deliberately ignores. The delete trigger is unchanged
# from 0002 save for the ``NOT IN`` list: R-13.3's purge is anchored on
# ``closed_at`` where set, ``withdrawn_at`` otherwise (§11), so the delete
# carve-out must admit ``withdrawn`` exactly as it already admits ``closed``
# and ``published`` — the job's own selection (``due_polls``), not this
# trigger, is what keeps the deletion from running before either anchor ages
# past the retention term.
REGISTRATION_WINDOW = """
CREATE TRIGGER inv2_registration_insert_window
BEFORE INSERT ON registrations_registration
FOR EACH ROW WHEN
    (SELECT state FROM elections_poll WHERE id = NEW.poll_id) = 'withdrawn'
    OR (
        julianday('now') >= julianday(
            (SELECT closes_at FROM elections_poll WHERE id = NEW.poll_id))
        AND NOT (
            NEW.channel = 'paper'
            AND julianday('now') < julianday(
                (SELECT paper_entry_deadline FROM elections_poll WHERE id = NEW.poll_id))
        )
    )
BEGIN
    SELECT RAISE(ABORT, 'INV-2: registrations are closed');
END;

CREATE TRIGGER inv2_registration_update_window
BEFORE UPDATE ON registrations_registration
FOR EACH ROW WHEN
    (SELECT state FROM elections_poll WHERE id = NEW.poll_id) = 'withdrawn'
    OR (
        julianday('now') >= julianday(
            (SELECT closes_at FROM elections_poll WHERE id = NEW.poll_id))
        AND NOT (
            julianday('now') < julianday(
                (SELECT paper_entry_deadline FROM elections_poll WHERE id = NEW.poll_id))
            AND (NEW.channel = 'paper' OR OLD.channel = 'paper')
            AND NEW.poll_id IS OLD.poll_id
            AND NEW.roll_entry_id IS OLD.roll_entry_id
            AND NEW.declared_last_name IS OLD.declared_last_name
            AND NEW.declared_first_names IS OLD.declared_first_names
            AND NEW.declared_dob IS OLD.declared_dob
            AND NEW.email IS OLD.email
            AND NEW.email_canonical IS OLD.email_canonical
            AND NEW.declared_on_honour IS OLD.declared_on_honour
            AND NEW.state IS OLD.state
            AND NEW.review_reason IS OLD.review_reason
            AND NEW.voter_hash IS OLD.voter_hash
            AND NEW.language IS OLD.language
            AND NEW.created_at IS OLD.created_at
            AND NEW.confirmed_at IS OLD.confirmed_at
            AND NEW.reminder_sent_at IS OLD.reminder_sent_at
        )
    )
BEGIN
    SELECT RAISE(ABORT, 'INV-2: registrations are closed');
END;

CREATE TRIGGER inv2_registration_delete_only_after_closure
BEFORE DELETE ON registrations_registration
FOR EACH ROW WHEN (SELECT state FROM elections_poll WHERE id = OLD.poll_id)
                  NOT IN ('closed', 'published', 'withdrawn')
BEGIN
    SELECT RAISE(ABORT, 'INV-2: a registration may only be deleted by the retention purge');
END;
"""

# Same ``withdrawn`` short-circuit as ``REGISTRATION_WINDOW`` above, ahead of
# the per-source clock check 0002 already had.
BALLOT_WINDOW = """
CREATE TRIGGER inv2_ballot_insert_window
BEFORE INSERT ON ballots_ballot
FOR EACH ROW WHEN
    (SELECT state FROM elections_poll WHERE id = NEW.poll_id) = 'withdrawn'
    OR julianday('now') < julianday((SELECT opens_at FROM elections_poll WHERE id = NEW.poll_id))
    OR (NEW.source = 'online' AND julianday('now') >=
        julianday((SELECT closes_at FROM elections_poll WHERE id = NEW.poll_id)))
    OR (NEW.source = 'paper' AND julianday('now') >=
        julianday((SELECT paper_entry_deadline FROM elections_poll WHERE id = NEW.poll_id)))
BEGIN
    SELECT RAISE(ABORT, 'INV-2: outside the voting window for this ballot source');
END;

CREATE TRIGGER inv2_ballot_update_window
BEFORE UPDATE ON ballots_ballot
FOR EACH ROW WHEN
    (SELECT state FROM elections_poll WHERE id = NEW.poll_id) = 'withdrawn'
    OR julianday('now') < julianday((SELECT opens_at FROM elections_poll WHERE id = NEW.poll_id))
    OR (NEW.source = 'online' AND julianday('now') >=
        julianday((SELECT closes_at FROM elections_poll WHERE id = NEW.poll_id)))
    OR (NEW.source = 'paper' AND julianday('now') >=
        julianday((SELECT paper_entry_deadline FROM elections_poll WHERE id = NEW.poll_id)))
BEGIN
    SELECT RAISE(ABORT, 'INV-2: outside the voting window for this ballot source');
END;
"""

ROLL_SNAPSHOT_FROZEN = """
CREATE TRIGGER inv7_rollentry_no_update
BEFORE UPDATE ON elections_rollentry
BEGIN
    SELECT RAISE(ABORT, 'INV-7: the roll snapshot is immutable');
END;

CREATE TRIGGER inv7_rollentry_delete_only_after_closure
BEFORE DELETE ON elections_rollentry
FOR EACH ROW WHEN (SELECT state FROM elections_poll WHERE id = OLD.poll_id)
                  NOT IN ('closed', 'published', 'withdrawn')
BEGIN
    SELECT RAISE(ABORT, 'INV-7: the roll snapshot may only be purged after closure');
END;
"""

TRIGGERS = [
    _invariants.POLL_CONFIG_FROZEN,
    _invariants.POLL_OPTIONS_FROZEN,
    POLL_STATE_IRREVERSIBLE,
    _invariants.AUDIT_APPEND_ONLY,
    _invariants.BALLOT_HISTORY_IMMUTABLE,
    ROLL_SNAPSHOT_FROZEN,
    REGISTRATION_WINDOW,
    BALLOT_WINDOW,
]

# Reversal restores the trigger set exactly as 0006 left it.
PREVIOUS_TRIGGERS = "\n".join(_announced.TRIGGERS)


class Migration(migrations.Migration):
    dependencies = [
        ("elections", "0006_poll_state_irreversible_announced"),
    ]

    operations = [
        migrations.RunSQL(sql=DROP, reverse_sql=PREVIOUS_TRIGGERS),
        migrations.AddField(
            model_name="poll",
            name="withdrawn_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
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
                    ("withdrawn", "retiré"),
                ],
                default="draft",
                max_length=20,
            ),
        ),
        migrations.RunSQL(sql="\n".join(TRIGGERS), reverse_sql=DROP),
    ]
