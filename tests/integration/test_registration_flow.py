# SPDX-License-Identifier: 0BSD
"""Registration (§6.2), end to end.

The properties that matter here are mostly about what does *not* happen: no
tracking code in the confirmation mail, no detail of an existing registration
disclosed to a duplicate, no token in the database, and no route from a
``pending_email`` registration to a ballot.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core import mail as django_mail
from django.utils import timezone

from apps.audit.models import Action, AuditEvent
from apps.core.crypto import voter_hash
from apps.core.types import Token, TokenSalt
from apps.elections.models import Poll
from apps.elections.transitions import open_poll
from apps.elections.windows import WindowClosed
from apps.registrations import services
from apps.registrations.models import (
    Channel,
    DuplicateAttempt,
    Registration,
    RegistrationState,
)

# The fixture snapshot holds Dupont Émile, born 12/05/1970, on the main list.
FORM = {
    "last_name": "Dupont",
    "first_names": "Émile",
    "date_of_birth": "12/05/1970",
    "email": "Emile.Dupont@example.fr",
    "declared_on_honour": "on",
}


@pytest.fixture
def live_poll(open_window_poll: Poll) -> Poll:
    """An open poll whose snapshot holds Dupont Émile, born 12/05/1970."""
    open_poll(open_window_poll)
    return Poll.objects.get(pk=open_window_poll.pk)


def _register(poll: Poll, **overrides: str) -> tuple[Registration, Token | None]:
    return services.register(poll, {**FORM, **overrides}, language="fr")


def _sibling_poll(model: Poll, **config: object) -> Poll:
    """Another open poll, holding the same elector, configured differently.

    Configuration is frozen once a poll leaves ``draft`` (INV-6, R-3.3) and the
    trigger enforces it, so a test that needs a different setting builds a poll
    with it rather than updating one.
    """
    from apps.elections.models import PollOption, RollEntry

    poll = Poll.objects.create(
        title_i18n={"fr": "Second"},
        description_i18n={"fr": "Second"},
        languages=["fr"],
        opens_at=model.opens_at,
        closes_at=model.closes_at,
        paper_entry_deadline=model.paper_entry_deadline,
        **config,
    )
    for position, option_id in enumerate(["a", "b"]):
        PollOption.objects.create(
            poll=poll, option_id=option_id, label_i18n={"fr": option_id}, position=position
        )
    RollEntry.objects.create(
        poll=poll,
        birth_name="Dupont",
        first_names="Émile",
        date_of_birth="12/05/1970",
        date_of_birth_parsed="1970-05-12",
        list_types=["principale"],
    )
    return poll


# --- Step 4's routing (R-5.4, R-4.7) ---------------------------------------


def test_a_consistent_name_and_date_go_straight_to_pending_email(live_poll: Poll) -> None:
    registration, token = _register(live_poll)
    assert registration.state == RegistrationState.PENDING_EMAIL
    assert registration.roll_entry is not None
    assert token is not None


def test_t28_a_divergent_name_is_reviewed_not_refused(live_poll: Poll) -> None:
    """R-5.4: routed to a human. Refusing here would strand anyone whose roll
    entry is spelled differently from their own declaration."""
    registration, token = _register(live_poll, last_name="Dupond")
    assert registration.state == RegistrationState.PENDING_REVIEW
    assert registration.roll_entry is None
    assert token is None, "no token before a human has looked"


def test_a_divergent_or_missing_date_of_birth_is_reviewed(live_poll: Poll) -> None:
    wrong_date, _ = _register(live_poll, date_of_birth="01/01/1900", email="a@example.fr")
    assert wrong_date.state == RegistrationState.PENDING_REVIEW
    no_date, _ = _register(live_poll, date_of_birth="", email="b@example.fr")
    assert no_date.state == RegistrationState.PENDING_REVIEW


def test_diacritics_and_particles_do_not_make_a_divergence(live_poll: Poll) -> None:
    """The roll holds "Émile"; the applicant types "emile" (T-40)."""
    registration, _ = _register(live_poll, first_names="emile")
    assert registration.state == RegistrationState.PENDING_EMAIL


def test_the_name_in_use_is_accepted_in_place_of_the_birth_surname(
    open_window_poll: Poll,
) -> None:
    """R-5.3: the declared surname is tried against both roll surnames."""
    from apps.elections.models import WorkingRollEntry

    WorkingRollEntry.objects.all().delete()
    WorkingRollEntry.objects.create(
        birth_name="Delavigne",
        usual_name="Ravanel",
        first_names="Apolline",
        date_of_birth="14/03/1962",
        date_of_birth_parsed="1962-03-14",
        list_types=["principale"],
    )
    poll = Poll.objects.get(pk=open_window_poll.pk)
    open_poll(poll)

    registration, token = services.register(
        Poll.objects.get(pk=poll.pk),
        {
            "last_name": "Ravanel",
            "first_names": "Apolline",
            "date_of_birth": "14/03/1962",
            "email": "apolline@example.fr",
            "declared_on_honour": "on",
        },
        language="fr",
    )
    assert registration.state == RegistrationState.PENDING_EMAIL
    assert token is not None


def test_t61_a_match_on_an_ineligible_list_type_is_rejected(open_window_poll: Poll) -> None:
    """R-4.7: a single match whose list types confer no eligibility here is
    refused as ineligible, not sent to review, and the attempt is logged."""
    from apps.elections.models import WorkingRollEntry

    WorkingRollEntry.objects.all().delete()
    WorkingRollEntry.objects.create(
        birth_name="Zampieri",
        first_names="Églantine",
        date_of_birth="08/01/1983",
        date_of_birth_parsed="1983-01-08",
        list_types=["complementaire_europeenne"],
    )
    open_poll(open_window_poll)
    poll = Poll.objects.get(pk=open_window_poll.pk)

    registration, token = services.register(
        poll,
        {
            "last_name": "Zampieri",
            "first_names": "Églantine",
            "date_of_birth": "08/01/1983",
            "email": "eglantine@example.fr",
            "declared_on_honour": "on",
        },
        language="fr",
    )
    assert registration.state == RegistrationState.REJECTED
    assert registration.roll_entry is None
    assert token is None
    event = AuditEvent.objects.get(action=Action.REGISTRATION_INELIGIBLE)
    assert event.after["list_types"] == ["complementaire_europeenne"]
    assert "Zampieri" not in str(event.after)


def test_t62_a_match_only_against_a_date_uncertain_entry_is_reviewed(
    open_window_poll: Poll,
) -> None:
    """R-4.9: an entry whose date of birth would not parse never auto-matches."""
    from apps.elections.models import WorkingRollEntry

    WorkingRollEntry.objects.all().delete()
    WorkingRollEntry.objects.create(
        birth_name="Orsatti",
        first_names="Zéphirin",
        date_of_birth="00/00/1953",
        date_of_birth_parsed=None,
        date_uncertain=True,
        list_types=["principale"],
    )
    open_poll(open_window_poll)

    registration, token = services.register(
        Poll.objects.get(pk=open_window_poll.pk),
        {
            "last_name": "Orsatti",
            "first_names": "Zéphirin",
            "date_of_birth": "00/00/1953",
            "email": "zephirin@example.fr",
            "declared_on_honour": "on",
        },
        language="fr",
    )
    assert registration.state == RegistrationState.PENDING_REVIEW
    assert token is None


# --- Steps 3 and 6: the two duplicates (T-2, T-17) ---------------------------


def test_t2_a_registration_against_a_bound_roll_entry_is_refused_logged_and_flagged(
    live_poll: Poll,
) -> None:
    """R-5.9. The event references the *existing* registration and records
    nothing about the attempter (§10)."""
    first, _ = _register(live_poll)
    with pytest.raises(services.RegistrationRefused):
        _register(live_poll, email="autre@example.fr")

    assert DuplicateAttempt.objects.filter(existing_registration=first).count() == 1
    event = AuditEvent.objects.get(action=Action.REGISTRATION_DUPLICATE)
    assert event.object_ref == f"registration:{first.pk}"
    assert event.before == {} and event.after == {}


def test_t17_a_duplicate_address_is_refused_whatever_its_case(live_poll: Poll) -> None:
    _register(live_poll)
    with pytest.raises(services.RegistrationRefused):
        _register(live_poll, last_name="Autre", email="EMILE.DUPONT@EXAMPLE.FR")


def test_both_duplicates_answer_with_the_same_words(live_poll: Poll) -> None:
    """T-2 and T-17: an attacker must not learn which field collided, nor
    anything about the registration that caused the refusal."""
    _register(live_poll)

    with pytest.raises(services.RegistrationRefused) as by_entry:
        _register(live_poll, email="autre@example.fr")
    with pytest.raises(services.RegistrationRefused) as by_email:
        _register(live_poll, last_name="Autre")

    assert str(by_entry.value) == str(by_email.value)
    for message in (str(by_entry.value), str(by_email.value)):
        assert "Dupont" not in message
        assert "example.fr" not in message


# --- Step 7 and §7: the token ------------------------------------------------


def test_the_plaintext_token_is_never_stored(live_poll: Poll) -> None:
    """§7. Only ``voter_hash`` is written; the token exists in the mail and in
    the caller's hand, nowhere else."""
    registration, token = _register(live_poll)
    assert token is not None
    registration.refresh_from_db()

    expected = voter_hash(TokenSalt(bytes(live_poll.token_salt)), token)
    assert registration.voter_hash is not None
    assert bytes(registration.voter_hash) == bytes(expected)

    row = Registration.objects.filter(pk=registration.pk).values().get()
    assert not any(token.reveal() in str(value) for value in row.values())


