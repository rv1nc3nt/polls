# SPDX-License-Identifier: 0BSD
"""T-10 — the published CSV re-tallied by the Rust verifier.

CI asserts agreement on fixtures including the cyclic case of T-9. The verifier
shares no code with the application and was written from
``docs/canonical-serialisation.md``; when the two disagree the resolution is to
return to the specification and determine which is wrong, never to adjust the
verifier until it matches (§14).

Skipped where no Rust toolchain is present, so the ordinary test run stays fast
and dependency-free; the CI job builds the binary first.
"""

from __future__ import annotations

import csv
import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from apps.core.canonical import CanonicalBallot, closure_hash
from apps.core.types import OptionId, TrackingCode
from apps.tally.methods import Method, tally
from apps.tally.tiebreak import break_tie

VERIFIER_DIR = Path(__file__).resolve().parents[2] / "verifier"
pytestmark = pytest.mark.skipif(
    shutil.which("cargo") is None, reason="no Rust toolchain; the verifier job builds it in CI"
)

CYCLIC = [
    ("AAAAAAAAAA", [["a"], ["b"], ["c"]]),
    ("BBBBBBBBBB", [["b"], ["c"], ["a"]]),
    ("CCCCCCCCCC", [["c"], ["a"], ["b"]]),
]
CLEAR = [
    ("AAAAAAAAAA", [["a"], ["b"], ["c"]]),
    ("BBBBBBBBBB", [["a"], ["c"], ["b"]]),
    ("CCCCCCCCCC", [["b"], ["a"], ["c"]]),
]


@pytest.fixture(scope="module")
def verifier_binary() -> Path:
    subprocess.run(
        ["cargo", "build", "--release"],  # noqa: S607
        cwd=VERIFIER_DIR,
        check=True,
        capture_output=True,
    )
    return VERIFIER_DIR / "target" / "release" / "polls-verifier"


def write_csv(rows: list[tuple[str, list[list[str]]]], path: Path) -> None:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["tracking_code", "ranking"])
    for code, ranking in rows:
        writer.writerow([code, json.dumps(ranking, separators=(",", ":"))])
    path.write_text(buffer.getvalue(), encoding="utf-8")


@pytest.mark.parametrize("rows", [CYCLIC, CLEAR], ids=["cyclic-t9", "clear-winner"])
def test_t10_verifier_agrees_with_the_python_tally(
    rows: list[tuple[str, list[list[str]]]], verifier_binary: Path, tmp_path: Path
) -> None:
    csv_path = tmp_path / "ballots.csv"
    write_csv(rows, csv_path)

    ballots = [
        CanonicalBallot(TrackingCode(code), [[OptionId(o) for o in g] for g in ranking])
        for code, ranking in rows
    ]
    options = [OptionId("a"), OptionId("b"), OptionId("c")]
    expected_hash = closure_hash(ballots)
    result = tally([b.ranking for b in ballots], options, Method.SCHULZE)

    opening_seed = bytes(range(32))
    winner = result.winner or break_tie(result.tied, opening_seed, expected_hash)

    completed = subprocess.run(  # noqa: S603
        [
            str(verifier_binary),
            str(csv_path),
            "--closure-hash",
            expected_hash.hex(),
            "--opening-seed",
            opening_seed.hex(),
            "--winner",
            str(winner),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "AGREES" in completed.stdout
