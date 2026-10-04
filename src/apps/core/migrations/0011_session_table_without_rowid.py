# SPDX-License-Identifier: 0BSD
# INV-1 (decision log #53): the session table is rebuilt ``WITHOUT ROWID``, for
# the reason ballots migration 0004 rebuilt ``ballots_ballot``. A voter's
# session row is written in the visit that casts their ballot and holds the
# receipt (tracking code and ranking) or, for a modification, the ballot hash.
# An ordinary SQLite table keeps an insertion-ordered ``rowid`` beside its
# primary key, so ``SELECT rowid`` listed tracking codes in the order of
# casting, which is the order ``Ballot`` was rebuilt to forget. Without it the
# rows are stored by their random ``session_key``.
#
# ``django_session`` belongs to ``django.contrib.sessions``, which has no option
# for this; a test (``tests/integration/test_trend_points.py``) fails if a later
# migration rebuilds the table the ordinary way. No trigger reads the table, so
# none needs dropping around the rename. Reversible: the reverse rebuilds it
# with a rowid, as Django created it.
from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

TABLE = "django_session"
SUFFIX = " WITHOUT ROWID"


def _rebuild(schema_editor: BaseDatabaseSchemaEditor, *, without_rowid: bool) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = %s", [TABLE])
        (table,) = cursor.fetchone()
        if table.rstrip().endswith(SUFFIX) == without_rowid:
            return
        cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = %s "
            "AND sql IS NOT NULL",
            [TABLE],
        )
        indexes = [row[0] for row in cursor.fetchall()]
        base = table.rstrip().removesuffix(SUFFIX)
        new_table = base.replace(f'CREATE TABLE "{TABLE}"', f'CREATE TABLE "new__{TABLE}"', 1)
        if without_rowid:
            new_table += SUFFIX
        cursor.execute(new_table)
        cursor.execute(
            'INSERT INTO "new__django_session" (session_key, session_data, expire_date) '
            'SELECT session_key, session_data, expire_date FROM "django_session"'
        )
        cursor.execute('DROP TABLE "django_session"')
        cursor.execute('ALTER TABLE "new__django_session" RENAME TO "django_session"')
        for sql in indexes:
            cursor.execute(sql)


def forwards(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    _rebuild(schema_editor, without_rowid=True)


def backwards(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    _rebuild(schema_editor, without_rowid=False)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_commune_logo_dark"),
        ("sessions", "0001_initial"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
