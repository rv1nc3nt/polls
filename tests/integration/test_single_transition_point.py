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
