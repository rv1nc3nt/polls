# SPDX-License-Identifier: 0BSD
"""Every acceptance test of §12 is cited by an automated test (review E-7).

A test cites ``T-n`` in its name (``test_tn_…``) or in its docstring or a
comment. The search covers the Python tests, the Rust verifier's tests, the
Molecule scenarios and the CI workflows, which is where T-10, T-16 and T-38
run. Without this, "every acceptance test has a test" could only be checked by
hand, and a spec row added later went unnoticed.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEARCHED = ("tests", "verifier", "ansible", ".github")
SUFFIXES = {".py", ".rs", ".yml", ".yaml", ".sh"}


def _acceptance_ids() -> set[int]:
    spec = (ROOT / "spec-plateforme-vote.md").read_text(encoding="utf-8")
    section = spec[spec.index("## 12. Acceptance tests") : spec.index("## 13. ")]
    return {int(n) for n in re.findall(r"^\| T-(\d+) \|", section, re.MULTILINE)}


def _sources() -> str:
    texts = []
    for top in SEARCHED:
        for path in (ROOT / top).rglob("*"):
            if path.suffix in SUFFIXES and "target" not in path.parts and path.is_file():
                texts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(texts)


def test_the_spec_section_is_found() -> None:
    ids = _acceptance_ids()
    assert len(ids) > 80  # a reworded heading must not make this pass vacuously
    assert {1, 9, 94} <= ids


def test_every_acceptance_test_is_cited_by_a_test() -> None:
    sources = _sources()
    uncited = sorted(
        n for n in _acceptance_ids() if not re.search(rf"\bT-{n}\b|\btest_t{n}(?![0-9])", sources)
    )
    assert not uncited, f"no test cites {', '.join(f'T-{n}' for n in uncited)}"
