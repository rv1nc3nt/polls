# SPDX-License-Identifier: 0BSD
"""Read models for the paper-ballot screens (§6.5.5–7).

Screen 5 shows an elector's identity beside the ranking about to be recorded for
them — the one place §6.5 permits identity next to ballot content, and only
because R-8.2 bis makes the association deliberate and logged. The search is
against the frozen snapshot (R-8.3), ranked and never filtered: an operator who
sees nothing cannot tell "no such elector" from "the search was too narrow".

The reason vocabularies live here, next to the screens that use them, for the
reason ``review`` gives: offering an operator a code that cannot be true on the
decision in front of them is how a code becomes noise (§10).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db.models import Q

from apps.audit.models import Reason
from apps.ballots.models import Ballot, BallotStatus, PaperBallotLink
from apps.core.names import name_tokens, parse_dob
from apps.elections.models import Poll, RollEntry
from apps.registrations.models import Channel, Registration, RegistrationState

#: Screen 6's correction and deletion (R-8.5). Screen 5 needs no vocabulary:
#: a keyed ballot is either recorded or refused, never conditionally recorded.
CORRECTION_REASONS = (Reason.KEYING_ERROR, Reason.VOTER_REQUEST, Reason.OTHER)
DELETION_REASONS = (Reason.VOTER_REQUEST, Reason.KEYING_ERROR, Reason.OTHER)

#: Enough near-matches to cover a misspelling and a household, few enough that
#: the operator reads them all before choosing (R-8.3).
SEARCH_LIMIT = 20

_IN_FORCE = (BallotStatus.LIVE, BallotStatus.PENDING_COUNTERSIGN)


def choices(reasons: tuple[Reason, ...]) -> list[tuple[str, str]]:
    """``(value, label)`` pairs for a template, labels translated per request."""
    return [(str(reason), str(reason.label)) for reason in reasons]


def option_labels(poll: Poll, language: str) -> dict[str, str]:
    """``option_id → label`` in the given language, for rendering a stored
    ranking (which carries ids only, §3.8) on the receipt and screen 6."""
    return {option.option_id: option.label(language) for option in poll.options.all()}


@dataclass(frozen=True)
class SnapshotMatch:
    """A snapshot entry the operator should look at, and why it surfaced."""

    entry: RollEntry
    same_dob: bool
    name_overlap: int
    date_uncertain: bool


def _query_date(query: str) -> date | None:
    for chunk in query.split():
        parsed = parse_dob(chunk)
        if parsed is not None:
            return parsed
    return parse_dob(query)


def snapshot_search(poll: Poll, query: str) -> list[SnapshotMatch]:
    """Frozen-snapshot entries consistent with what the operator typed (R-8.3).

    ``query`` is free text — a surname, a forename, a date of birth, or several
    together. Narrowed in the database by first letter and by parsed date, then
    compared properly in Python (diacritics, particles and hyphens, none of
    which SQL folds), and ranked by how much lines up rather than filtered.
    """
    tokens = name_tokens(query)
    dob = _query_date(query)
    if not tokens and dob is None:
        return []

    narrowed = Q()
    for letter in {token[:1] for token in tokens if token}:
        narrowed |= (
            Q(birth_name__istartswith=letter)
            | Q(usual_name__istartswith=letter)
            | Q(first_names__istartswith=letter)
        )
    if dob is not None:
        narrowed |= Q(date_of_birth_parsed=dob)

    scored: list[SnapshotMatch] = []
    for entry in RollEntry.objects.filter(poll=poll).filter(narrowed)[:400]:
        entry_tokens = (
            name_tokens(entry.birth_name)
            | name_tokens(entry.usual_name)
            | name_tokens(entry.first_names)
        )
        overlap = len(tokens & entry_tokens)
        same_dob = (
            dob is not None and not entry.date_uncertain and entry.date_of_birth_parsed == dob
        )
        if overlap or same_dob:
            scored.append(
                SnapshotMatch(
                    entry=entry,
                    same_dob=same_dob,
                    name_overlap=overlap,
                    date_uncertain=entry.date_uncertain,
                )
            )
    scored.sort(key=lambda match: (match.same_dob, match.name_overlap), reverse=True)
    return scored[:SEARCH_LIMIT]


def channel_state(poll: Poll, entry: RollEntry) -> str:
    """The elector's voting-channel indicator (R-9.1): ``none``, ``online`` or
    ``paper``. Read-only — creating the registration is ``enter_paper``'s job,
    inside its transaction."""
    registration = (
        Registration.objects.filter(poll=poll, roll_entry=entry)
        .exclude(state=RegistrationState.REJECTED)
        .first()
    )
    return registration.channel if registration is not None else Channel.NONE


def in_force_paper_ballot(poll: Poll, entry: RollEntry) -> Ballot | None:
    """The elector's live or pending paper ballot, if any — screen 5 hands off
    to screen 6 when one exists, rather than keying a second."""
    link = (
        PaperBallotLink.objects.filter(poll=poll, roll_entry=entry, ballot__status__in=_IN_FORCE)
        .select_related("ballot")
        .first()
    )
    return link.ballot if link is not None else None
