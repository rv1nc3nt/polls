# SPDX-License-Identifier: 0BSD
"""Every setting read from the environment is one the deploy renders (review A-6).

Ansible re-renders the environment file on every deploy, so a variable it does
not render can only be set by hand, and is silently reset by the next deploy.
Three settings were in that state; this keeps a fourth from joining them.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = ROOT / "src" / "config" / "settings"
TEMPLATE = ROOT / "ansible" / "roles" / "polls" / "templates" / "polls.env.j2"

#: Read from the environment but deliberately not rendered, with the reason.
NOT_RENDERED = {
    # An emergency switch, set by hand and removed once the cause is fixed
    # (guide-administrateur, section 11); rendering it would make it permanent.
    "DJANGO_CSP_REPORT_ONLY",
}


def _read_by_settings() -> set[str]:
    names: set[str] = set()
    for path in SETTINGS.glob("*.py"):
        names |= set(re.findall(r'os\.environ(?:\.get\(|\[)"([A-Z_]+)"', path.read_text()))
    return names


def test_the_deploy_renders_every_environment_setting() -> None:
    rendered = set(re.findall(r"^([A-Z_]+)=", TEMPLATE.read_text(), re.MULTILINE))
    read = _read_by_settings()
    assert read, "no environment read found: the pattern no longer matches the settings"
    assert read - rendered - NOT_RENDERED == set()
    assert NOT_RENDERED <= read, "an exception no setting reads any more"
