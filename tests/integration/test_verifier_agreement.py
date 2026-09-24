# SPDX-License-Identifier: 0BSD
"""T-10 — the published CSV, and the publication document, re-tallied by the
Rust verifier.

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
from datetime import timedelta
from pathlib import Path

import pytest
from django.test import Client
from django.utils import timezone

from apps.audit.models import Reason
from apps.ballots.models import Ballot, BallotSource
from apps.core.canonical import CanonicalBallot, closure_hash
from apps.core.codes import new_tracking_code
from apps.core.models import User
from apps.core.types import OptionId, TrackingCode
from apps.elections import closure
from apps.elections.models import Poll, PollOption, TiebreakRule
from apps.elections.transitions import close_poll, publish_poll
from apps.tally.methods import Method, tally
from apps.tally.tiebreak import tiebreak_order
from tests.conftest import force_open

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
# Plurality elects a, Schulze b, approval ties all three: a verifier checking
# every poll against Schulze (review note M2) disagrees on two of the three.
DIVERGENT = [
    ("AAAAAAAAAA", [["a"], ["b"], ["c"]]),
    ("BBBBBBBBBB", [["a"], ["b"], ["c"]]),
    ("CCCCCCCCCC", [["a"], ["b"], ["c"]]),
    ("DDDDDDDDDD", [["b"], ["c"], ["a"]]),
    ("EEEEEEEEEE", [["b"], ["c"], ["a"]]),
    ("FFFFFFFFFF", [["c"], ["b"], ["a"]]),
    ("GGGGGGGGGG", [["c"], ["b"], ["a"]]),
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


@pytest.mark.parametrize("method", list(Method), ids=lambda m: str(m))
@pytest.mark.parametrize(
    "rows", [CYCLIC, CLEAR, DIVERGENT], ids=["cyclic-t9", "clear-winner", "divergent"]
)
def test_t10_verifier_agrees_with_the_python_tally(
    rows: list[tuple[str, list[list[str]]]],
    method: Method,
    verifier_binary: Path,
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "ballots.csv"
    write_csv(rows, csv_path)

    ballots = [
        CanonicalBallot(TrackingCode(code), [[OptionId(o) for o in g] for g in ranking])
        for code, ranking in rows
    ]
    # "d" is an option no ballot ranks: passed with --options, the verifier
    # must still agree (review note L5).
    options = [OptionId("a"), OptionId("b"), OptionId("c"), OptionId("d")]
    expected_hash = closure_hash(ballots)
    result = tally([b.ranking for b in ballots], options, method)

    opening_seed = bytes(range(32))
    winner = result.winner or tiebreak_order(result.tied, opening_seed, expected_hash)[0][0]

    completed = subprocess.run(  # noqa: S603
        [
            str(verifier_binary),
            str(csv_path),
            "--method",
            str(method),
            "--options",
            ",".join(options),
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


# --- the publication document, from a real published poll -------------------


def _published(rows: list[tuple[str, list[list[str]]]], method: Method, rule: str) -> Poll:
    """A poll published through the real transitions, so the document the
    verifier reads is the one the site serves. Option ``d`` is never ranked."""
    now = timezone.now()
    poll = Poll.objects.create(
        title_i18n={"fr": "Vérification"},
        description_i18n={"fr": "Accord Python / Rust."},
        languages=["fr"],
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
        tally_method=str(method),
        tiebreak_rule=rule,
    )
    for position, option_id in enumerate("abcd"):
        PollOption.objects.create(
            poll=poll,
            option_id=option_id,
            label_i18n={"fr": f'Option « {option_id} » "é"'},
            position=position,
        )
    force_open(poll)
    for _code, ranking in rows:
        Ballot.objects.create(
            poll=poll,
            tracking_code=new_tracking_code(),
            ranking=ranking,
            source=BallotSource.ONLINE,
        )
    close_poll(poll, early_reason=Reason.ADMINISTRATIVE_DECISION)
    admin = User.objects.create_user(username=f"admin-{poll.pk.hex[:8]}", password="x")
    poll.refresh_from_db()
    if rule == TiebreakRule.PHYSICAL:
        tied = closure.tallied(poll)[2].tied
        if tied:
            closure.record_physical_tiebreak(poll, list(reversed(tied)), admin)
    publish_poll(poll, admin)
    return Poll.objects.get(pk=poll.pk)


def _run(verifier: Path, document: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [str(verifier), str(document)], capture_output=True, text=True, check=False
    )


@pytest.mark.django_db
@pytest.mark.parametrize("rule", [TiebreakRule.COMPUTED, TiebreakRule.PHYSICAL])
@pytest.mark.parametrize("method", list(Method), ids=lambda m: str(m))
@pytest.mark.parametrize(
    "rows", [CYCLIC, CLEAR, DIVERGENT], ids=["cyclic-t9", "clear-winner", "divergent"]
)
def test_the_verifier_agrees_with_the_published_document(
    rows: list[tuple[str, list[list[str]]]],
    method: Method,
    rule: str,
    client: Client,
    verifier_binary: Path,
    tmp_path: Path,
) -> None:
    """Every claim the site publishes — hash, count, matrix, counts, tie-break
    and winner — is recomputed and agreed with, for every method and both
    tie-break rules, with labels that need JSON escaping."""
    poll = _published(rows, method, rule)
    response = client.get(f"/fr/scrutin/{poll.pk}/resultats/?format=json")
    assert response.status_code == 200
    document = tmp_path / "publication.json"
    document.write_bytes(response.content)

    completed = _run(verifier_binary, document)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "DIFFERS" not in completed.stdout
    assert f"method         {method}" in completed.stdout
    tiebreak = json.loads(response.content).get("tiebreak")
    if tiebreak is not None:
        assert tiebreak["rule"] == rule
        assert "tie-break       AGREES" in completed.stdout
        assert ("physical draw" in completed.stdout) == (rule == TiebreakRule.PHYSICAL)


@pytest.mark.django_db
def test_a_tampered_winner_is_caught(client: Client, verifier_binary: Path, tmp_path: Path) -> None:
    poll = _published(DIVERGENT, Method.PLURALITY, TiebreakRule.COMPUTED)
    data = json.loads(client.get(f"/fr/scrutin/{poll.pk}/resultats/?format=json").content)
    assert data["format_version"] == closure.PUBLICATION_FORMAT_VERSION
    assert data["winner"] == "a"
    data["winner"] = "b"
    document = tmp_path / "publication.json"
    document.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    completed = _run(verifier_binary, document)
    assert completed.returncode == 1
    assert "winner          DIFFERS" in completed.stdout