def test_a_token_redacts_itself_everywhere(live_poll: Poll) -> None:
    _, token = _register(live_poll)
    assert token is not None
    assert token.reveal() not in f"{token} {token!r} {token!s}"


def test_t25_the_confirmation_mail_carries_no_tracking_code(live_poll: Poll) -> None:
    """§6.2 step 7: the code belongs to a ballot, and no ballot exists yet."""
    from apps.registrations import mail as registration_mail

    registration, token = _register(live_poll)
    assert token is not None
    registration_mail.send_confirmation(registration, token)

    body = django_mail.outbox[0].body
    assert token.reveal() in body, "the ballot link must carry the token"
    assert "tracking" not in body.lower()
    assert registration.declared_dob not in body


def test_the_mail_warns_that_losing_it_loses_modification(live_poll: Poll) -> None:
    """R-5.6 and R-7.6, and only where modification is actually enabled: where
    it is off the point is moot and the mail should not raise it (§7)."""
    from apps.registrations import mail as registration_mail

    registration, token = _register(live_poll)
    assert token is not None
    registration_mail.send_confirmation(registration, token)
    assert "modifier" in django_mail.outbox[0].body

    unmodifiable = _sibling_poll(live_poll, allow_ballot_modification=False)
    other, other_token = _register(unmodifiable)
    assert other_token is not None
    registration_mail.send_confirmation(other, other_token)
    assert "modifier" not in django_mail.outbox[1].body


