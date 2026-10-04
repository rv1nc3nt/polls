# SPDX-License-Identifier: 0BSD
"""The version ``GET /sante`` reports (§14, review A-5).

Ansible sets ``APP_VERSION``; a hand install does not, and used to report
``0.1.0-dev``, a version that never existed.
"""

from __future__ import annotations

import re
import tomllib

from django.conf import settings

from config.settings.base import BASE_DIR, project_version


def test_without_app_version_the_source_tree_version_is_reported() -> None:
    with (BASE_DIR / "pyproject.toml").open("rb") as file:
        declared = tomllib.load(file)["project"]["version"]
    assert project_version() == declared
    # PEP 440, as a release is spelt (CLAUDE.md, "Releases").
    assert re.fullmatch(r"\d+\.\d+\.\d+((a|b|rc)\d+)?", declared)


def test_the_setting_never_falls_back_to_a_made_up_version() -> None:
    assert settings.APP_VERSION != "0.1.0-dev"
