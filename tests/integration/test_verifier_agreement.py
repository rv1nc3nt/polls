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
import re
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
from apps.registrations.models import Channel, Registration, RegistrationState
from apps.tally.methods import IMPLEMENTED_VERSIONS, Method, tally
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
# T-39: no ballots, no result. Under Schulze every strongest path is zero, and
# a verifier that read that as an all-way tie disagreed with an honest
# publication (review B-2).
EMPTY: list[tuple[str, list[list[str]]]] = []


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
    "rows",
    [CYCLIC, CLEAR, DIVERGENT, EMPTY],
    ids=["cyclic-t9", "clear-winner", "divergent", "empty-t39"],
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
    winner = result.winner or (
        tiebreak_order(result.tied, opening_seed, expected_hash)[0][0] if result.tied else None
    )

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
            *(["--winner", str(winner)] if winner else []),
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
    # An elector behind every ballot, and one who never voted, so the counts
    # frozen at closure add up as a real poll's do (the verifier checks them).
    for k in range(len(rows) + 1):
        Registration.objects.create(
            poll=poll,
            declared_last_name="X",
            declared_first_names="Y",
            email=f"v{k}@example.fr",
            email_canonical=f"v{k}@example.fr",
            state=RegistrationState.ACTIVE,
            channel=Channel.ONLINE if k < len(rows) else Channel.NONE,
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


def _run(
    verifier: Path, document: Path, *, anchored: Poll | None = None, extra: tuple[str, ...] = ()
) -> subprocess.CompletedProcess[str]:
    """The verifier on a publication document. ``anchored`` passes that poll's
    closure hash, as a reader copies it off the public page at closure: without
    it the document is only shown to agree with itself (review B-1)."""
    anchor = ["--closure-hash", bytes(anchored.closure_hash or b"").hex()] if anchored else []
    return subprocess.run(  # noqa: S603
        [str(verifier), str(document), *anchor, *extra],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("rule", [TiebreakRule.COMPUTED, TiebreakRule.PHYSICAL])
@pytest.mark.parametrize("method", list(Method), ids=lambda m: str(m))
@pytest.mark.parametrize(
    "rows",
    [CYCLIC, CLEAR, DIVERGENT, EMPTY],
    ids=["cyclic-t9", "clear-winner", "divergent", "empty-t39"],
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

    completed = _run(verifier_binary, document, anchored=poll)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "DIFFERS" not in completed.stdout
    assert "hash at closure AGREES" in completed.stdout
    assert "derivation      AGREES" in completed.stdout
    if method == Method.SCHULZE and rows is not EMPTY:
        assert "orderings       AGREES" in completed.stdout
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

    completed = _run(verifier_binary, document, anchored=poll)
    assert completed.returncode == 1
    assert "winner          DIFFERS" in completed.stdout


# --- the command line refuses to pass what it did not check (review B-1) ----


@pytest.mark.parametrize(
    ("extra", "code"),
    [
        ([], 3),  # nothing to compare: not a verification
        (["--closure_hash", "00"], 2),  # misspelt flag
        (["--winner"], 2),  # flag without a value
        (["--closure-hash=" + "00" * 32], 1),  # = form is read, and this hash is wrong
        (["--winner", "a"], 4),  # the winner agrees, with ballots nothing anchors (B-1)
        (["--winner", "b"], 1),  # and a wrong one still differs
    ],
    ids=[
        "nothing-compared",
        "unknown-flag",
        "missing-value",
        "equals-form",
        "winner-not-anchored",
        "wrong-winner",
    ],
)
def test_the_cli_never_exits_zero_without_comparing(
    extra: list[str], code: int, verifier_binary: Path, tmp_path: Path
) -> None:
    csv_path = tmp_path / "ballots.csv"
    write_csv(CLEAR, csv_path)
    completed = subprocess.run(  # noqa: S603
        [str(verifier_binary), str(csv_path), *extra], capture_output=True, text=True, check=False
    )
    assert completed.returncode == code, completed.stdout + completed.stderr


def test_a_repeated_tracking_code_is_refused(verifier_binary: Path, tmp_path: Path) -> None:
    csv_path = tmp_path / "ballots.csv"
    write_csv([*CLEAR, CLEAR[0]], csv_path)
    completed = subprocess.run(  # noqa: S603
        [str(verifier_binary), str(csv_path), "--winner", "a"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "more than one ballot" in completed.stderr


@pytest.mark.django_db
def test_published_counts_that_do_not_add_up_are_caught(
    client: Client, verifier_binary: Path, tmp_path: Path
) -> None:
    """Ballots stuffed into the list, the counts frozen at closure left as
    they were: the ballots by channel no longer make the list (review B-8)."""
    poll = _published(CLEAR, Method.SCHULZE, TiebreakRule.COMPUTED)
    data = json.loads(client.get(f"/fr/scrutin/{poll.pk}/resultats/?format=json").content)
    assert data["counts"]["ballots_online"] == 3 and data["counts"]["non_voters"] == 1
    data["counts"]["ballots_online"] += 2
    document = tmp_path / "publication.json"
    document.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    completed = _run(verifier_binary, document, anchored=poll)
    assert completed.returncode == 1
    assert "participation   DIFFERS" in completed.stdout


@pytest.mark.parametrize(
    "cell",
    ['"[[""a""],[""a""]]"', '"[[""a""],[]]"', '"[[a]]"', '[["a"]]'],
    ids=["ranked-twice", "empty-group", "unquoted-id", "unquoted-cell"],
)
def test_a_ranking_the_platform_never_writes_is_refused(
    cell: str, verifier_binary: Path, tmp_path: Path
) -> None:
    """The CSV is read strictly (review B-6): exit 2, never a verdict."""
    csv_path = tmp_path / "ballots.csv"
    csv_path.write_text(f"tracking_code,ranking\nAAAAAAAAAA,{cell}\n", encoding="utf-8")
    completed = subprocess.run(  # noqa: S603
        [str(verifier_binary), str(csv_path), "--winner", "a"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2, completed.stdout + completed.stderr


@pytest.mark.django_db
@pytest.mark.parametrize("member", ["orderings", "paths"])
def test_a_tampered_derivation_or_orderings_table_is_caught(
    member: str, client: Client, verifier_binary: Path, tmp_path: Path
) -> None:
    """The results page shows the orderings table (R-11.3), and the
    derivation is published with the result: both are checked (review C-1)."""
    poll = _published(CLEAR, Method.SCHULZE, TiebreakRule.COMPUTED)
    data = json.loads(client.get(f"/fr/scrutin/{poll.pk}/resultats/?format=json").content)
    if member == "orderings":
        first = next(iter(data["orderings"]))
        data["orderings"][first] += 1
        line = "orderings       DIFFERS"
    else:
        data["derivation"]["paths"]["a"]["b"] += 1
        line = "derivation      DIFFERS"
    document = tmp_path / "publication.json"
    document.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    completed = _run(verifier_binary, document, anchored=poll)
    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert line in completed.stdout


# --- a document is only verified against the hash noted at closure (B-1) ------


@pytest.mark.django_db
def test_a_document_alone_is_consistent_but_not_verified(
    client: Client, verifier_binary: Path, tmp_path: Path
) -> None:
    """Every check agrees, as it would for a document rebuilt from end to end;
    without the closure hash noted at closure that is not a verification."""
    poll = _published(CLEAR, Method.SCHULZE, TiebreakRule.COMPUTED)
    document = tmp_path / "publication.json"
    document.write_bytes(client.get(f"/fr/scrutin/{poll.pk}/resultats/?format=json").content)

    completed = _run(verifier_binary, document)
    assert completed.returncode == 4, completed.stdout + completed.stderr
    assert "DIFFERS" not in completed.stdout
    assert "NOT ANCHORED" in completed.stdout


@pytest.mark.django_db
def test_a_rebuilt_document_is_caught_by_the_hash_noted_at_closure(
    client: Client, verifier_binary: Path, tmp_path: Path
) -> None:
    """Another poll's document is self-consistent; only the anchor shows it is
    not this poll's."""
    poll = _published(CLEAR, Method.SCHULZE, TiebreakRule.COMPUTED)
    other = _published(DIVERGENT, Method.SCHULZE, TiebreakRule.COMPUTED)
    document = tmp_path / "publication.json"
    document.write_bytes(client.get(f"/fr/scrutin/{other.pk}/resultats/?format=json").content)

    completed = _run(verifier_binary, document, anchored=poll)
    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "hash at closure DIFFERS" in completed.stdout
    assert _run(verifier_binary, document, anchored=other).returncode == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "extra",
    [("--winner", "a"), ("--method", "schulze"), ("--options", "a,b")],
    ids=["winner", "method", "options"],
)
def test_a_document_takes_no_value_it_states_itself(
    extra: tuple[str, ...], client: Client, verifier_binary: Path, tmp_path: Path
) -> None:
    poll = _published(CLEAR, Method.SCHULZE, TiebreakRule.COMPUTED)
    document = tmp_path / "publication.json"
    document.write_bytes(client.get(f"/fr/scrutin/{poll.pk}/resultats/?format=json").content)
    completed = _run(verifier_binary, document, anchored=poll, extra=extra)
    assert completed.returncode == 2, completed.stdout + completed.stderr


# --- method versions: the verifier recounts only those it implements (B-2) ----


@pytest.mark.django_db
def test_a_method_version_the_verifier_does_not_implement_is_refused(
    client: Client, verifier_binary: Path, tmp_path: Path
) -> None:
    poll = _published(CLEAR, Method.SCHULZE, TiebreakRule.COMPUTED)
    data = json.loads(client.get(f"/fr/scrutin/{poll.pk}/resultats/?format=json").content)
    data["tally_method_version"] = "2"
    document = tmp_path / "publication.json"
    document.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    completed = _run(verifier_binary, document, anchored=poll)
    assert completed.returncode == 2, completed.stdout + completed.stderr
    assert "tally method version 2" in completed.stderr


def test_the_verifier_implements_exactly_the_versions_the_tally_does() -> None:
    """A poll the application can tally under a version the verifier lacks
    could never be verified; one the verifier accepts but the application never
    ran would be recounted under rules nobody published (R-10.2)."""
    source = (VERIFIER_DIR / "core" / "src" / "publication.rs").read_text(encoding="utf-8")
    declared = re.search(r"SUPPORTED_METHOD_VERSIONS: &\[&str\] = &\[([^\]]*)\]", source)
    assert declared is not None, "SUPPORTED_METHOD_VERSIONS not found in publication.rs"
    assert re.findall(r'"([^"]*)"', declared.group(1)) == list(IMPLEMENTED_VERSIONS)
