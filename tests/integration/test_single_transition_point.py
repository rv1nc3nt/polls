# SPDX-License-Identifier: 0BSD
"""§5.1 — ``state`` is assigned in exactly one module.

Python cannot make an illegal transition a compile error, so the enforcement is
layered: one guarded transition function, ``Poll.save()``, and the triggers.
This test is the layer that keeps the first of those true as the tree grows.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
ALLOWED = {SRC / "apps" / "elections" / "transitions.py"}

#: ``state`` is also a field on ``Registration``, whose lifecycle is §6.2's and
#: not §4's. The AST cannot tell one object from the other, so the exemption is
#: by the enum being *assigned*, and the default stays "flag it": an assignment
#: this list does not explain is reported, whatever it turns out to be.
NON_POLL_STATE_ENUMS = frozenset({"RegistrationState"})


def _assigns_poll_state(path: Path) -> bool:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        targets: list[ast.expr]
        value: ast.expr | None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AugAssign | ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            if not (isinstance(target, ast.Attribute) and target.attr == "state"):
                continue
            assigned = ast.unparse(value) if value is not None else ""
            if any(enum in assigned for enum in NON_POLL_STATE_ENUMS):
                continue
            return True
    return False


def test_only_the_transition_module_assigns_poll_state() -> None:
    offenders = [
        path
        for path in SRC.rglob("*.py")
        if "migrations" not in path.parts and path not in ALLOWED and _assigns_poll_state(path)
    ]
    assert offenders == [], (
        "state is assigned outside apps.elections.transitions: "
        f"{[str(p.relative_to(SRC)) for p in offenders]}"
    )


def test_the_reference_table_matches_the_triggers_real_enforcement() -> None:
    """``transitions.TRANSITIONS`` is documentation, not enforcement — the
    ``poll_state_irreversible`` trigger is what actually holds (its own
    migration comment says so). Nothing previously checked the two stayed in
    step, so the dict could drift silently from the trigger it describes the
    moment either one gained an edge the other didn't.

    Reads the trigger's SQL directly from the latest migration that redefines
    it, rather than hitting a live database, so this stays a pure, DB-free
    check of the two source texts against each other.
    """
    import re

    from apps.elections.transitions import TRANSITIONS

    migrations_dir = SRC / "apps" / "elections" / "migrations"
    # The trigger is dropped and redefined by several migrations along the way
    # (0002, 0006, 0007 — see 0006/0007's own comments on why SQLite forces
    # this dance) but not by every migration since; the current definition is
    # whichever of those that actually redefines it sorts last, not simply the
    # newest migration file in the app.
    candidates = sorted(p for p in migrations_dir.glob("*.py") if re.match(r"\d{4}_", p.name))
    defining = [p for p in candidates if "CREATE TRIGGER poll_state_irreversible" in p.read_text()]
    assert defining, "no migration defines poll_state_irreversible"
    latest = defining[-1]
    sql = latest.read_text()

    edges = set(
        re.findall(
            r"OLD\.state = '(\w+)'\s+AND NEW\.state = '(\w+)'",
            sql,
        )
    )
    assert edges, f"no poll_state_irreversible edges found in {latest.name}"

    from_dict = {
        (str(source), str(target)) for source, targets in TRANSITIONS.items() for target in targets
    }
    assert from_dict == edges, (
        f"TRANSITIONS and the {latest.name} trigger disagree: "
        f"only in TRANSITIONS: {from_dict - edges}; only in the trigger: {edges - from_dict}"
    )
