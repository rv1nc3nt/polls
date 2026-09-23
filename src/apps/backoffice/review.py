# SPDX-License-Identifier: 0BSD
"""The read model behind screen 4, file d'attente des inscriptions (§6.5.4).

Screen 4 shows a declaration beside roll entries, which is the point: an agent
decides whether the person who filled in the form is the person on the roll, and
picks the entry to bind (R-5.4). That is identity beside identity, and never
identity beside ballot content — the one screen permitted to show the latter is
screen 5 (§6.5).

``near_matches`` is why the screen is usable. The applicant reached
``pending_review`` because no single automatic match was found, so showing them
nothing would leave the agent to search the roll by hand; showing them the
entries that nearly match — by date of birth, by either surname, by a shared
forename — turns the decision into a comparison.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from apps.audit.models import Reason
from apps.core.names import name_tokens, parse_dob, surname_matches
from apps.elections.models import Poll, RollEntry
from apps.registrations.models import Channel, Registration, RegistrationState

#: The reason codes that mean something on *this* screen (§10). The full
#: vocabulary spans the paper-ballot screens too, and offering an agent
#: "bulletin en double" when they are deciding a registration is how a reason
#: code becomes noise: the value logged has to be the one that was true.
APPROVAL_REASONS = (
    Reason.NAME_DIVERGENCE_ACCEPTED,
    Reason.IDENTITY_CONFIRMED_AT_MAIRIE,
    Reason.ADMINISTRATIVE_DECISION,
    Reason.OTHER,
)
REFUSAL_REASONS = (
    Reason.NAME_DIVERGENCE_REFUSED,
    Reason.NO_ROLL_MATCH,
    Reason.INELIGIBLE_LIST_TYPE,
    Reason.ADMINISTRATIVE_DECISION,
    Reason.OTHER,
)


def choices(reasons: tuple[Reason, ...]) -> list[tuple[str, str]]:
    """``(value, label)`` pairs for a template, labels translated per request."""
    return [(str(reason), str(reason.label)) for reason in reasons]


#: How many roll entries to offer per pending registration. Enough to cover a
#: misspelling and a household, few enough that the agent reads them all.
NEAR_MATCH_LIMIT = 5


@dataclass(frozen=True)
class NearMatch:
    """A roll entry the agent should look at, and why it surfaced."""

    entry: RollEntry
    same_dob: bool
    same_surname: bool
    shared_first_names: int
    date_uncertain: bool


def pending(poll: Poll) -> list[Registration]:
    """The queue itself: oldest first, because the wait is the applicant's."""
    return list(
        Registration.objects.filter(poll=poll, state=RegistrationState.PENDING_REVIEW).order_by(
            "created_at"
        )
    )


def awaiting_confirmation(poll: Poll) -> list[Registration]:
    """Electors matched but not yet confirmed (R-5.5), oldest first: the ones an
    agent can chase — most often a confirmation mail that never arrived. Not one
    keyed on paper meanwhile: they have voted, and there is nothing to chase
    (``docs/specification-decision-log.md`` #29)."""
    return list(
        Registration.objects.filter(
            poll=poll, state=RegistrationState.PENDING_EMAIL, channel=Channel.NONE
        ).order_by("created_at")
    )


def poll_roll(poll: Poll) -> list[RollEntry]:
    """This poll's whole roll, fetched once for the queue screen (§6.5.4).

    One commune's roll, not the country's: cheaper as the single query a
    caller iterating every pending registration makes once than as up to
    three narrowing queries ``near_matches`` would otherwise repeat per row.
    """
    return list(RollEntry.objects.filter(poll=poll))


def near_matches(
    registration: Registration, roll: Iterable[RollEntry] | None = None
) -> list[NearMatch]:
    """Roll entries worth comparing against this applicant (R-8.3's idea, here
    serving R-5.4).

    Three ways in, in descending order of confidence: the parsed date of birth
    matches, either surname matches after normalisation, or a forename is
    shared. Ranked, not filtered — an agent who sees nothing cannot tell "no
    candidate" from "the search was too narrow".

    ``roll`` is this poll's entries, queried once by ``poll_roll`` and shared
    across every registration on the queue screen; a caller scoring a single
    registration on its own may leave it out.
    """
    if roll is None:
        roll = RollEntry.objects.filter(poll=registration.poll)
    declared_dob = parse_dob(registration.declared_dob)
    declared_surname = name_tokens(registration.declared_last_name)
    declared_first = name_tokens(registration.declared_first_names)

    scored = []
    for entry in roll:
        entry_first = name_tokens(entry.first_names)
        match = NearMatch(
            entry=entry,
            same_dob=declared_dob is not None
            and not entry.date_uncertain
            and entry.date_of_birth_parsed == declared_dob,
            same_surname=bool(declared_surname)
            and surname_matches(
                registration.declared_last_name, entry.birth_name, entry.usual_name
            ),
            shared_first_names=len(declared_first & entry_first),
            date_uncertain=entry.date_uncertain,
        )
        if match.same_dob or match.same_surname or match.shared_first_names:
            scored.append(match)

    scored.sort(
        key=lambda m: (m.same_dob, m.same_surname, m.shared_first_names),
        reverse=True,
    )
    return scored[:NEAR_MATCH_LIMIT]
