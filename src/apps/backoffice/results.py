# SPDX-License-Identifier: 0BSD
"""The read model behind screen 9, clôture et publication (§6.5.9).

Screen 9 shows the closure hash, the tally derivation, the tie-break where one
applies, and offers the publication action. Every value here is derived from the
live ballot set and the frozen counts — there is no elector data on this screen
and no join to one (INV-1): the counts come from ``Poll.frozen_counts``, frozen
at closure, and everything else from ``elections.closure``, which recomputes the
tally as the pure function of §8 it is.

The shaping done here is for the template's sake. Django's template language
cannot index a mapping by a variable key, so the pairwise matrix is turned into
rows of cells and the per-ordering summary is relabelled into readable French
before it reaches the page — the same limit ``auditlog.resolve_refs`` and the
roll-import review work around.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.elections import closure
from apps.elections.models import Poll, PollState, TiebreakRule


@dataclass(frozen=True)
class MatrixCell:
    opponent_id: str
    #: ``None`` on the diagonal, where an option is not compared with itself.
    value: int | None


@dataclass(frozen=True)
class MatrixRow:
    option_id: str
    label: str
    cells: list[MatrixCell]


@dataclass(frozen=True)
class LabelledOption:
    option_id: str
    label: str


@dataclass(frozen=True)
class Ordering:
    #: The ranking as readable labels, groups joined by " = " and " > ".
    label: str
    count: int


@dataclass(frozen=True)
class Screen9:
    """Everything the template iterates. ``document`` is the §9 publication
    document verbatim (``elections.closure.publication``); the rest is it,
    reshaped."""

    poll: Poll
    published: bool
    document: dict[str, object]
    option_ids: list[str]
    matrix_rows: list[MatrixRow]
    winner: LabelledOption | None
    tied: list[LabelledOption]
    tiebreak_rule: str
    tiebreak_order: list[LabelledOption]
    #: A physical draw is owed and not yet entered — publication is refused
    #: until it is (§8.3).
    pending_physical_tiebreak: bool
    orderings: list[Ordering]
    override_reason: str


def _labels(poll: Poll) -> dict[str, str]:
    """Option id → the label in the poll's default language (§3.8).

    The default language, not the operator's: this text is quoted in the
    publication and read the same way by everyone, and a missing translation
    falls back rather than blanks (``Poll.translate``).
    """
    return {o.option_id: o.label(poll.default_language) for o in poll.options.all()}


def _relabel_ordering(key: str, labels: dict[str, str]) -> str:
    """``"a=b>c"`` → ``"A = B > C"`` (``ordering_summary`` keys, §9/R-11.3)."""
    groups = [
        " = ".join(labels.get(option_id, option_id) for option_id in group.split("="))
        for group in key.split(">")
    ]
    return " > ".join(groups)


def screen9(poll: Poll) -> Screen9:
    """The read model. Assumes the poll is ``closed`` or ``published`` — the
    view keeps the earlier states on a different branch."""
    document = closure.publication(poll)
    labels = _labels(poll)
    _ballots, options, result = closure.tallied(poll)
    option_ids = [str(o) for o in options]

    matrix_rows = [
        MatrixRow(
            option_id=str(i),
            label=labels.get(str(i), str(i)),
            cells=[
                MatrixCell(
                    opponent_id=str(j),
                    value=None if i == j else result.matrix[i][j],
                )
                for j in options
            ],
        )
        for i in options
    ]

    tiebreak = document.get("tiebreak")
    tiebreak_order: list[LabelledOption] = []
    if isinstance(tiebreak, dict):
        raw_order = tiebreak.get("order")
        for entry in raw_order if isinstance(raw_order, list) else []:
            option_id = entry["option_id"] if isinstance(entry, dict) else str(entry)
            tiebreak_order.append(LabelledOption(option_id, labels.get(option_id, option_id)))

    winner_id = document.get("winner")
    winner = (
        LabelledOption(str(winner_id), labels.get(str(winner_id), str(winner_id)))
        if winner_id
        else None
    )

    orderings_raw = document.get("orderings")
    orderings = [
        Ordering(_relabel_ordering(key, labels), count)
        for key, count in (orderings_raw.items() if isinstance(orderings_raw, dict) else [])
    ]

    return Screen9(
        poll=poll,
        published=poll.state == PollState.PUBLISHED,
        document=document,
        option_ids=option_ids,
        matrix_rows=matrix_rows,
        winner=winner,
        tied=[LabelledOption(str(o), labels.get(str(o), str(o))) for o in result.tied],
        tiebreak_rule=poll.tiebreak_rule,
        tiebreak_order=tiebreak_order,
        pending_physical_tiebreak=(
            poll.tiebreak_rule == TiebreakRule.PHYSICAL
            and closure.unresolved_physical_tiebreak(poll)
        ),
        orderings=orderings,
        override_reason=poll.closure_override_reason,
    )
