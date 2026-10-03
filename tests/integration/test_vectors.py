# SPDX-License-Identifier: 0BSD
"""The shared vector corpus (``tests/vectors/``, review D-2), run against the
application. ``verifier/core/tests/vectors.rs`` runs the same files against
the verifier, so the two implementations answer to one set of expectations
instead of each to a copy of its own.

A case either expects results (closure hash, matrix, winners, counts and, given
an opening seed and a tie, the tie-break order) or names the refusal it must
meet. ``expectation`` is also how ``test_differential.py`` writes the random
cases it hands the verifier.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.ballots.models import Ballot, BallotSource
from apps.ballots.ranking import BallotRefused, validate_ranking
from apps.core.canonical import (
    OPTION_ID,
    CanonicalBallot,
    NonCanonicalValue,
    check_alphabets,
    closure_hash,
)
from apps.core.types import OptionId, TrackingCode
from apps.elections.models import Poll, PollOption
from apps.tally.methods import Method, tally
from apps.tally.tiebreak import tiebreak_order
from tests.conftest import force_open

VECTORS = Path(__file__).resolve().parents[1] / "vectors"


def _canonical(case: dict[str, Any]) -> list[CanonicalBallot]:
    return [
        CanonicalBallot(
            TrackingCode(b["tracking_code"]), [[OptionId(o) for o in g] for g in b["ranking"]]
        )
        for b in case["ballots"]
    ]


def expectation(case: dict[str, Any]) -> dict[str, Any]:
    """What the application computes for ``case``, in the corpus's terms."""
    ballots = _canonical(case)
    digest = closure_hash(ballots)
    result = tally(
        [b.ranking for b in ballots], [OptionId(o) for o in case["options"]], Method(case["method"])
    )
    winners = list(result.derivation["winners"])  # type: ignore[call-overload]
    order = None
    if case.get("opening_seed") and len(winners) > 1:
        drawn = tiebreak_order(winners, bytes.fromhex(case["opening_seed"]), digest)
        order = [option for option, _draw in drawn]
    counts = result.derivation.get("counts")
    return {
        "closure_hash": digest.hex(),
        "matrix": {i: dict(row) for i, row in result.matrix.items()},
        "winners": sorted(winners),
        "counts": dict(counts) if isinstance(counts, dict) else None,
        "tiebreak_order": order,
    }


def _cases(kind: str) -> list[Any]:
    cases = []
    for path in sorted(VECTORS.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["format"] == 1
        for case in document["cases"]:
            if ("refuse" in case) == (kind == "refused"):
                cases.append(pytest.param(case, id=f"{path.stem}: {case['name']}"))
    return cases


@pytest.mark.parametrize("case", _cases("expected"))
def test_the_application_agrees_with_the_corpus(case: dict[str, Any]) -> None:
    assert expectation(case) == case["expect"]


def _refused_without_a_database(case: dict[str, Any]) -> bool:
    kind = case["refuse"]
    try:
        if kind in ("tracking_code", "option_id"):
            for ballot in _canonical(case):
                check_alphabets(ballot)
        elif kind == "ranking":
            for ballot in case["ballots"]:
                validate_ranking(
                    ballot["ranking"], case["options"], require_complete=False, allow_ties=True
                )
        elif kind == "listed_option_id":
            return not all(OPTION_ID.fullmatch(o) for o in case["options"])
    except (NonCanonicalValue, BallotRefused):
        return True
    return False


@pytest.mark.parametrize("case", _cases("refused"))
def test_the_application_refuses_what_the_corpus_refuses(case: dict[str, Any], db: None) -> None:
    if case["refuse"] != "duplicate_tracking_code":
        assert _refused_without_a_database(case)
        return
    # INV-11: the database itself refuses a tracking code twice in one poll.
    now = timezone.now()
    poll = Poll.objects.create(
        title_i18n={"fr": "Vecteurs"},
        description_i18n={"fr": "…"},
        languages=["fr"],
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
    )
    for position, option_id in enumerate(case["options"]):
        PollOption.objects.create(
            poll=poll, option_id=option_id, label_i18n={"fr": option_id}, position=position
        )
    force_open(poll)
    with pytest.raises(IntegrityError), transaction.atomic():
        for ballot in case["ballots"]:
            Ballot.objects.create(
                poll=poll,
                tracking_code=ballot["tracking_code"],
                ranking=ballot["ranking"],
                source=BallotSource.ONLINE,
            )


def test_the_corpus_is_found() -> None:
    assert len(_cases("expected")) >= 15
    assert len(_cases("refused")) >= 10
