# SPDX-License-Identifier: 0BSD
"""No script parses markup from a string (review C-10).

Copying nodes (``cloneNode``, ``template.content``) needs no HTML parser, so
the Content-Security-Policy can add ``require-trusted-types-for 'script'``
without a policy to exempt any of these files.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SCRIPTS = sorted((Path(__file__).resolve().parents[2] / "src" / "static" / "js").glob("*.js"))
MARKUP_SINKS = re.compile(r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write")


def _code(text: str) -> str:
    """The script without its comments, which may name a sink to explain it."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_no_script_writes_markup(script: Path) -> None:
    assert not MARKUP_SINKS.search(_code(script.read_text(encoding="utf-8")))


def test_the_scripts_are_found() -> None:
    assert len(SCRIPTS) >= 6
