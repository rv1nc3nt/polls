# SPDX-License-Identifier: 0BSD
"""The shared ranking shape, validator and form (§6.3, §6.4, R-6.1, T-29)."""

from __future__ import annotations

import pytest

from apps.ballots.forms import RankingForm
from apps.ballots.ranking import BallotRefused, normalise_ranking, validate_ranking
from apps.elections.models import Poll

OPTIONS = ["a", "b", "c"]


# --- normalise_ranking -----------------------------------------------------


def test_normalise_accepts_groups_and_flat_lists() -> None:
    assert normalise_ranking([["a"], ["b"], ["c"]]) == [["a"], ["b"], ["c"]]
    assert normalise_ranking(["a", "b", "c"]) == [["a"], ["b"], ["c"]]
    assert normalise_ranking([["a", "b"], ["c"]]) == [["a", "b"], ["c"]]


def test_normalise_drops_blanks_and_dedupes_within_a_group() -> None:
    assert normalise_ranking([[" a ", "a", ""], [], ["b"]]) == [["a"], ["b"]]


@pytest.mark.parametrize("raw", ["a", 3, {"a": 1}, [{"a": 1}], None])
def test_normalise_rejects_a_malformed_submission(raw: object) -> None:
    with pytest.raises(BallotRefused):
        normalise_ranking(raw)


# --- validate_ranking ----------------------------------------------------


def test_validate_passes_a_strict_complete_ranking() -> None:
    validate_ranking([["a"], ["b"], ["c"]], OPTIONS, require_complete=True, allow_ties=False)


def test_validate_rejects_an_empty_ranking() -> None:
    with pytest.raises(BallotRefused, match="vide"):
        validate_ranking([], OPTIONS, require_complete=False, allow_ties=True)


def test_validate_rejects_an_unknown_option() -> None:
    with pytest.raises(BallotRefused, match="inconnue"):
        validate_ranking([["a"], ["z"]], OPTIONS, require_complete=False, allow_ties=False)


def test_validate_rejects_a_repeated_option() -> None:
    with pytest.raises(BallotRefused, match="plusieurs fois"):
        validate_ranking([["a"], ["a"]], OPTIONS, require_complete=False, allow_ties=False)


def test_validate_rejects_a_tie_where_the_poll_forbids_one() -> None:
    with pytest.raises(BallotRefused, match="ex æquo"):
        validate_ranking([["a", "b"], ["c"]], OPTIONS, require_complete=True, allow_ties=False)
    validate_ranking([["a", "b"], ["c"]], OPTIONS, require_complete=True, allow_ties=True)


def test_validate_enforces_completeness_only_when_required() -> None:
    with pytest.raises(BallotRefused, match="doivent être classées"):
        validate_ranking([["a"]], OPTIONS, require_complete=True, allow_ties=False)
    validate_ranking([["a"]], OPTIONS, require_complete=False, allow_ties=False)


# --- T-45: the accept/reject matrix of R-6.1 ----------------------------

_STRICT_COMPLETE = [["a"], ["b"], ["c"]]
_STRICT_SHORT = [["a"], ["b"]]
_TIED_COMPLETE = [["a", "b"], ["c"]]
_TIED_SHORT = [["a", "b"]]

# (ranking, require_complete, allow_ties, rejection message or None). The
# validator tests the tie before completeness (see ``validate_ranking``), so a
# ranking that is both tied and short is refused for the tie where both apply.
_T45_MATRIX = [
    # A strict, complete ranking is admissible under every configuration.
    (_STRICT_COMPLETE, False, False, None),
    (_STRICT_COMPLETE, False, True, None),
    (_STRICT_COMPLETE, True, False, None),
    (_STRICT_COMPLETE, True, True, None),
    # Incomplete: refused exactly when the poll requires a complete ranking.
    (_STRICT_SHORT, False, False, None),
    (_STRICT_SHORT, False, True, None),
    (_STRICT_SHORT, True, False, "doivent être classées"),
    (_STRICT_SHORT, True, True, "doivent être classées"),
    # Contains a tie: refused exactly when the poll forbids ex æquo.
    (_TIED_COMPLETE, False, False, "ex æquo"),
    (_TIED_COMPLETE, False, True, None),
    (_TIED_COMPLETE, True, False, "ex æquo"),
    (_TIED_COMPLETE, True, True, None),
    # Both at once: admissible only when ties are allowed and completeness is
    # not required; otherwise the tie is reported first, the gap only after.
    (_TIED_SHORT, False, False, "ex æquo"),
    (_TIED_SHORT, False, True, None),
    (_TIED_SHORT, True, False, "ex æquo"),
    (_TIED_SHORT, True, True, "doivent être classées"),
]


