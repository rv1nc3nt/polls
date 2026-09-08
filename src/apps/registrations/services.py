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

Two refusals share one message and one silence. An NNE already registered
(case 6) and an address already used (case 3) both answer with
``NEUTRAL_REFUSAL`` and disclose nothing about the registration that caused
them (T-2, T-17): the person at the keyboard may not be the person already
registered, and telling them apart is what an enumeration oracle is.
"""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.audit.models import Action, Reason
from apps.core.crypto import new_token, voter_hash
from apps.core.models import User
from apps.core.names import canonical_email, is_valid_nne, names_match, normalise_nne
from apps.core.types import Token, TokenSalt
from apps.elections.models import Poll, RollEntry
from apps.elections.windows import check_registration_window

from .models import Channel, DuplicateAttempt, Registration, RegistrationState


class RegistrationRefused(Exception):
    """Shown to the visitor as a neutral message.

    Cases 3 and 6 of §6.2 — address already used, NNE already registered — get
    the *same* message and disclose no detail of the existing registration
    (T-2, T-17).
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


def find_roll_entry(poll: Poll, nne: str) -> RollEntry | None:
    """Step 2: match on NNE against the frozen snapshot (R-5.3)."""
    return RollEntry.objects.filter(poll=poll, nne=nne).first()


def _resolve_state(poll: Poll, nne: str, last_name: str, first_names: str) -> str:
    """Step 4's routing (R-5.4).

    NNE found and name consistent → ``pending_email``. Everything else —
    divergent name, malformed NNE, blank NNE, NNE absent from the roll — goes to
    ``pending_review`` rather than being refused (T-28). A false negative here
    costs a human review; a false positive lets someone vote as somebody else,
    which is why ``names_match`` is deliberately the strict side of the trade.
    """
    if not nne or not is_valid_nne(nne):
        return RegistrationState.PENDING_REVIEW
    entry = find_roll_entry(poll, nne)
    if entry is None:
        return RegistrationState.PENDING_REVIEW
    if names_match(last_name, first_names, entry.last_name, entry.first_names):
        return RegistrationState.PENDING_EMAIL
    return RegistrationState.PENDING_REVIEW


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
    poll: Poll, fields: dict[str, Any], state: str, language: str
) -> tuple[Registration, Token | None]:
    """The write half of ``register``, and the only part that is a transaction.

    The token is minted inside it, so a registration can never exist without the
    ``voter_hash`` that lets its owner reach it.
    """
    registration = Registration.objects.create(poll=poll, state=state, language=language, **fields)
    token = issue_token(registration) if state == RegistrationState.PENDING_EMAIL else None
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

    nne = normalise_nne(form_data.get("nne", ""))
    fields: dict[str, Any] = {
        "nne": nne,
        "last_name": form_data["last_name"].strip(),
        "first_names": form_data["first_names"].strip(),
        "email": form_data["email"].strip(),
        "email_canonical": canonical_email(form_data["email"]),
        "declared_on_honour": bool(form_data.get("declared_on_honour")),
    }

    duplicate_of = _existing_for_nne(poll, nne)
    address_taken = Registration.objects.filter(
        poll=poll, email_canonical=fields["email_canonical"]
    ).exists()

    if duplicate_of is None and not address_taken:
        state = _resolve_state(poll, nne, fields["last_name"], fields["first_names"])
        try:
            return _create(poll, fields, state, language)
        except IntegrityError:
            # Lost a race with a concurrent submission. INV-4 and INV-10 are
            # database constraints precisely so that the winner is decided here
            # and not by the check above; re-read to see which one bit.
            duplicate_of = _existing_for_nne(poll, nne)

    if duplicate_of is not None:
        _flag_duplicate(poll, duplicate_of)
    raise RegistrationRefused(NEUTRAL_REFUSAL())


def _existing_for_nne(poll: Poll, nne: str) -> Registration | None:
    """Case 6 (R-5.9): is this NNE already registered for this poll?"""
    if not nne:
        return None
    return Registration.objects.filter(poll=poll, nne=nne).first()


def _flag_duplicate(poll: Poll, existing: Registration) -> None:
    """R-5.9: log the attempt and flag it to the poll admin."""
    DuplicateAttempt.objects.create(poll=poll, existing_registration=existing)
    audit.record(
        action=Action.REGISTRATION_DUPLICATE_NNE,
        poll=poll,
        object_ref=audit.ref(existing),
        actor_label="public",
    )


@transaction.atomic
def approve(
    registration: Registration,
    reason: Reason | str,
    actor: User | None = None,
    note: str = "",
) -> tuple[Registration, Token]:
    """Step 5: ``pending_review → pending_email``, never straight to ``active``.

    The mailbox is confirmed in every path. §6.2 step 5 logs a reason on both
    decisions, not only refusals, so ``reason`` is mandatory here too: an
    approval recorded without one leaves the log saying that somebody was let in
    and not why, which is the half of the record that matters later.

    ``note`` is prose and is stored on this row, where the retention purge takes
    it — never on the audit event, whose ``reason`` is a code (§10).
    """
    check_registration_window(registration.poll)
    if registration.state != RegistrationState.PENDING_REVIEW:
        raise RegistrationRefused(_("Cette inscription n'est pas en attente d'examen."))
    if not reason:
        raise RegistrationRefused(_("Un motif est obligatoire."))

    before = registration.state
    registration.state = RegistrationState.PENDING_EMAIL
    registration.review_reason = note
    registration.save(update_fields=["state", "review_reason"])
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
