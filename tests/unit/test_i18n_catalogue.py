# SPDX-License-Identifier: 0BSD
"""The English interface catalogue stays complete (§3.8, R-14.3).

Nothing here runs ``makemessages`` — that needs GNU gettext and touches the
working tree — but a *stale* catalogue (a string added to a template or view
without a matching ``locale/en`` entry) is exactly what let 164 strings render
in French for an English-language visitor despite otherwise-correct
language-selection code. ``compilemessages`` alone does not catch this: it only
checks that the ``.po`` file parses, not that it is complete. This is the
cheaper half of that gap — it catches drift *within* the shipped catalogue
(a fuzzy flag, an empty translation) — the other half needs a real
``makemessages`` diff in CI, which belongs in the pipeline config, not here.
"""

from __future__ import annotations

import re
from pathlib import Path

_PO = Path(__file__).resolve().parents[2] / "locale" / "en" / "LC_MESSAGES" / "django.po"


def _entries() -> list[tuple[str, bool, bool, bool]]:
    """``(msgid, is_fuzzy, msgstr_empty, is_header)`` for every entry."""
    text = _PO.read_text(encoding="utf-8")
    blocks = re.split(r"\n\n(?=#)", text)
    out = []
    for block in blocks:
        m = re.search(r'(?m)^msgid ((?:"(?:[^"\\]|\\.)*"\n?)+)', block)
        if not m:
            continue
        msgid = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1)))
        fuzzy = bool(re.search(r"(?m)^#,.*\bfuzzy\b", block))
        if "msgid_plural" in block:
            m0 = re.search(r'(?m)^msgstr\[0\] ((?:"(?:[^"\\]|\\.)*"\n?)+)', block)
            empty = m0 is None or "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m0.group(1))) == ""
        else:
            ms = re.search(r'(?m)^msgstr ((?:"(?:[^"\\]|\\.)*"\n?)+)', block)
            empty = ms is None or "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', ms.group(1))) == ""
        out.append((msgid, fuzzy, empty, msgid == ""))
    return out


def test_the_english_catalogue_has_no_fuzzy_entries() -> None:
    """A fuzzy entry is excluded from the compiled ``.mo`` by ``msgfmt``
    unless ``--use-fuzzy`` is passed — Django's ``compilemessages`` does not
    pass it — so a fuzzy-flagged translation is silently unused, and the page
    falls back to the French ``msgid`` with nothing to say why."""
    fuzzy = [
        msgid for msgid, is_fuzzy, _empty, is_header in _entries() if is_fuzzy and not is_header
    ]
    assert fuzzy == [], f"{len(fuzzy)} fuzzy entries, e.g. {fuzzy[:5]!r}"


def test_the_english_catalogue_has_no_empty_translations() -> None:
    empty = [
        msgid for msgid, _fuzzy, is_empty, is_header in _entries() if is_empty and not is_header
    ]
    assert empty == [], f"{len(empty)} untranslated entries, e.g. {empty[:5]!r}"