@pytest.mark.parametrize(("ranking", "require_complete", "allow_ties", "rejection"), _T45_MATRIX)
def test_t45_incomplete_and_tied_rankings_are_judged_exactly_by_the_two_flags(
    ranking: list[list[str]],
    require_complete: bool,
    allow_ties: bool,
    rejection: str | None,
) -> None:
    """T-45 / R-6.1: ``validate_ranking`` — the server-side layer, which a POST
    straight to the endpoint still goes through (T-29) — accepts or rejects an
    incomplete or tied ranking exactly per ``require_complete_ranking`` and
    ``allow_ties_in_ballot``, and for no other reason.
    """
    if rejection is None:
        validate_ranking(ranking, OPTIONS, require_complete=require_complete, allow_ties=allow_ties)
    else:
        with pytest.raises(BallotRefused, match=rejection):
            validate_ranking(
                ranking, OPTIONS, require_complete=require_complete, allow_ties=allow_ties
            )


@pytest.mark.parametrize("require_complete", [False, True])
@pytest.mark.parametrize("allow_ties", [False, True])
def test_t45_the_poll_fields_are_what_drives_the_decision(
    open_window_poll: Poll, require_complete: bool, allow_ties: bool
) -> None:
    """T-45 / R-6.1: the two named poll fields, not the page, decide. ``RankingForm``
    reads ``poll.require_complete_ranking`` and ``poll.allow_ties_in_ballot`` and
    hands them to ``validate_ranking``; a ranking that is both short and tied is
    admissible only when ties are allowed and a complete ranking is not required.
    """
    open_window_poll.require_complete_ranking = require_complete
    open_window_poll.allow_ties_in_ballot = allow_ties
    form = _form(
        open_window_poll,
        {"order": "a,b,c", "rank_a": "1", "rank_b": "1"},
    )
    expected = allow_ties and not require_complete
    assert form.is_valid() is expected, form.errors
    if expected:
        assert form.cleaned_data["ranking"] == [["a", "b"]]


# --- RankingForm --------------------------------------------------------


def _form(poll: Poll, data: dict[str, str] | None = None) -> RankingForm:
    return RankingForm(data, poll=poll, language="fr")


def test_form_renders_one_select_per_option_in_a_pinned_shuffled_order(
    open_window_poll: Poll,
) -> None:
    form = _form(open_window_poll)
    assert {option_id for option_id, _field in form.ranked_fields()} == set(OPTIONS)
    assert sorted(form["order"].initial.split(",")) == OPTIONS


def test_form_builds_groups_in_ascending_rank(open_window_poll: Poll) -> None:
    open_window_poll.allow_ties_in_ballot = True
    form = _form(
        open_window_poll,
        {"order": "a,b,c", "rank_a": "1", "rank_b": "2", "rank_c": "1"},
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["ranking"] == [["a", "c"], ["b"]]


def test_form_honours_a_pinned_order_on_re_render(open_window_poll: Poll) -> None:
    form = _form(open_window_poll, {"order": "c,a,b"})
    assert [option_id for option_id, _field in form.ranked_fields()] == ["c", "a", "b"]


def test_form_rejects_an_incomplete_ranking_when_the_poll_requires_one(
    open_window_poll: Poll,
) -> None:
    form = _form(open_window_poll, {"order": "a,b,c", "rank_a": "1", "rank_b": "2"})
    assert not form.is_valid()
    assert any("classées" in str(error) for error in form.non_field_errors())


def test_form_rejects_a_tie_by_default(open_window_poll: Poll) -> None:
    form = _form(
        open_window_poll,
        {"order": "a,b,c", "rank_a": "1", "rank_b": "1", "rank_c": "2"},
    )
    assert not form.is_valid()
    assert any("ex æquo" in str(error) for error in form.non_field_errors())
