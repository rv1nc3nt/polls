# SPDX-License-Identifier: 0BSD
"""The database triggers that actually enforce the invariants (§5.1).

Application-level checks survive only as long as every future code path
remembers them; these hold against ``update()``, ``bulk_update()``, raw SQL, the
Django shell and a maintainer who has not read the specification. INV-4, INV-10
and INV-11 are ``UniqueConstraint``s on the models and are not repeated here.

SQLite dialect. If the PostgreSQL backend is ever enabled these must be
rewritten in PL/pgSQL, and a test suite running against both backends is the
only way to keep the two in step (§14).

Time comparisons use ``julianday`` rather than string ordering: Django writes
UTC with six fractional digits and ``strftime('%f')`` yields three, so a
lexicographic comparison would be subtly wrong for exactly the instants that
matter (T-3, T-34, T-56).
"""

from django.db import migrations

# ---------------------------------------------------------------- INV-6 -----
# Poll configuration is immutable once the poll leaves draft (R-3.3).
# closes_at and paper_entry_deadline are absent from the list: they move
# together through the reasoned extension of R-3.4. The lifecycle fields
# (state, opening_seed, closure_hash, closed_at, frozen_counts,
# closure_override_reason) are not configuration.
POLL_CONFIG_FROZEN = """
CREATE TRIGGER inv6_poll_config_frozen
BEFORE UPDATE ON elections_poll
FOR EACH ROW WHEN OLD.state <> 'draft' AND (
       OLD.title_i18n                 IS NOT NEW.title_i18n
    OR OLD.description_i18n           IS NOT NEW.description_i18n
    OR OLD.languages                  IS NOT NEW.languages
    OR OLD.opens_at                   IS NOT NEW.opens_at
    OR OLD.timezone                   IS NOT NEW.timezone
    OR OLD.tally_method               IS NOT NEW.tally_method
    OR OLD.tally_method_version       IS NOT NEW.tally_method_version
    OR OLD.require_complete_ranking   IS NOT NEW.require_complete_ranking
    OR OLD.allow_ties_in_ballot       IS NOT NEW.allow_ties_in_ballot
    OR OLD.tiebreak_rule              IS NOT NEW.tiebreak_rule
    OR OLD.token_salt                 IS NOT NEW.token_salt
    OR OLD.paper_requires_signed_form IS NOT NEW.paper_requires_signed_form
    OR OLD.paper_requires_countersign IS NOT NEW.paper_requires_countersign
    OR OLD.paper_requires_reconciliation IS NOT NEW.paper_requires_reconciliation
    OR OLD.allow_ballot_modification  IS NOT NEW.allow_ballot_modification
    OR OLD.eligible_list_types        IS NOT NEW.eligible_list_types
    OR OLD.show_live_participation    IS NOT NEW.show_live_participation
    OR OLD.is_sandbox                 IS NOT NEW.is_sandbox
)
BEGIN
    SELECT RAISE(ABORT, 'INV-6: poll configuration is frozen outside draft');
END;
"""

# Options are configuration too: they may not be added, changed or removed once
# the poll is open (R-3.3, T-4).
POLL_OPTIONS_FROZEN = """
CREATE TRIGGER inv6_option_insert_frozen
BEFORE INSERT ON elections_polloption
FOR EACH ROW WHEN (SELECT state FROM elections_poll WHERE id = NEW.poll_id) <> 'draft'
BEGIN
    SELECT RAISE(ABORT, 'INV-6: options are frozen outside draft');
END;

CREATE TRIGGER inv6_option_update_frozen
BEFORE UPDATE ON elections_polloption
FOR EACH ROW WHEN (SELECT state FROM elections_poll WHERE id = OLD.poll_id) <> 'draft'
BEGIN
    SELECT RAISE(ABORT, 'INV-6: options are frozen outside draft');
END;

CREATE TRIGGER inv6_option_delete_frozen
BEFORE DELETE ON elections_polloption
FOR EACH ROW WHEN (SELECT state FROM elections_poll WHERE id = OLD.poll_id) <> 'draft'
BEGIN
    SELECT RAISE(ABORT, 'INV-6: options are frozen outside draft');
END;
"""

# The lifecycle is irreversible (R-3.2). The one transition function of §5.1 is
# the only writer, but the table is what makes a hand-written UPDATE fail too.
POLL_STATE_IRREVERSIBLE = """
CREATE TRIGGER poll_state_irreversible
BEFORE UPDATE OF state ON elections_poll
FOR EACH ROW WHEN NEW.state <> OLD.state AND NOT (
       (OLD.state = 'draft'  AND NEW.state = 'open')
    OR (OLD.state = 'open'   AND NEW.state = 'closed')
    OR (OLD.state = 'closed' AND NEW.state = 'published')
)
BEGIN
    SELECT RAISE(ABORT, 'R-3.2: illegal state transition');
END;
"""

# ---------------------------------------------------------------- INV-3 -----
# Absolute: no update or delete path to the audit log at all, with no exception
# for the retention purge — audit events hold no personal data to redact (§10).
AUDIT_APPEND_ONLY = """
CREATE TRIGGER inv3_audit_no_update
BEFORE UPDATE ON audit_auditevent
BEGIN
    SELECT RAISE(ABORT, 'INV-3: audit_event is append-only');
END;

CREATE TRIGGER inv3_audit_no_delete
BEFORE DELETE ON audit_auditevent
BEGIN
    SELECT RAISE(ABORT, 'INV-3: audit_event is append-only');
END;
"""

