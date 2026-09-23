# SPDX-License-Identifier: 0BSD
# R-3.7: a sandbox poll may be deleted outright, with everything it holds. The
# delete triggers below all read the poll's state to refuse a removal that is
# not the retention purge (INV-2, INV-3, INV-6, INV-7); each grows one
# exemption, `is_sandbox = 1`, and no other. `is_sandbox` is frozen outside
# `draft` by `inv6_poll_config_frozen`, and a `draft` holds no ballot, no
# registration and no roll snapshot, so the flag cannot be flipped to reach
# real data: the exemption only ever opens rows of a poll that was a test from
# creation.
#
# A real poll used to be undeletable only because `audit_event.poll_id` was a
# protected foreign key. The audit migration that follows drops that
# constraint (the log must outlive a deleted sandbox poll, INV-3), so
# `inv3_poll_no_delete` takes over the guarantee at the table itself.
#
# SQLite has no ALTER TRIGGER: each is dropped and recreated, as 0012 does.
import importlib

from django.db import migrations

_invariants = importlib.import_module("apps.elections.migrations.0002_invariant_triggers")
_withdrawn = importlib.import_module("apps.elections.migrations.0007_poll_withdrawn_state")
_poll_images = importlib.import_module("apps.elections.migrations.0011_poll_images")


def _one(block: str, name: str) -> str:
    """One ``CREATE TRIGGER`` statement out of a block that defines several."""
    for statement in block.split("CREATE TRIGGER ")[1:]:
        if statement.startswith(name + "\n"):
            return "CREATE TRIGGER " + statement.strip() + "\n"
    raise LookupError(name)


NOT_SANDBOX = "(SELECT is_sandbox FROM elections_poll WHERE id = OLD.poll_id) = 0"

#: Trigger name -> the definition live before this migration.
PREVIOUS = {
    "inv2_registration_delete_only_after_closure": _one(
        _withdrawn.REGISTRATION_WINDOW, "inv2_registration_delete_only_after_closure"
    ),
    "inv7_rollentry_delete_only_after_closure": _one(
        _withdrawn.ROLL_SNAPSHOT_FROZEN, "inv7_rollentry_delete_only_after_closure"
    ),
    "inv3_ballot_no_delete": _one(_invariants.BALLOT_HISTORY_IMMUTABLE, "inv3_ballot_no_delete"),
    "inv6_option_delete_frozen": _one(_invariants.POLL_OPTIONS_FROZEN, "inv6_option_delete_frozen"),
    "inv6_pollimage_delete_frozen": _one(
        _poll_images.POLLIMAGE_FROZEN, "inv6_pollimage_delete_frozen"
    ),
}


def _exempt(name: str, *, old: str, new: str) -> str:
    """``PREVIOUS[name]`` with its ``WHEN`` condition extended by the sandbox
    exemption. ``old`` must occur exactly once, so a drift in an earlier
    migration's text fails here rather than silently producing a trigger that
    exempts nothing."""
    statement = PREVIOUS[name]
    assert statement.count(old) == 1, name
    return statement.replace(old, new)


NEW = {
    "inv2_registration_delete_only_after_closure": _exempt(
        "inv2_registration_delete_only_after_closure",
        old="NOT IN ('closed', 'published', 'withdrawn')\n",
        new=f"NOT IN ('closed', 'published', 'withdrawn')\n                  AND {NOT_SANDBOX}\n",
    ),
    "inv7_rollentry_delete_only_after_closure": _exempt(
        "inv7_rollentry_delete_only_after_closure",
        old="NOT IN ('closed', 'published', 'withdrawn')\n",
        new=f"NOT IN ('closed', 'published', 'withdrawn')\n                  AND {NOT_SANDBOX}\n",
    ),
    "inv3_ballot_no_delete": _exempt(
        "inv3_ballot_no_delete",
        old="IS NOT NULL\n",
        new=f"IS NOT NULL\n                  AND {NOT_SANDBOX}\n",
    ),
    "inv6_option_delete_frozen": _exempt(
        "inv6_option_delete_frozen",
        old="<> 'draft'\n",
        new=f"<> 'draft' AND {NOT_SANDBOX}\n",
    ),
    "inv6_pollimage_delete_frozen": _exempt(
        "inv6_pollimage_delete_frozen",
        old=") <> 'draft'\n",
        new=f") <> 'draft' AND {NOT_SANDBOX}\n",
    ),
}

POLL_NO_DELETE_NAME = "inv3_poll_no_delete"
POLL_NO_DELETE = """
CREATE TRIGGER inv3_poll_no_delete
BEFORE DELETE ON elections_poll
FOR EACH ROW WHEN OLD.is_sandbox = 0
BEGIN
    SELECT RAISE(ABORT, 'INV-3: only a sandbox poll may be deleted');
END;
"""


def _drop(names: list[str]) -> str:
    return "\n".join(f"DROP TRIGGER IF EXISTS {name};" for name in names)


class Migration(migrations.Migration):
    dependencies = [
        ("elections", "0012_inv6_early_opening"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_drop(list(NEW)) + "\n" + "\n".join(NEW.values()) + POLL_NO_DELETE,
            reverse_sql=_drop([*NEW, POLL_NO_DELETE_NAME]) + "\n" + "\n".join(PREVIOUS.values()),
        ),
    ]
