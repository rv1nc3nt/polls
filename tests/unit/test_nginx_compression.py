# SPDX-License-Identifier: 0BSD
"""nginx compresses the static files and nothing else (review C-2).

The stylesheet and scripts compress to a third of their size. The application's
pages are left alone: they carry a CSRF token beside what the visitor typed,
and compressing that is the shape BREACH exploits.
"""

from __future__ import annotations

import re
from pathlib import Path

VHOST = (
    Path(__file__).resolve().parents[2] / "ansible/roles/polls/templates/nginx-vhost.conf.j2"
).read_text()


def _block(prefix: str) -> str:
    """The location block, to its closing brace: not the first ``}``, which
    may close a Jinja ``{{ … }}``."""
    start = VHOST.index(f"location {prefix} {{")
    return VHOST[start : VHOST.index("\n    }", start)]


def test_the_static_files_are_compressed() -> None:
    static = _block("/static/")
    assert re.search(r"^\s*gzip on;", static, re.MULTILINE)
    assert "text/css" in static and "application/javascript" in static


def test_compression_is_switched_on_nowhere_else() -> None:
    assert len(re.findall(r"^\s*gzip on;", VHOST, re.MULTILINE)) == 1
    assert "text/html" not in VHOST
