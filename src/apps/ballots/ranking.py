# SPDX-License-Identifier: 0BSD
"""Ranking shape and validation, shared by paper entry and the online ballot
page (§6.3, §6.4).

A ranking is an ordered list of groups, each group a list of option ids: a
strict ranking is a list of one-element groups, a tie is a group of more than
one, and an option left out is unranked and ranks equal-last (R-10.4). This is
the shape ``core.canonical`` serialises and the tally consumes.

``require_complete_ranking`` and ``allow_ties_in_ballot`` (R-6.1) are enforced
here, not only in the page: a ballot can be posted straight to the endpoint
(T-29), so the server is the layer that holds.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.utils.translation import gettext as _


class BallotRefused(Exception):
    """A cast, modification or paper entry the server refuses, whatever the
    browser allowed. ``apps.ballots.services`` re-exports it."""


def normalise_ranking(raw: object) -> list[list[str]]:
    """Coerce a submitted ranking to ``list[list[str]]`` or raise.

    Accepts a list of groups (each a list of ids) or a flat list of ids taken
    as a strict ranking. Blank ids and empty groups are dropped, ids stripped,
    duplicates within a group removed with order preserved. Anything else is a
    malformed submission (T-29). Admissibility against the poll's rules is
    ``validate_ranking``'s job, not this one's.
    """
    if not isinstance(raw, list):
        raise BallotRefused(_("Classement illisible."))
    groups: list[list[str]] = []
    for item in raw:
        if isinstance(item, str):
            members: list[str] = [item]
        elif isinstance(item, list):
            members = [str(member) for member in item]
        else:
            raise BallotRefused(_("Classement illisible."))
        group: list[str] = []
        for member in members:
            cleaned = member.strip()
            if cleaned and cleaned not in group:
                group.append(cleaned)
        if group:
            groups.append(group)
    return groups


def validate_ranking(
    ranking: list[list[str]],
    option_ids: Iterable[str],
    *,
    require_complete: bool,
    allow_ties: bool,
) -> None:
    """Raise ``BallotRefused`` unless ``ranking`` is admissible for the poll.

    In order: the ranking is non-empty, every id is a real option of the poll,
    no id appears twice across groups, ties appear only where the poll permits
    them (R-6.1), and — where the poll requires it — every option is placed
    (R-6.1; otherwise the missing ones rank equal-last, R-10.4).
    """
    options = set(option_ids)
    flat = [option_id for group in ranking for option_id in group]

    if not flat:
        raise BallotRefused(_("Le classement est vide."))
    if any(option_id not in options for option_id in flat):
        raise BallotRefused(_("Le classement contient une option inconnue."))
    if len(flat) != len(set(flat)):
        raise BallotRefused(_("Une option est classée plusieurs fois."))
    if not allow_ties and any(len(group) > 1 for group in ranking):
        raise BallotRefused(_("Ce scrutin n'autorise pas les ex æquo."))
    if require_complete and set(flat) != options:
        raise BallotRefused(_("Toutes les propositions doivent être classées."))
