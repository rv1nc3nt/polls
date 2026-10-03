# SPDX-License-Identifier: 0BSD
"""Every vendored font family ships with its licence (review C-9).

The SIL Open Font License requires its text and the copyright notice to
accompany each copy of the font; ``src/static/fonts/README.md`` says where they
come from.
"""

from __future__ import annotations

from pathlib import Path

FONTS = Path(__file__).resolve().parents[2] / "src" / "static" / "fonts"


def test_every_family_has_its_ofl_text() -> None:
    families = {path.name.split("-")[0] for path in FONTS.glob("*.woff2")}
    assert families == {"ibmplexmono", "sourceserif4"}
    for family in families:
        licence = (FONTS / f"OFL-{family}.txt").read_text(encoding="utf-8")
        assert licence.startswith("Copyright")
        assert "SIL OPEN FONT LICENSE Version 1.1" in licence
