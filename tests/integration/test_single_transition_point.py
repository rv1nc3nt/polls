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


def _assigns_poll_state(path: Path) -> bool:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AugAssign | ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Attribute) and target.attr == "state":
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
