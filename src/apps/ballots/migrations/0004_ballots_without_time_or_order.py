# SPDX-License-Identifier: 0BSD
# INV-1 (decision log #42): a ballot no longer records when it was cast, nor in
# which order. A first ballot follows, within minutes, the registration confirmed
# from the same page, so its creation instant — or merely its place in the
# table — would pair the two lists §7 makes irreconcilable. Three changes:
#
# 1. ``Ballot.created_at`` is dropped, with every value it held.
# 2. The table is rebuilt ``WITHOUT ROWID``. An ordinary SQLite table keeps an
#    insertion-ordered ``rowid`` beside its own primary key, so ``SELECT rowid``
#    would give the order of casting even with no time column. Without it, rows
#    are stored by their random UUID. Django has no option for this; a test
#    (``tests/integration/test_ballot_timing.py``) fails if a later migration's
#    table rebuild brings the rowid back.
# 3. The back-office trend (R-11.5 bis), which cut its points from those
#    instants, now records each point as it falls due (``TrendSnapshot``,
#    ``apps.ballots.trendpoints``). The points every existing poll had reached
#    are computed here, from the instants, before they are dropped — by the
#    rule the trend used until now — and each ballot gets the epoch it would
#    have had: how many points had been taken when it was first cast.
#
# The rebuild drops every trigger in the database, rebuilds the table, and
# recreates them from their own text, unchanged: SQLite's table rename trips
# over any trigger that reads a table mid-rebuild (elections 0010's comment).
# The backfill is written here, not imported, so this migration keeps working
# whatever the application code becomes. Not reversible: the instants are gone.
import json
import uuid
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import django.db.models.deletion
from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

#: The trend's rule as it stood: a point every STEP ballots counted.
STEP = 10
#: Versions that counted for the trend (§3.4): the live one, or a superseded
#: one until its successor arrived. Pending and deleted entries count nothing.
COUNTED = ("live", "superseded")

OLD_COLUMN = '"created_at" datetime NOT NULL, '
NEW_COLUMN = '"epoch" integer unsigned NOT NULL CHECK ("epoch" >= 0), '

TREND_POINT_IMMUTABLE = """
CREATE TRIGGER inv3_trend_point_no_update
BEFORE UPDATE ON ballots_trendsnapshot
BEGIN
    SELECT RAISE(ABORT, 'R-11.5 bis: a trend point never changes once taken');
END;

CREATE TRIGGER inv3_trend_point_no_delete
BEFORE DELETE ON ballots_trendsnapshot
FOR EACH ROW WHEN (SELECT is_sandbox FROM elections_poll WHERE id = OLD.poll_id) = 0
BEGIN
    SELECT RAISE(ABORT, 'R-11.5 bis: a trend point is never removed');
END;
"""


def _ordering_table(ballots: list[list[list[str]]], options: list[str]) -> list[dict[str, Any]]:
    """Ballots per distinct ranking, as ``tally.trend.encode`` stores them:
    groups in the poll's option order, unknown options and empty groups left
    out, rows sorted so equal tables are equal text."""
    position = {o: k for k, o in enumerate(options)}
    table: dict[tuple[tuple[str, ...], ...], int] = {}
    for ranking in ballots:
        key = tuple(
            g
            for g in (
                tuple(sorted((o for o in group if o in position), key=position.__getitem__))
                for group in ranking
            )
            if g
        )
        table[key] = table.get(key, 0) + 1
    rows = [{"ranking": [list(g) for g in key], "count": n} for key, n in table.items()]
    return sorted(rows, key=lambda row: (str(row["ranking"]), row["count"]))


