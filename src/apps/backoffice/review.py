# SPDX-License-Identifier: 0BSD
"""The read model behind screen 4, file d'attente des inscriptions (§6.5.4).

Screen 4 shows a name beside a roll entry, which is the point: an agent decides
whether the person who filled in the form is the person on the roll (R-5.4).
That is identity beside identity, and never identity beside ballot content —
the one screen permitted to show the latter is screen 5 (§6.5).

``near_matches`` is why the screen is usable. The applicant reached
``pending_review`` because the exact NNE match failed, so showing them nothing
would leave the agent to search the roll by hand; showing them the entries that
nearly match turns the decision into a comparison.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.audit.models import Reason
from apps.core.names import name_tokens, normalise_nne
from apps.elections.models import Poll, RollEntry
from apps.registrations.models import Registration, RegistrationState

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
    Reason.NNE_ABSENT_FROM_ROLL,
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
    same_nne: bool
    same_last_name: bool
    shared_first_names: int


def pending(poll: Poll) -> list[Registration]:
    """The queue itself: oldest first, because the wait is the applicant's."""
    return list(
        Registration.objects.filter(poll=poll, state=RegistrationState.PENDING_REVIEW).order_by(
            "created_at"
        )
    )


def near_matches(registration: Registration) -> list[NearMatch]:
    """Roll entries worth comparing against this applicant (R-8.3's idea, here
    serving R-5.4).

    Three ways in, in descending order of confidence: the NNE matches exactly
    (so the *name* is what diverged), the last name matches after
    normalisation, or a first name is shared. Ranked, not filtered — an agent
    who sees nothing cannot tell "no candidate" from "the search was too
    narrow".
    """
    poll = registration.poll
    nne = normalise_nne(registration.nne)
    declared_last = name_tokens(registration.last_name)
    declared_first = name_tokens(registration.first_names)

    candidates: dict[str, RollEntry] = {}
    if nne:
        for entry in RollEntry.objects.filter(poll=poll, nne=nne):
            candidates[str(entry.pk)] = entry
    # Last-name candidates are narrowed in the database by first letter, then
    # compared properly in Python: normalisation strips diacritics, particles
    # and hyphens, none of which SQL can do (§6.2 step 2).
    if registration.last_name:
        for entry in RollEntry.objects.filter(
            poll=poll, last_name__istartswith=registration.last_name[:1]
        )[:200]:
            candidates.setdefault(str(entry.pk), entry)

    scored = []
    for entry in candidates.values():
        entry_last = name_tokens(entry.last_name)
        entry_first = name_tokens(entry.first_names)
        match = NearMatch(
            entry=entry,
            same_nne=bool(nne) and entry.nne == nne,
            same_last_name=entry_last == declared_last,
            shared_first_names=len(declared_first & entry_first),
        )
        if match.same_nne or match.same_last_name or match.shared_first_names:
            scored.append(match)

    scored.sort(
        key=lambda m: (m.same_nne, m.same_last_name, m.shared_first_names),
        reverse=True,
    )
    return scored[:NEAR_MATCH_LIMIT]
