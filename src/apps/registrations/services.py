# SPDX-License-Identifier: 0BSD
"""Registration flow (§6.2).

Never imports ``apps.ballots`` (INV-1). Voting status is written here, on
``Registration.channel``, in the same transaction as the ballot insert — the
ballot service calls ``mark_voted`` below and passes no voter identity back.

The token is the whole of §7 and is handled in one place. It is minted on entry
to ``pending_email``, from either path, and immediately forgotten: only
``voter_hash`` is stored, and the confirmation mail is the sole place the
plaintext is written out. Losing it is unrecoverable by anyone, administrators
included (R-7.6).

Two refusals share one message and one silence. A roll entry already registered
(case 6) and an address already used (case 3) both answer with
``NEUTRAL_REFUSAL`` and disclose nothing about the registration that caused
them (T-2, T-17): the person at the keyboard may not be the person already
registered, and telling them apart is what an enumeration oracle is.

There is no national identifier any more (R-4.8). A match is a normalised name
tried against the roll's birth surname and its name in use, plus the date of
birth, which carries most of the discriminating power (R-5.3). An entry flagged
``date_uncertain`` (R-4.9) never matches here. A single match whose list types
fall outside ``poll.eligible_list_types`` (R-4.7) is refused as ineligible, not
sent to review; no match, several matches, or a match only against an uncertain
date go to ``pending_review``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.audit.models import Action, Reason
from apps.core.crypto import new_token, voter_hash
from apps.core.models import User
from apps.core.names import canonical_email, names_match, parse_dob
from apps.core.types import Token, TokenSalt
from apps.elections.models import Poll, RollEntry
from apps.elections.windows import check_registration_window

from .models import Channel, DuplicateAttempt, Registration, RegistrationState


class RegistrationRefused(Exception):
    """Shown to the visitor as a neutral message.

    Cases 3 and 6 of §6.2 — address already used, roll entry already registered
    — get the *same* message and disclose no detail of the existing
    registration (T-2, T-17).
    """


def NEUTRAL_REFUSAL() -> str:
    """The one message both duplicate cases answer with (§6.2 steps 3 and 6).

    A function rather than a constant so it translates per request (§3.8), and
    deliberately says nothing an attacker could use to decide *which* of the two
    fields collided — or whether anything collided at all.
    """
    return _(
        "Nous ne pouvons pas enregistrer cette demande en ligne. "
        "Veuillez vous adresser à la mairie."
    )


def match_roll_entries(
    poll: Poll, declared_last: str, declared_first: str, declared_dob: str
) -> list[RollEntry]:
    """Step 2 (R-5.3): snapshot entries consistent with the declaration.

    The date of birth carries the discriminating power, so the query is pinned
    to it and the name comparison — done in Python, against both the birth
    surname and the name in use — stays lenient. Empty when the declared date
    will not parse or nothing lines up; the caller routes both to review. An
    entry flagged ``date_uncertain`` (R-4.9) is excluded and can only be bound
    by a poll admin.
    """
    parsed = parse_dob(declared_dob)
    if parsed is None:
        return []
    candidates = RollEntry.objects.filter(
        poll=poll, date_uncertain=False, date_of_birth_parsed=parsed
    )
    return [
        entry
        for entry in candidates
        if names_match(
            declared_last, declared_first, entry.birth_name, entry.usual_name, entry.first_names
        )
    ]


@dataclass(frozen=True)
class _Outcome:
    """Step 4's decision (R-5.4): the state to create the registration in, the
    single matched entry where there was one, and the code to log on a refusal
    for an ineligible list type."""

    state: str
    matched_entry: RollEntry | None = None
    reject_reason: Reason | None = None

    @property
    def bound_entry(self) -> RollEntry | None:
        """The entry written onto ``Registration.roll_entry``: only where the
        match is single and eligible (§3.3 — null for review and rejected)."""
        return self.matched_entry if self.state == RegistrationState.PENDING_EMAIL else None


def _resolve(poll: Poll, last_name: str, first_names: str, dob: str) -> _Outcome:
    """Step 4's routing (R-5.4, R-4.7).

    - exactly one match, list types eligible for this poll → ``pending_email``,
      bound to that entry;
    - exactly one match, list types conferring no eligibility here → ``rejected``
      with a reason, the person told they are not eligible (T-61);
    - no match, several matches, or a match only against a ``date_uncertain``
      entry → ``pending_review`` (T-28, T-62).

    A false negative costs a human review; a false positive lets someone vote as
    somebody else, which is why ``names_match`` is the strict side of the trade.
    """
    matches = match_roll_entries(poll, last_name, first_names, dob)
    if len(matches) != 1:
        return _Outcome(RegistrationState.PENDING_REVIEW)
    entry = matches[0]
    if not (set(entry.list_types) & set(poll.eligible_list_types)):
        return _Outcome(RegistrationState.REJECTED, entry, Reason.INELIGIBLE_LIST_TYPE)
    return _Outcome(RegistrationState.PENDING_EMAIL, entry)


def issue_token(registration: Registration) -> Token:
    """Mint a token for a registration entering ``pending_email`` (§7).

    Returns the plaintext to its single legitimate consumer, the confirmation
    mail. Only ``voter_hash`` is written; the token itself is never persisted,
    and ``Token`` redacts itself in every ``repr``, ``str`` and ``format`` so an
    accidental log line cannot leak it (§5.1).
    """
    token = new_token()
    registration.voter_hash = voter_hash(TokenSalt(bytes(registration.poll.token_salt)), token)
    registration.save(update_fields=["voter_hash"])
    return token


@transaction.atomic
def _create(
    poll: Poll, fields: dict[str, Any], outcome: _Outcome, language: str
) -> tuple[Registration, Token | None]:
    """The write half of ``register``, and the only part that is a transaction.

    The token is minted inside it, so a registration can never exist without the
    ``voter_hash`` that lets its owner reach it.
    """
    registration = Registration.objects.create(
        poll=poll,
        state=outcome.state,
        language=language,
        roll_entry=outcome.bound_entry,
        **fields,
    )
    token = issue_token(registration) if outcome.state == RegistrationState.PENDING_EMAIL else None
    return registration, token


def register(
    poll: Poll, form_data: dict[str, str], language: str
) -> tuple[Registration, Token | None]:
    """Steps 1–7: match, canonicalise, route, issue the token.

    Returns the registration and, where one was minted, the plaintext token for
    the caller to mail — this function does not send it, so that the send
    happens after the transaction commits and a rolled-back registration cannot
    produce a delivered email.

    A ``pending_review`` registration gets no token: the mailbox is confirmed in
    every path (step 5), and a token is what confirms it, so it is minted when a
    poll admin approves.

    Note what is *not* wrapped in the transaction. The duplicate flag of R-5.9 is
    written after the refusal, outside any transaction the refusal would roll
    back — an audit event written inside one that then raises vanishes with it,
    which is why ``open_poll`` logs its refusals the same way (§10).
    """
    check_registration_window(poll)

    fields: dict[str, Any] = {
        "declared_last_name": form_data["last_name"].strip(),
        "declared_first_names": form_data["first_names"].strip(),
        "declared_dob": form_data.get("date_of_birth", "").strip(),
        "email": form_data["email"].strip(),
        "email_canonical": canonical_email(form_data["email"]),
        "declared_on_honour": bool(form_data.get("declared_on_honour")),
    }

    outcome = _resolve(
        poll, fields["declared_last_name"], fields["declared_first_names"], fields["declared_dob"]
    )
    duplicate_of = _existing_for_roll_entry(poll, outcome.bound_entry)
    address_taken = Registration.objects.filter(
        poll=poll, email_canonical=fields["email_canonical"]
    ).exists()

    if duplicate_of is None and not address_taken:
        try:
            registration, token = _create(poll, fields, outcome, language)
        except IntegrityError:
            # Lost a race with a concurrent submission. The partial unique on
            # (poll, roll_entry) and the address constraint are what actually
            # decide the winner, not the checks above; re-read to see which bit.
            duplicate_of = _existing_for_roll_entry(poll, outcome.bound_entry)
        else:
            if outcome.state == RegistrationState.REJECTED and outcome.matched_entry is not None:
                _log_ineligible(registration, outcome.matched_entry)
            return registration, token

    if duplicate_of is not None:
        _flag_duplicate(poll, duplicate_of)
    raise RegistrationRefused(NEUTRAL_REFUSAL())


def _existing_for_roll_entry(poll: Poll, entry: RollEntry | None) -> Registration | None:
    """Case 6 (R-5.9): does this roll entry already carry a live registration?

    Rejected registrations do not count — the entry is free again — which is why
    the partial unique constraint excludes them too.
    """
    if entry is None:
        return None
    return (
        Registration.objects.filter(poll=poll, roll_entry=entry)
        .exclude(state=RegistrationState.REJECTED)
        .first()
    )


def _flag_duplicate(poll: Poll, existing: Registration) -> None:
    """R-5.9: log the attempt and flag it to the poll admin. The event
    references the *existing* registration and records nothing about the
    attempter (§10)."""
    DuplicateAttempt.objects.create(poll=poll, existing_registration=existing)
    audit.record(
        action=Action.REGISTRATION_DUPLICATE,
        poll=poll,
        object_ref=audit.ref(existing),
        actor_label="public",
    )


def _log_ineligible(registration: Registration, entry: RollEntry) -> None:
    """T-61, §10: a registration refused for an ineligible list type is logged,
    referencing the new (rejected) row. The list types are non-identifying
    state; nothing about the person is recorded."""
    audit.record(
        action=Action.REGISTRATION_INELIGIBLE,
        poll=registration.poll,
        object_ref=audit.ref(registration),
        after={"list_types": list(entry.list_types)},
        actor_label="public",
        reason=Reason.INELIGIBLE_LIST_TYPE,
    )


@transaction.atomic
def approve(
    registration: Registration,
    roll_entry: RollEntry | None,
    reason: Reason | str,
    actor: User | None = None,
    note: str = "",
) -> tuple[Registration, Token]:
    """Step 5: ``pending_review → pending_email``, never straight to ``active``.

    The admin picks the roll entry (R-5.4); ``roll_entry_id`` is bound here and
    nowhere else on the review path. The mailbox is still confirmed in every
    path. §6.2 step 5 logs a reason on both decisions, not only refusals, so
    ``reason`` is mandatory here too: an approval recorded without one leaves the
    log saying that somebody was let in and not why.

    Step 6 (R-5.9): an admin-picked entry that already carries a live
    registration is refused, exactly as an automatic match against it would be.

    ``note`` is prose and is stored on this row, where the retention purge takes
    it — never on the audit event, whose ``reason`` is a code (§10).
    """
    check_registration_window(registration.poll)
    if registration.state != RegistrationState.PENDING_REVIEW:
        raise RegistrationRefused(_("Cette inscription n'est pas en attente d'examen."))
    if not reason:
        raise RegistrationRefused(_("Un motif est obligatoire."))
    if roll_entry is None:
        raise RegistrationRefused(_("Choisissez l'entrée de la liste électorale à rattacher."))
    existing = _existing_for_roll_entry(registration.poll, roll_entry)
    if existing is not None and existing.pk != registration.pk:
        # The admin sees this directly; no DuplicateAttempt flag, which is the
        # public path's way of surfacing R-5.9 to the very person now deciding.
        raise RegistrationRefused(
            _("Cette entrée de la liste électorale est déjà rattachée à une inscription.")
        )

    before = registration.state
    registration.state = RegistrationState.PENDING_EMAIL
    registration.roll_entry = roll_entry
    registration.review_reason = note
    registration.save(update_fields=["state", "roll_entry", "review_reason"])
    token = issue_token(registration)

    audit.record(
        action=Action.REGISTRATION_REVIEWED,
        poll=registration.poll,
        actor=actor,
        object_ref=audit.ref(registration),
        before={"state": before},
        after={"state": registration.state},
        reason=reason,
    )
    return registration, token


@transaction.atomic
def reject(
    registration: Registration, reason: Reason | str, actor: User | None = None, note: str = ""
) -> Registration:
    """Step 5's other half: rejection, with a mandatory reason, logged.

    The reason is a **code**; any prose the operator writes goes to
    ``review_reason`` on this row, because free text authored about an elector
    will contain their name sooner or later and ``reason`` is retained (§10).
    """
    check_registration_window(registration.poll)
    if registration.state != RegistrationState.PENDING_REVIEW:
        raise RegistrationRefused(_("Cette inscription n'est pas en attente d'examen."))
    if not reason:
        raise RegistrationRefused(_("Un motif est obligatoire."))

    before = registration.state
    registration.state = RegistrationState.REJECTED
    registration.review_reason = note
    registration.save(update_fields=["state", "review_reason"])

    audit.record(
        action=Action.REGISTRATION_REVIEWED,
        poll=registration.poll,
        actor=actor,
        object_ref=audit.ref(registration),
        before={"state": before},
        after={"state": registration.state},
        reason=reason,
    )
    return registration


def find_by_token(poll: Poll, token: Token) -> Registration | None:
    """The one lookup a token permits (§7): ``voter_hash`` → registration.

    No other direction exists. Nothing here or anywhere else maps a token to a
    ballot; that is ``ballot_hash``, on a different row, computed with a
    different domain prefix, and the two are separate ``NewType``s precisely so
    that confusing them is a type error (§5.1).
    """
    if not token:
        return None
    digest = voter_hash(TokenSalt(bytes(poll.token_salt)), token)
    return Registration.objects.filter(poll=poll, voter_hash=digest).first()


@transaction.atomic
def confirm_mailbox(registration: Registration) -> Registration:
    """``pending_email → active``: the mailbox is proven (§6.2 step 5).

    Presenting the token proves control of the address it was sent to, which is
    the whole of the confirmation. Idempotent: a voter who follows the link
    twice, or bookmarks it, is already ``active`` and that is not an error.

    A registration left in ``pending_email`` cannot vote and is excluded from
    turnout (R-5.5, T-27) — which is enforced by this function never having run
    for it, not by a check elsewhere.
    """
    check_registration_window(registration.poll)
    if registration.state == RegistrationState.ACTIVE:
        return registration
    if registration.state != RegistrationState.PENDING_EMAIL:
        raise RegistrationRefused(_("Cette inscription ne peut pas être confirmée."))

    registration.state = RegistrationState.ACTIVE
    registration.confirmed_at = timezone.now()
    registration.save(update_fields=["state", "confirmed_at"])
    return registration


@transaction.atomic
def mark_voted(registration_id: str, channel: Channel) -> None:
    """Set ``channel`` in the same transaction as the ballot insert (INV-5, §7).

    This is how "has this person voted" is answered, always. Counting ballots
    to answer it is not available and must not be made available.

    Takes an **id** rather than a registration, and returns nothing: the ballot
    service is the caller, and giving it a ``Registration`` to hold would put a
    voter and a ballot in one scope, which is where a join gets written.
    """
    Registration.objects.filter(pk=registration_id).update(channel=channel)