def _instant(value: str | datetime) -> datetime:
    """A stored ``created_at``: UTC, without an offset, as Django writes it.
    Django's SQLite connection parses a ``datetime`` column into a naive
    ``datetime``; a bare ``sqlite3`` cursor returns the text."""
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def _backfill(cursor: Any) -> dict[str, int]:
    """Record every point each poll had reached, and return the epoch of each
    ballot chain, by tracking code and poll."""
    cursor.execute("SELECT poll_id, tracking_code, status, ranking, created_at FROM ballots_ballot")
    by_poll: dict[str, list[tuple[str, str, str, Any]]] = {}
    for poll_id, code, status, ranking, created_at in cursor.fetchall():
        by_poll.setdefault(poll_id, []).append((code, status, ranking, created_at))

    epochs: dict[str, int] = {}
    for poll_id, rows in by_poll.items():
        cursor.execute("SELECT timezone FROM elections_poll WHERE id = %s", [poll_id])
        zone = ZoneInfo(cursor.fetchone()[0])
        cursor.execute(
            "SELECT option_id FROM elections_polloption WHERE poll_id = %s ORDER BY position",
            [poll_id],
        )
        options = [row[0] for row in cursor.fetchall()]

        ordered = sorted(rows, key=lambda r: (_instant(r[3]), r[0]))
        in_force: dict[str, list[list[str]]] = {}
        first_cast: dict[str, int] = {}
        cuts: list[tuple[int, date, list[list[list[str]]]]] = []
        for n, (code, status, ranking, created_at) in enumerate(ordered, start=1):
            first_cast.setdefault(code, n)
            if status in COUNTED:
                in_force[code] = json.loads(ranking)
            else:
                in_force.pop(code, None)
            if len(in_force) == STEP * (len(cuts) + 1):
                day = _instant(created_at).astimezone(zone).date()
                cuts.append((n, day, list(in_force.values())))

        for sequence, (_n, day, ballots) in enumerate(cuts, start=1):
            cursor.execute(
                "INSERT INTO ballots_trendsnapshot "
                "(id, poll_id, sequence, ballot_count, taken_on, orderings) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [
                    uuid.uuid4().hex,
                    poll_id,
                    sequence,
                    len(ballots),
                    day.isoformat(),
                    json.dumps(_ordering_table(ballots, options)),
                ],
            )
        for code, first in first_cast.items():
            epochs[f"{poll_id}:{code}"] = sum(1 for n, _day, _b in cuts if n < first)
    return epochs


def rebuild(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    with schema_editor.connection.cursor() as cursor:
        epochs = _backfill(cursor)

        cursor.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND sql IS NOT NULL"
        )
        triggers = cursor.fetchall()
        cursor.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'index' AND tbl_name = 'ballots_ballot' AND sql IS NOT NULL"
        )
        indexes = [row[0] for row in cursor.fetchall()]
        cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'ballots_ballot'"
        )
        (table,) = cursor.fetchone()
        assert table.count(OLD_COLUMN) == 1, "ballots_ballot has drifted from 0001's definition"
        new_table = (
            table.replace(OLD_COLUMN, NEW_COLUMN).replace(
                'CREATE TABLE "ballots_ballot"', 'CREATE TABLE "new__ballots_ballot"', 1
            )
            + " WITHOUT ROWID"
        )

        for name, _sql in triggers:
            cursor.execute(f'DROP TRIGGER "{name}"')
        cursor.execute(new_table)
        cursor.execute(
            'INSERT INTO "new__ballots_ballot" '
            "(id, ballot_hash, tracking_code, version, ranking, source, status, epoch, poll_id) "
            "SELECT id, ballot_hash, tracking_code, version, ranking, source, status, 0, poll_id "
            "FROM ballots_ballot"
        )
        for key, epoch in epochs.items():
            if epoch:
                poll_id, code = key.split(":", 1)
                cursor.execute(
                    'UPDATE "new__ballots_ballot" SET epoch = %s '
                    "WHERE poll_id = %s AND tracking_code = %s",
                    [epoch, poll_id, code],
                )
        cursor.execute("DROP TABLE ballots_ballot")
        cursor.execute('ALTER TABLE "new__ballots_ballot" RENAME TO "ballots_ballot"')
        for sql in indexes:
            cursor.execute(sql)
        for _name, sql in triggers:
            cursor.execute(sql)


class Migration(migrations.Migration):
    dependencies = [
        ("ballots", "0003_reconciliationrecord"),
        ("elections", "0016_commitments_write_once"),
        ("registrations", "0003_remove_confirmed_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="TrendSnapshot",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("sequence", models.PositiveIntegerField()),
                ("ballot_count", models.PositiveIntegerField()),
                ("taken_on", models.DateField()),
                ("orderings", models.JSONField()),
                (
                    "poll",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="trend_snapshots",
                        to="elections.poll",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("poll", "sequence"), name="uniq_trend_point_sequence"
                    )
                ],
            },
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name="ballot", name="created_at"),
                migrations.AddField(
                    model_name="ballot",
                    name="epoch",
                    field=models.PositiveIntegerField(default=0),
                ),
            ],
            database_operations=[migrations.RunPython(rebuild)],
        ),
        migrations.RunSQL(
            sql=TREND_POINT_IMMUTABLE,
            reverse_sql=(
                "DROP TRIGGER inv3_trend_point_no_update;\nDROP TRIGGER inv3_trend_point_no_delete;"
            ),
        ),
    ]
