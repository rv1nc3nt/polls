# SPDX-License-Identifier: 0BSD
"""§8.2 — the screen-2 configuration warnings, as a pure function.

No database: ``configuration_warnings`` is a function of the two scalars screen
2 already holds, so the detection can be tested without a ``Poll`` row.
"""

from __future__ import annotations

from apps.elections.config import configuration_warnings
from apps.elections.models import TallyMethod


def test_plurality_with_ballot_ties_is_flagged() -> None:
    assert configuration_warnings(TallyMethod.PLURALITY, allow_ties_in_ballot=True) == [
        "plurality_allows_ties"
    ]


def test_plurality_without_ballot_ties_is_clean() -> None:
    assert configuration_warnings(TallyMethod.PLURALITY, allow_ties_in_ballot=False) == []


def test_ballot_ties_under_a_ranked_method_are_not_a_warning() -> None:
    # Ties on a Schulze or approval ballot are an ordinary, supported choice
    # (R-6.1); only plurality makes the combination suspect (§8.2).
    assert configuration_warnings(TallyMethod.SCHULZE, allow_ties_in_ballot=True) == []
    assert configuration_warnings(TallyMethod.APPROVAL, allow_ties_in_ballot=True) == []
