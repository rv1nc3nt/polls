# SPDX-License-Identifier: 0BSD
# R-10.5, R-10.5 bis and R-11.1: the opening seed and the closure hash are
# published the moment they are drawn or computed — on the poll's public page,
# from opening and from closure respectively (decision log #40) — so a reader
# can check that the publication carries the same values. This trigger makes the
# database hold them to it too: each may go from NULL to a value once, and never
# change after. Without it, whoever can write to the database could re-pick a
# computed tie-break by rewriting the seed once the closure hash is known.
#
# `closed_at` is deliberately not covered: it is the retention anchor (§11), not
# a value anyone verifies, and nothing published depends on it.
#
# A plain CREATE TRIGGER; no column changes, so no table rebuild.
from django.db import migrations

COMMITMENTS_WRITE_ONCE = """
CREATE TRIGGER inv3_poll_commitments_write_once
BEFORE UPDATE ON elections_poll
FOR EACH ROW WHEN
       (OLD.opening_seed IS NOT NULL AND OLD.opening_seed IS NOT NEW.opening_seed)
    OR (OLD.closure_hash IS NOT NULL AND OLD.closure_hash IS NOT NEW.closure_hash)
BEGIN
    SELECT RAISE(ABORT, 'R-10.5: the opening seed and the closure hash are set once and never changed');
END;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("elections", "0015_published_artefacts"),
    ]

    operations = [
        migrations.RunSQL(
            sql=COMMITMENTS_WRITE_ONCE,
            reverse_sql="DROP TRIGGER inv3_poll_commitments_write_once;",
        ),
    ]
