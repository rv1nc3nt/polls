# SPDX-License-Identifier: 0BSD
# The clock refuses, the state admits (decision log #33, §5.1, INV-2): the
# INV-2 ``INSERT``/``UPDATE`` triggers on ballots and registrations refuse any
# write to a poll that is not ``open``. Their ``withdrawn``-only short-circuit
# of 0007 becomes the general case, placed where it was, ahead of the clock
# checks, which are unchanged: the closing bounds stay the clock's alone, so a
# ``close_poll`` that runs late still admits nothing late. The delete triggers
# (0013) are untouched — the retention purge and sandbox deletion act on polls
# that are not ``open`` by design.
#
# SQLite has no ALTER TRIGGER: each is dropped and recreated, as 0012 and 0013
# do.
import importlib

from django.db import migrations

_withdrawn = importlib.import_module("apps.elections.migrations.0007_poll_withdrawn_state")
_sandbox = importlib.import_module("apps.elections.migrations.0013_sandbox_deletion")

NAMES = {
    "inv2_registration_insert_window": _withdrawn.REGISTRATION_WINDOW,
    "inv2_registration_update_window": _withdrawn.REGISTRATION_WINDOW,
    "inv2_ballot_insert_window": _withdrawn.BALLOT_WINDOW,
    "inv2_ballot_update_window": _withdrawn.BALLOT_WINDOW,
}

#: Trigger name -> the definition live before this migration (0007's).
PREVIOUS = {name: _sandbox._one(block, name) for name, block in NAMES.items()}


def _requires_open(name: str) -> str:
    """``PREVIOUS[name]`` with ``= 'withdrawn'`` widened to ``<> 'open'``. The
    old text must occur exactly once, so drift in 0007 fails here rather than
    producing a trigger that still admits a ``draft`` poll."""
    statement = PREVIOUS[name]
    old = "WHERE id = NEW.poll_id) = 'withdrawn'\n"
    assert statement.count(old) == 1, name
    return statement.replace(old, "WHERE id = NEW.poll_id) <> 'open'\n")


#: Trigger name -> the definition this migration installs. Module-level so a
#: later migration that has to drop and recreate every trigger (see 0011) can
#: reinstate these rather than 0007's.
CURRENT = {name: _requires_open(name) for name in NAMES}


def _drop(names: list[str]) -> str:
    return "\n".join(f"DROP TRIGGER IF EXISTS {name};" for name in names)


class Migration(migrations.Migration):
    dependencies = [
        ("elections", "0013_sandbox_deletion"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_drop(list(CURRENT)) + "\n" + "\n".join(CURRENT.values()),
            reverse_sql=_drop(list(PREVIOUS)) + "\n" + "\n".join(PREVIOUS.values()),
        ),
    ]
