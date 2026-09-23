# SPDX-License-Identifier: 0BSD
# R-3.4: opening a poll by hand ahead of `opens_at` pulls `opens_at` back to
# the instant of opening, so the poll is votable and listed from then on
# instead of reading `open` in the back-office while the public site still
# says "not yet open". `inv6_poll_config_frozen` is recreated with that one
# carve-out, no wider: `opens_at` may change only on the `announced → open`
# write itself and only to an earlier instant. SQLite has no ALTER TRIGGER,
# so it is dropped and recreated, as 0003, 0006, 0007, 0008, 0010 and 0011 do.
import importlib

from django.db import migrations

_invariants = importlib.import_module("apps.elections.migrations.0002_invariant_triggers")

POLL_CONFIG_FROZEN = _invariants.POLL_CONFIG_FROZEN.replace(
    "    OR OLD.opens_at                   IS NOT NEW.opens_at\n",
    "    OR (OLD.opens_at IS NOT NEW.opens_at AND NOT (\n"
    "            OLD.state = 'announced' AND NEW.state = 'open'\n"
    "        AND julianday(NEW.opens_at) < julianday(OLD.opens_at)))\n",
)
assert POLL_CONFIG_FROZEN != _invariants.POLL_CONFIG_FROZEN

DROP = "DROP TRIGGER inv6_poll_config_frozen;\n"


class Migration(migrations.Migration):
    dependencies = [
        ("elections", "0011_poll_images"),
    ]

    operations = [
        migrations.RunSQL(
            sql=DROP + POLL_CONFIG_FROZEN,
            reverse_sql=DROP + _invariants.POLL_CONFIG_FROZEN,
        ),
    ]
