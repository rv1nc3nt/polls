# SPDX-License-Identifier: 0BSD
"""Seeded random cases, the application against the verifier (review D-2).

Each case is a random poll: 2 to 6 options, 0 to 40 ballots, partial rankings
and ties within a ballot, any of the three methods, and an opening seed so a
tie is always drawn. The application computes the expectation
(``test_vectors.expectation``); the cases are written in the corpus format and
the verifier's own corpus runner (``verifier/core/tests/vectors.rs``) checks
every one. A disagreement names the case, and the seed reproduces it:

    POLLS_DIFFERENTIAL_SEED=<seed> uv run pytest tests/integration/test_differential.py

``POLLS_DIFFERENTIAL_CASES`` sets the count (1000 by default). CI's verifier
job runs more, on a seed of its own each time, so the space is explored rather
than the same thousand cases rechecked.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from apps.core.codes import ALPHABET, LENGTH
from tests.integration.test_vectors import expectation

ROOT = Path(__file__).resolve().parents[2]
SEED = int(os.environ.get("POLLS_DIFFERENTIAL_SEED", "20261003"))
CASES = int(os.environ.get("POLLS_DIFFERENTIAL_CASES", "1000"))
#: Short ids and ones that use the whole alphabet, so sorting within a tie and
#: the order of rows are exercised on more than single letters.
OPTION_IDS = ["a", "b", "c", "d", "e", "f", "opt-1", "Opt_2", "Z9", "x-y_z"]

pytestmark = pytest.mark.skipif(
    shutil.which("cargo") is None, reason="no Rust toolchain; the verifier job runs this in CI"
)


def _ranking(rng: random.Random, options: list[str], ties: bool) -> list[list[str]]:
    placed = rng.sample(options, rng.randint(1, len(options)))
    groups: list[list[str]] = []
    for option in placed:
        if ties and groups and rng.random() < 0.3:
            groups[-1].append(option)
        else:
            groups.append([option])
    return groups


def random_case(rng: random.Random, index: int) -> dict[str, Any]:
    options = rng.sample(OPTION_IDS, rng.randint(2, 6))
    ties = rng.random() < 0.5
    count = rng.choice([0, 1, 2, 3, *range(4, 41)])
    codes: set[str] = set()
    while len(codes) < count:
        codes.add("".join(rng.choice(ALPHABET) for _ in range(LENGTH)))
    case: dict[str, Any] = {
        "name": f"random #{index} (seed {SEED})",
        "source": "application",
        "method": rng.choice(["schulze", "plurality", "approval"]),
        "options": options,
        "ballots": [
            {"tracking_code": code, "ranking": _ranking(rng, options, ties)} for code in codes
        ],
        "opening_seed": rng.randbytes(32).hex(),
    }
    case["expect"] = expectation(case)
    return case


def test_the_verifier_agrees_on_random_polls(tmp_path: Path) -> None:
    # Seeded for reproducible test cases; nothing here draws a tie-break (§8.3).
    rng = random.Random(SEED)  # noqa: S311
    cases = [random_case(rng, index) for index in range(CASES)]
    assert any(case["expect"]["tiebreak_order"] for case in cases), "no tie drawn"
    assert any(not case["ballots"] for case in cases), "no empty poll"
    corpus = tmp_path / "differential.json"
    corpus.write_text(json.dumps({"format": 1, "cases": cases}), encoding="utf-8")
    completed = subprocess.run(  # noqa: S603 — a fixed command
        [  # noqa: S607
            "cargo",
            "test",
            "--quiet",
            "--manifest-path",
            str(ROOT / "verifier/Cargo.toml"),
            "-p",
            "polls-verifier-core",
            "--test",
            "vectors",
        ],
        env={**os.environ, "POLLS_EXTRA_VECTORS": str(corpus)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, (
        f"seed {SEED}, {CASES} cases:\n{completed.stdout[-4000:]}\n{completed.stderr[-4000:]}"
    )
