# SPDX-License-Identifier: 0BSD
"""The retention purge against live triggers (§11, R-13.3): T-14, T-54, T-55.

Two months after closure the identity data is deleted and nothing else is. The
rest of the suite simulates that step with ``Registration.objects.delete()``;
here the real ``elections.retention.purge`` and the ``retention_purge`` command
run, so the INV-2 and INV-7 delete carve-outs of §11 — ``closed`` *or*
``published``, expressed inside the trigger rather than by disabling it — are
what the deletion actually passes through.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta

import pytest
from django.core.management import call_command
from django.db import connection, transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.audit.models import Action, AuditEvent, Reason
from apps.backoffice.auditlog import resolve_refs
from apps.ballots import services as ballots
from apps.ballots.models import Ballot
from apps.core.models import User
from apps.elections.models import (
    Poll,
    PollOption,
    PollState,
    RollEntry,
    WorkingRollEntry,
)
from apps.elections.retention import RETENTION, due_polls, purge
from apps.elections.transitions import close_poll, open_poll, publish_poll
from apps.registrations import services as registrations
from apps.registrations.models import (
    DuplicateAttempt,
    Registration,
    RegistrationState,
)

# --- fixtures for the scan of T-55 --------------------------------------------

# Every fragment of the electors' identities that must not survive the purge on
# a row, and must never reach an audit event at all: birth names, the divergent
# spelling an operator typed, first names, the local part of each address, and
# both renderings of every date of birth.
_IDENTITY_LITERALS = (
    "Dupont",
    "Émile",
    "emile.dupont",
    "Marchand",
    "Marchaud",
    "Camille",
    "camille.marchand",
    "Nguyen",
    "Thi Lan",
    "thi.nguyen",
    "Zampieri",
    "Églantine",
    "eglantine.zampieri",
    "1970-05-12",
    "1985-07-03",
    "1990-11-21",
    "1983-01-08",
    "example.fr",
)
# A slash-delimited date and an address never occur in a reference, a hash, a
# state name or a ranking, so a hit is a genuine leak rather than a collision.
_DATE = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _scan_for_identity(events: QuerySet[AuditEvent]) -> None:
    """§10, T-55: no ``object_ref``, ``before``, ``after`` or ``reason`` carries
    a name, a date of birth or an email — before or after the purge."""
    for event in events:
        haystack = " ".join(
            [
                event.object_ref,
                json.dumps(event.before, ensure_ascii=False),
                json.dumps(event.after, ensure_ascii=False),
                str(event.reason),
            ]
        )
        for needle in _IDENTITY_LITERALS:
            assert needle not in haystack, (
                f"{event.action}: {needle!r} in {haystack!r} — identity data belongs "
                "on the referenced row, never on the event (§10, T-55)"
            )
        assert not _DATE.search(haystack), f"{event.action}: a date of birth in {haystack!r}"
        assert not _EMAIL.search(haystack), f"{event.action}: an email in {haystack!r}"


# --- builders ---------------------------------------------------------------


def _poll(title: str) -> Poll:
    now = timezone.now()
    poll = Poll.objects.create(
        title_i18n={"fr": title},
        description_i18n={"fr": title},
        languages=["fr"],
        # Well before the retention term: ``opens_at`` is frozen once the poll
        # leaves draft (INV-6), so ``_age_past_retention`` can only move the
        # closing instants back, and they must stay after this one.
        opens_at=now - timedelta(days=120),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
    )
    for position, option_id in enumerate(("a", "b", "c")):
        PollOption.objects.create(
            poll=poll,
            option_id=option_id,
            label_i18n={"fr": option_id.upper()},
            position=position,
        )
    return poll


def _roll_entry(
    birth_name: str,
    first_names: str,
    dob_raw: str,
    dob_iso: str,
    list_type: str = "principale",
) -> WorkingRollEntry:
    return WorkingRollEntry.objects.create(
        birth_name=birth_name,
        first_names=first_names,
        date_of_birth=dob_raw,
        date_of_birth_parsed=dob_iso,
        list_types=[list_type],
    )


def _form(last_name: str, first_names: str, dob_raw: str, email: str) -> dict[str, str]:
    return {
        "last_name": last_name,
        "first_names": first_names,
        "date_of_birth": dob_raw,
        "email": email,
        "declared_on_honour": "on",
    }


def _age_past_retention(poll: Poll) -> None:
    """Push closure and the voting window back beyond the retention term.

    ``closed_at`` is what ``due_polls`` selects on; ``closes_at`` and
    ``paper_entry_deadline`` are what the INV-2 window triggers read. None of the
    three is frozen configuration (INV-6), so a bare ``update`` moves them
    without the reasoned extension of R-3.4 — ``opens_at`` is frozen and stays
    where ``_poll`` put it, well before this instant.
    """
    past = timezone.now() - RETENTION - timedelta(days=1)
    Poll.objects.filter(pk=poll.pk).update(
        closed_at=past, closes_at=past, paper_entry_deadline=past
    )


def _sql_time(moment: datetime) -> str:
    """The wire format Django writes for an aware datetime on SQLite."""
    return moment.strftime("%Y-%m-%d %H:%M:%S.%f")


def _raw(sql: str, params: list[str]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)


# --- T-14 -----------------------------------------------------------------


def test_t14_purge_keeps_everything_but_identity(db: None) -> None:
    """Retention job run two months after closure: identity data gone; ballots,
    results and the log retained in full; the log's now-dangling references
    resolve as deletions rather than erroring."""
    operator = User.objects.create_user(
        username="op.retention", password="x", full_name="Opérateur"
    )
    poll = _poll("Aménagement de la place")
    _roll_entry("Dupont", "Émile", "12/05/1970", "1970-05-12")
    _roll_entry("Nguyen", "Thi Lan", "21/11/1990", "1990-11-21")
    open_poll(poll)
    poll = Poll.objects.get(pk=poll.pk)
    nguyen = RollEntry.objects.get(poll=poll, birth_name="Nguyen")

    # An online voter and a paper voter — the paper channel is anonymised only
    # when its link and the roll snapshot go (R-8.2 bis, §11).
    online_reg, token = registrations.register(
        poll,
        _form("Dupont", "Émile", "12/05/1970", "emile.dupont@example.fr"),
        language="fr",
    )
    registrations.confirm_mailbox(online_reg)
    assert token is not None
    ballots.cast_online(poll, token, [["a"], ["b"], ["c"]])
    ballots.enter_paper(poll, str(nguyen.pk), [["a"], ["b"], ["c"]], str(operator.pk), "fr")

    # A duplicate attempt against the online voter's entry: a row the purge is
    # meant to take (R-5.9, §10).
    with pytest.raises(registrations.RegistrationRefused):
        registrations.register(
            poll,
            _form("Dupont", "Émile", "12/05/1970", "autre@example.fr"),
            language="fr",
        )

    close_poll(poll)
    poll = Poll.objects.get(pk=poll.pk)
    assert poll.closure_hash is not None
    closure_hash = bytes(poll.closure_hash)
    frozen_counts = dict(poll.frozen_counts)
    ballot_ids = set(Ballot.objects.filter(poll=poll).values_list("pk", flat=True))
    live_ballot_ids = set(Ballot.live.filter(poll=poll).values_list("pk", flat=True))
    event_ids_before = set(AuditEvent.objects.values_list("pk", flat=True))
    assert Registration.objects.filter(poll=poll).count() == 2
    assert DuplicateAttempt.objects.filter(poll=poll).count() == 1
    assert RollEntry.objects.filter(poll=poll).count() == 2

    _age_past_retention(poll)
    assert poll in due_polls()
    call_command("retention_purge")

    # Identity data: gone.
    assert not Registration.objects.filter(poll=poll).exists()
    assert not RollEntry.objects.filter(poll=poll).exists()
    assert not DuplicateAttempt.objects.filter(poll=poll).exists()
    assert not poll.paper_links.exists()

    # Ballots and results: untouched.
    assert set(Ballot.objects.filter(poll=poll).values_list("pk", flat=True)) == ballot_ids
    assert set(Ballot.live.filter(poll=poll).values_list("pk", flat=True)) == live_ballot_ids
    poll.refresh_from_db()
    assert poll.closure_hash is not None
    assert bytes(poll.closure_hash) == closure_hash
    assert dict(poll.frozen_counts) == frozen_counts

    # The log: every prior event still present (INV-3 has no delete path, purge
    # included), plus the purge's own event.
    assert event_ids_before <= set(AuditEvent.objects.values_list("pk", flat=True))
    assert AuditEvent.objects.filter(action=Action.RETENTION_PURGE, poll=poll).count() == 1

    # A reference that now names a deleted row resolves as absent, without
    # raising: that is the audit screen working, not a fault (§10, §11).
    dangling = list(AuditEvent.objects.filter(poll=poll, action=Action.REGISTRATION_DUPLICATE))
    assert dangling
    assert resolve_refs(dangling) == {dangling[0].object_ref: False}

    # Idempotent: a re-run finds nothing left to delete.
    again = purge(poll)
    assert (again.registrations, again.roll_entries) == (0, 0)
    assert (again.paper_links, again.duplicate_attempts) == (0, 0)
    assert event_ids_before <= set(AuditEvent.objects.values_list("pk", flat=True))


# --- T-54 -----------------------------------------------------------------


def test_t54_purge_on_a_published_poll_leaves_inv2_in_force(db: None) -> None:
    """Retention purge run on a published poll; then INSERT and UPDATE attempted
    on ``Registration`` in raw SQL after ``closes_at``. The purge succeeds
    against the live triggers, including the ``RollEntry`` deletion; the insert
    and the update are rejected by the INV-2 trigger."""
    operator = User.objects.create_user(
        username="op.retention", password="x", full_name="Opérateur"
    )

    published = _poll("Scrutin publié")
    _roll_entry("Dupont", "Émile", "12/05/1970", "1970-05-12")
    open_poll(published)
    published = Poll.objects.get(pk=published.pk)
    registrations.register(
        published,
        _form("Dupont", "Émile", "12/05/1970", "emile.dupont@example.fr"),
        language="fr",
    )
    close_poll(published)
    publish_poll(Poll.objects.get(pk=published.pk), operator)
    published = Poll.objects.get(pk=published.pk)
    assert published.state == PollState.PUBLISHED
    assert RollEntry.objects.filter(poll=published).count() == 1

    _age_past_retention(published)
    report = purge(published)
    # The INV-7 delete trigger admits this only because the state is published
    # (or closed); disabling it for the job is not the mechanism (§11).
    assert report.roll_entries == 1
    assert report.registrations == 1
    assert not RollEntry.objects.filter(poll=published).exists()
    assert not Registration.objects.filter(poll=published).exists()

    # A second poll, closed and left populated: its registration — created while
    # the window was open — is the UPDATE target once the window is aged shut.
    closed = _poll("Scrutin clos")
    open_poll(closed)
    survivor, _token = registrations.register(
        closed,
        _form("Dupont", "Émile", "12/05/1970", "emile.dupont@example.fr"),
        language="fr",
    )
    close_poll(closed)
    _age_past_retention(closed)

    now = timezone.now()

    # INSERT into the purged, published poll: refused by the INV-2 insert window,
    # which the purge's DELETE carve-out did not touch.
    with pytest.raises(Exception, match="INV-2"), transaction.atomic():
        _raw(
            "INSERT INTO registrations_registration "
            "(id, poll_id, roll_entry_id, declared_last_name, declared_first_names, "
            "declared_dob, email, email_canonical, declared_on_honour, state, "
            "review_reason, voter_hash, channel, language, created_at, confirmed_at, "
            "reminder_sent_at) "
            "VALUES (%s, %s, NULL, 'X', 'Y', '', 'x@example.fr', 'x@example.fr', 0, "
            "'pending_email', '', NULL, 'none', 'fr', %s, NULL, NULL)",
            [uuid.uuid4().hex, published.pk.hex, _sql_time(now)],
        )

    # UPDATE of a registration past closes_at: refused by the INV-2 update window.
    with pytest.raises(Exception, match="INV-2"), transaction.atomic():
        _raw(
            "UPDATE registrations_registration SET reminder_sent_at = %s WHERE id = %s",
            [_sql_time(now), survivor.pk.hex],
        )
    survivor.refresh_from_db()
    assert survivor.reminder_sent_at is None


# --- T-55 -----------------------------------------------------------------


def test_t55_no_audit_event_carries_identity_before_or_after_the_purge(db: None) -> None:
    """Every audit event written across a full poll lifecycle, scanned before
    and after the purge: no ``object_ref``, ``before``, ``after`` or ``reason``
    matches a name, a date of birth or an email at either point; ``UPDATE`` on
    ``audit_event`` still aborts."""
    operator = User.objects.create_user(
        username="op.retention", password="x", full_name="Opérateur"
    )

    poll = _poll("Consultation citoyenne")
    _roll_entry("Dupont", "Émile", "12/05/1970", "1970-05-12")
    _roll_entry("Marchand", "Camille", "03/07/1985", "1985-07-03")
    _roll_entry("Nguyen", "Thi Lan", "21/11/1990", "1990-11-21")
    _roll_entry(
        "Zampieri", "Églantine", "08/01/1983", "1983-01-08", list_type="complementaire_europeenne"
    )
    open_poll(poll)
    poll = Poll.objects.get(pk=poll.pk)

    # Clean match, mailbox confirmed, votes online.
    clean_reg, token = registrations.register(
        poll,
        _form("Dupont", "Émile", "12/05/1970", "emile.dupont@example.fr"),
        language="fr",
    )
    registrations.confirm_mailbox(clean_reg)
    assert token is not None
    ballots.cast_online(poll, token, [["a"], ["b"], ["c"]])

    # Divergent surname → review → approved onto the Marchand entry, with an
    # operator note that names the person: it must land on the row the purge
    # deletes, never on the event (§10).
    review_reg, _token = registrations.register(
        poll,
        _form("Marchaud", "Camille", "03/07/1985", "camille.marchand@example.fr"),
        language="fr",
    )
    assert review_reg.state == RegistrationState.PENDING_REVIEW
    marchand = RollEntry.objects.get(poll=poll, birth_name="Marchand")
    registrations.approve(
        review_reg,
        marchand,
        reason=Reason.NAME_DIVERGENCE_ACCEPTED,
        actor=operator,
        note="graphie « Marchaud » retenue pour Marchand, née le 03/07/1985",
    )

    # A duplicate attempt against the clean entry: logged, no row (R-5.9).
    with pytest.raises(registrations.RegistrationRefused):
        registrations.register(
            poll,
            _form("Dupont", "Émile", "12/05/1970", "encore@example.fr"),
            language="fr",
        )

    # A single match on an ineligible list type: not refused outright — a
    # rejected row is created and the attempt is logged (R-4.7, T-61).
    ineligible_reg, ineligible_token = registrations.register(
        poll,
        _form("Zampieri", "Églantine", "08/01/1983", "eglantine.zampieri@example.fr"),
        language="fr",
    )
    assert ineligible_reg.state == RegistrationState.REJECTED
    assert ineligible_token is None

    # A paper ballot, then a keying correction.
    nguyen = RollEntry.objects.get(poll=poll, birth_name="Nguyen")
    paper = ballots.enter_paper(poll, str(nguyen.pk), [["a"], ["b"], ["c"]], str(operator.pk), "fr")
    ballots.correct_paper(
        paper,
        [["a"], ["c"], ["b"]],
        str(operator.pk),
        reason=Reason.KEYING_ERROR,
        note="interversion b/c relevée sur le formulaire signé de Nguyen",
    )

    close_poll(poll)
    publish_poll(Poll.objects.get(pk=poll.pk), operator)
    poll = Poll.objects.get(pk=poll.pk)

    # More than a dozen events, spanning open, review, duplicate, ineligibility,
    # paper entry, correction, closure and publication.
    assert AuditEvent.objects.filter(poll=poll).count() >= 8
    _scan_for_identity(AuditEvent.objects.all())

    _age_past_retention(poll)
    purge(poll)

    assert AuditEvent.objects.filter(action=Action.RETENTION_PURGE, poll=poll).exists()
    _scan_for_identity(AuditEvent.objects.all())

    # INV-3 stays absolute — the purge is granted no exception on the log (§10).
    event = AuditEvent.objects.filter(poll=poll).first()
    assert event is not None
    with pytest.raises(Exception, match="INV-3"), transaction.atomic():
        _raw("UPDATE audit_auditevent SET reason = 'other' WHERE id = %s", [event.pk.hex])