# --- Step 5: review, and the mailbox confirmed in every path -----------------


def test_t18_approval_reaches_pending_email_never_active(live_poll: Poll) -> None:
    from apps.elections.models import RollEntry

    registration, _ = _register(live_poll, last_name="Dupond")
    entry = RollEntry.objects.get(poll=live_poll, birth_name="Dupont")
    approved, token = services.approve(registration, entry, reason="name_divergence_accepted")

    assert approved.state == RegistrationState.PENDING_EMAIL
    assert approved.roll_entry == entry
    assert token is not None
    assert AuditEvent.objects.filter(action=Action.REGISTRATION_REVIEWED).exists()


def test_approval_needs_a_reason_and_an_entry(live_poll: Poll) -> None:
    from apps.elections.models import RollEntry

    registration, _ = _register(live_poll, last_name="Dupond")
    entry = RollEntry.objects.get(poll=live_poll, birth_name="Dupont")
    with pytest.raises(services.RegistrationRefused):
        services.approve(registration, entry, reason="")
    with pytest.raises(services.RegistrationRefused):
        services.approve(registration, None, reason="name_divergence_accepted")


def test_approval_refuses_an_entry_already_bound(live_poll: Poll) -> None:
    """Step 6 (R-5.9): the admin-picked entry already carries a live
    registration."""
    from apps.elections.models import RollEntry

    _register(live_poll)  # binds the Dupont entry
    entry = RollEntry.objects.get(poll=live_poll, birth_name="Dupont")
    other, _ = services.register(
        live_poll,
        {**FORM, "last_name": "Dupond", "email": "other@example.fr"},
        language="fr",
    )
    with pytest.raises(services.RegistrationRefused):
        services.approve(other, entry, reason="name_divergence_accepted")


