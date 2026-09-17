# SPDX-License-Identifier: 0BSD
"""§10's vocabulary is extended deliberately (``Action``'s own docstring) —
which cuts both ways: nothing here previously caught a value that stopped
being written at all, the way ``CHANNEL_COLLISION_OVERRIDE`` did once R-9.3's
reasoned override was replaced by a flat refusal. A value with no writer left
behind reads, to an auditor, as an action that can happen but never does.
"""

from __future__ import annotations

import re
from pathlib import Path

from apps.audit.models import Action

SRC = Path(__file__).resolve().parents[2] / "src"


def test_every_action_is_written_somewhere() -> None:
    call_sites = "\n".join(
        path.read_text()
        for path in SRC.rglob("*.py")
        if "migrations" not in path.parts and path != SRC / "apps" / "audit" / "models.py"
    )
    unused = [
        member.name for member in Action if not re.search(rf"\bAction\.{member.name}\b", call_sites)
    ]
    assert unused == [], f"Action values with no writer: {unused}"
