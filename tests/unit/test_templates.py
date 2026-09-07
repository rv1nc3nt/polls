# SPDX-License-Identifier: 0BSD
"""Two things about the templates that fail silently (§6.5, R-14.1).

Neither produces an error at render time, which is why they are asserted here:
a template with a syntax error is only found when somebody opens that page, and
a malformed comment is never found at all — it just appears on the page.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.template.loader import get_template

TEMPLATES = sorted((Path(__file__).resolve().parents[2] / "src" / "templates").rglob("*.html"))
COMMENT = re.compile(r"\{#(?:(?!#\}).)*#\}", re.S)


def test_there_are_templates_to_check() -> None:
    assert TEMPLATES


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_no_comment_spans_more_than_one_line(path: Path) -> None:
    """``{# … #}`` is single-line only: Django's lexer does not match it across
    a newline, so a multi-line one is not a comment at all — it renders
    verbatim into the page. Multi-line commentary uses ``{% comment %}``.
    """
    offenders = [
        m.group(0).splitlines()[0] for m in COMMENT.finditer(path.read_text()) if "\n" in m.group(0)
    ]
    assert offenders == [], f"{path.name}: multi-line {{# #}} renders into the page: {offenders}"


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_every_template_compiles(path: Path) -> None:
    """A syntax error otherwise waits for somebody to open that one screen."""
    root = Path(__file__).resolve().parents[2] / "src" / "templates"
    get_template(str(path.relative_to(root)))