# A superseded or deleted ballot version is history: it may not be edited, and
# no ballot row is ever physically removed (§3.4, R-8.5).
BALLOT_HISTORY_IMMUTABLE = """
CREATE TRIGGER inv3_ballot_history_no_update
BEFORE UPDATE ON ballots_ballot
FOR EACH ROW WHEN OLD.status IN ('superseded', 'deleted')
BEGIN
    SELECT RAISE(ABORT, 'INV-3: superseded and deleted ballot versions are immutable');
END;

CREATE TRIGGER inv3_ballot_no_delete
BEFORE DELETE ON ballots_ballot
FOR EACH ROW WHEN (SELECT state FROM elections_poll WHERE id = OLD.poll_id) IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'INV-3: ballot rows are never physically removed');
END;
"""

# ---------------------------------------------------------------- INV-7 -----
# The snapshot is frozen, not immortal: no UPDATE ever, DELETE only once the
# poll is over, which is the retention purge and nothing else (§11).
ROLL_SNAPSHOT_FROZEN = """
CREATE TRIGGER inv7_rollentry_no_update
BEFORE UPDATE ON elections_rollentry
BEGIN
    SELECT RAISE(ABORT, 'INV-7: the roll snapshot is immutable');
END;

CREATE TRIGGER inv7_rollentry_delete_only_after_closure
BEFORE DELETE ON elections_rollentry
FOR EACH ROW WHEN (SELECT state FROM elections_poll WHERE id = OLD.poll_id)
                  NOT IN ('closed', 'published')
BEGIN
    SELECT RAISE(ABORT, 'INV-7: the roll snapshot may only be purged after closure');
END;
"""

# ---------------------------------------------------------------- INV-2 -----
# The voting window, by source. The application checks it too, in one service
# function (§5.1); this is the layer that holds when someone bypasses it.
#
# The purge's exception is expressed *inside* the trigger rather than around it:
# DELETE of a registration is permitted where the poll is over. Disabling the
# trigger for the duration of the job is not an acceptable substitute (§11).
REGISTRATION_WINDOW = """
CREATE TRIGGER inv2_registration_insert_window
BEFORE INSERT ON registrations_registration
FOR EACH ROW WHEN julianday('now') >=
    julianday((SELECT closes_at FROM elections_poll WHERE id = NEW.poll_id))
BEGIN
    SELECT RAISE(ABORT, 'INV-2: registrations are closed');
END;

CREATE TRIGGER inv2_registration_update_window
BEFORE UPDATE ON registrations_registration
FOR EACH ROW WHEN julianday('now') >=
    julianday((SELECT closes_at FROM elections_poll WHERE id = NEW.poll_id))
BEGIN
    SELECT RAISE(ABORT, 'INV-2: registrations are closed');
END;

CREATE TRIGGER inv2_registration_delete_only_after_closure
BEFORE DELETE ON registrations_registration
FOR EACH ROW WHEN (SELECT state FROM elections_poll WHERE id = OLD.poll_id)
                  NOT IN ('closed', 'published')
BEGIN
    SELECT RAISE(ABORT, 'INV-2: a registration may only be deleted by the retention purge');
END;
"""

BALLOT_WINDOW = """
CREATE TRIGGER inv2_ballot_insert_window
BEFORE INSERT ON ballots_ballot
FOR EACH ROW WHEN
       julianday('now') < julianday((SELECT opens_at FROM elections_poll WHERE id = NEW.poll_id))
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
       julianday('now') < julianday((SELECT opens_at FROM elections_poll WHERE id = NEW.poll_id))
    OR (NEW.source = 'online' AND julianday('now') >=
        julianday((SELECT closes_at FROM elections_poll WHERE id = NEW.poll_id)))
    OR (NEW.source = 'paper' AND julianday('now') >=
        julianday((SELECT paper_entry_deadline FROM elections_poll WHERE id = NEW.poll_id)))
BEGIN
    SELECT RAISE(ABORT, 'INV-2: outside the voting window for this ballot source');
END;
"""

TRIGGERS = [
    POLL_CONFIG_FROZEN,
    POLL_OPTIONS_FROZEN,
    POLL_STATE_IRREVERSIBLE,
    AUDIT_APPEND_ONLY,
    BALLOT_HISTORY_IMMUTABLE,
    ROLL_SNAPSHOT_FROZEN,
    REGISTRATION_WINDOW,
    BALLOT_WINDOW,
]

DROP = """
DROP TRIGGER IF EXISTS inv6_poll_config_frozen;
DROP TRIGGER IF EXISTS inv6_option_insert_frozen;
DROP TRIGGER IF EXISTS inv6_option_update_frozen;
DROP TRIGGER IF EXISTS inv6_option_delete_frozen;
DROP TRIGGER IF EXISTS poll_state_irreversible;
DROP TRIGGER IF EXISTS inv3_audit_no_update;
DROP TRIGGER IF EXISTS inv3_audit_no_delete;
DROP TRIGGER IF EXISTS inv3_ballot_history_no_update;
DROP TRIGGER IF EXISTS inv3_ballot_no_delete;
DROP TRIGGER IF EXISTS inv7_rollentry_no_update;
DROP TRIGGER IF EXISTS inv7_rollentry_delete_only_after_closure;
DROP TRIGGER IF EXISTS inv2_registration_insert_window;
DROP TRIGGER IF EXISTS inv2_registration_update_window;
DROP TRIGGER IF EXISTS inv2_registration_delete_only_after_closure;
DROP TRIGGER IF EXISTS inv2_ballot_insert_window;
DROP TRIGGER IF EXISTS inv2_ballot_update_window;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("elections", "0001_initial"),
        ("audit", "0002_initial"),
        ("ballots", "0002_initial"),
        ("registrations", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql="\n".join(TRIGGERS), reverse_sql=DROP),
    ]