def test_rejection_needs_a_reason_and_keeps_the_prose_off_the_event(live_poll: Poll) -> None:
    """§10: ``reason`` is a code; the note goes on the row the purge deletes."""
    registration, _ = _register(live_poll, last_name="Dupond")
    with pytest.raises(services.RegistrationRefused):
        services.reject(registration, reason="")

    services.reject(
        registration,
        reason="name_divergence_refused",
        note="Dupond/Dupont, non confirmé au guichet",
    )
    registration.refresh_from_db()
    assert registration.state == RegistrationState.REJECTED
    assert "Dupond" in registration.review_reason

    event = AuditEvent.objects.get(action=Action.REGISTRATION_REVIEWED)
    assert event.reason == "name_divergence_refused"
    assert "Dupond" not in str(event.before) + str(event.after) + event.reason


def test_t27_a_pending_email_registration_is_not_counted_and_not_active(live_poll: Poll) -> None:
    """R-5.5: it cannot reach a ballot and is excluded from turnout."""
    registration, _ = _register(live_poll)
    assert registration.state == RegistrationState.PENDING_EMAIL

    from apps.elections.closure import frozen_counts

    assert frozen_counts(live_poll)["registered"] == 0


def test_confirming_the_mailbox_activates_once_and_is_idempotent(live_poll: Poll) -> None:
    registration, _ = _register(live_poll)
    confirmed = services.confirm_mailbox(registration)
    assert confirmed.state == RegistrationState.ACTIVE
    assert confirmed.confirmed_at is not None

    stamp = confirmed.confirmed_at
    again = services.confirm_mailbox(confirmed)
    assert again.confirmed_at == stamp, "a second visit must not restamp"


def test_a_token_resolves_to_its_registration_and_nothing_else(live_poll: Poll) -> None:
    registration, token = _register(live_poll)
    assert token is not None
    assert services.find_by_token(live_poll, token) == registration
    assert services.find_by_token(live_poll, Token("WRONG")) is None


def test_t12_the_same_elector_in_two_polls_gets_unrelated_tokens(
    live_poll: Poll, open_window_poll: Poll
) -> None:
    """§7: ``token_salt`` is per poll, so participation cannot be correlated
    across polls by the application (R-13.4)."""
    other = _sibling_poll(live_poll)

    first, token_a = _register(live_poll)
    second, token_b = _register(other)
    assert token_a is not None and token_b is not None
    assert token_a.reveal() != token_b.reveal()
    assert first.voter_hash is not None and second.voter_hash is not None
    assert bytes(first.voter_hash) != bytes(second.voter_hash)
    assert services.find_by_token(other, token_a) is None


# --- INV-2: the registration window ------------------------------------------


def test_registration_is_refused_after_closure(live_poll: Poll) -> None:
    past = timezone.now() - timedelta(minutes=1)
    Poll.objects.filter(pk=live_poll.pk).update(closes_at=past, paper_entry_deadline=past)
    with pytest.raises(WindowClosed):
        _register(Poll.objects.get(pk=live_poll.pk))


def test_registration_is_refused_before_opening(db: None) -> None:
    now = timezone.now()
    future = Poll.objects.create(
        title_i18n={"fr": "À venir"},
        description_i18n={"fr": "À venir"},
        languages=["fr"],
        opens_at=now + timedelta(days=1),
        closes_at=now + timedelta(days=2),
        paper_entry_deadline=now + timedelta(days=2),
    )
    with pytest.raises(WindowClosed):
        _register(future)


def test_marking_voted_writes_the_channel_and_returns_nothing(live_poll: Poll) -> None:
    """INV-5: this is how "has this person voted" is answered, always."""
    registration, _ = _register(live_poll)
    services.confirm_mailbox(registration)
    assert services.mark_voted(str(registration.pk), Channel.ONLINE) is None

    registration.refresh_from_db()
    assert registration.channel == Channel.ONLINE
    assert registration.has_voted
