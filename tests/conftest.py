# SPDX-License-Identifier: 0BSD
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.models import Action
from apps.core.crypto import new_opening_seed
from apps.elections.models import Poll, PollOption, PollState, RollEntry, WorkingRollEntry


@pytest.fixture
def open_window_poll(db: None) -> Poll:
    """A poll whose window is open now, with three options and a roll.

    Stays ``draft``, so a test can still change its configuration. Every
    ballot or registration write needs the poll ``open`` as well as the clock
    inside the window (§5.1, decision log #33), so a test that writes either
    calls ``force_open`` on it first — announcing requires ``opens_at`` still
    in the future (R-3.10), which this fixture's deliberately-past
    ``opens_at`` cannot satisfy — or uses ``open_paper_poll``.
    """
    now = timezone.now()
    poll = Poll.objects.create(
        title_i18n={"fr": "Aménagement de la place"},
        description_i18n={"fr": "Trois propositions."},
        languages=["fr"],
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
    )
    for position, option_id in enumerate(["a", "b", "c"]):
        PollOption.objects.create(
            poll=poll, option_id=option_id, label_i18n={"fr": option_id.upper()}, position=position
        )
    WorkingRollEntry.objects.create(
        birth_name="Dupont",
        first_names="Émile",
        date_of_birth="12/05/1970",
        date_of_birth_parsed="1970-05-12",
        list_types=["principale"],
    )
    return poll


def force_announce(poll: Poll) -> Poll:
    """Test helper: moves ``poll`` straight to ``announced``, bypassing
    ``announce_poll``'s ``opens_at``-in-the-future guard — for setup where a
    test needs an ``announced`` poll built with a past ``opens_at`` (e.g.
    retention/aging scenarios) and is not itself exercising the announce
    transition. Writes the same ``POLL_STATE_CHANGED`` audit event
    ``_announce_poll_locked`` would, so a test reading the log back sees the
    same trail."""
    previous_state = poll.state
    Poll.objects.filter(pk=poll.pk).update(state=PollState.ANNOUNCED)
    poll.refresh_from_db()
    audit.record(
        action=Action.POLL_STATE_CHANGED,
        poll=poll,
        object_ref=audit.ref(poll),
        before={"state": previous_state},
        after={"state": PollState.ANNOUNCED},
    )
    return poll


def force_open(poll: Poll) -> Poll:
    """Test helper: moves ``poll`` straight to ``open``, applying the same
    state/seed/roll-snapshot side effects ``_open_poll_locked`` would, but
    without going through ``announce_poll``/``open_poll``.

    Test-only: ``announce_poll`` now refuses once ``opens_at`` has passed
    (R-3.10), but a great many fixtures and tests need a poll whose voting
    window is already open, i.e. ``opens_at`` in the past — a combination
    the guarded transition path can no longer produce. A drop-in replacement
    for ``open_poll(poll)`` at call sites that need an already-open poll for
    setup and are not themselves exercising the announce/open transition
    (those call the real functions, with a future ``opens_at``, instead).

    Moves state through the two *legal* trigger edges ``draft → announced →
    open`` via plain ``.update(state=...)`` calls rather than one ``INSERT``
    with ``state=open`` directly, since ``inv6_option_insert_frozen`` would
    otherwise refuse any options inserted afterwards. The trigger only
    encodes which states may follow which; it has no notion of ``opens_at``,
    which is exactly what ``announcing_blockers`` would refuse here.
    (Existing precedent for bypassing the transition functions in test
    setup: ``tests/integration/test_reconciliation.py``'s direct
    ``Poll.objects.filter(pk=...).update(state=...)``.) Writes the same
    ``ROLL_SNAPSHOT_TAKEN``/``POLL_STATE_CHANGED`` audit events
    ``_open_poll_locked`` would, so a test reading the log back (or a
    back-office screen rendering it) sees the same trail.
    """
    force_announce(poll)
    previous_state = poll.state  # always announced, same as the real transition
    entries = [
        RollEntry(
            poll=poll,
            birth_name=e.birth_name,
            usual_name=e.usual_name,
            first_names=e.first_names,
            date_of_birth=e.date_of_birth,
            date_of_birth_parsed=e.date_of_birth_parsed,
            date_uncertain=e.date_uncertain,
            list_types=e.list_types,
        )
        for e in WorkingRollEntry.objects.all().iterator()
    ]
    RollEntry.objects.bulk_create(entries)
    Poll.objects.filter(pk=poll.pk).update(state=PollState.OPEN, opening_seed=new_opening_seed())
    poll.refresh_from_db()
    audit.record(
        action=Action.ROLL_SNAPSHOT_TAKEN,
        poll=poll,
        object_ref=audit.ref(poll),
        after={"row_count": len(entries)},
    )
    audit.record(
        action=Action.POLL_STATE_CHANGED,
        poll=poll,
        object_ref=audit.ref(poll),
        before={"state": previous_state},
        after={"state": PollState.OPEN, "opened_at": timezone.now().isoformat()},
    )
    return poll


def _create_open_poll(
    *,
    title: str,
    description: str,
    opens_at: datetime,
    closes_at: datetime,
    paper_entry_deadline: datetime,
    roll_name: tuple[str, str, str, str],
    option_ids: tuple[str, ...] = ("a", "b", "c"),
    **poll_kwargs: object,
) -> Poll:
    """Builds a poll already ``open`` — roll snapshot, ``opening_seed`` and
    all — without going through ``announce_poll``/``open_poll`` (see
    ``force_open``, which supplies the state/seed/snapshot side effects
    here). Options must be created while the poll is still ``draft``, before
    ``force_open`` moves it on, since ``inv6_option_insert_frozen`` refuses
    inserting them once the poll's state is anything else.
    """
    birth_name, first_names, dob, dob_parsed = roll_name
    poll = Poll.objects.create(
        title_i18n={"fr": title},
        description_i18n={"fr": description},
        languages=["fr"],
        opens_at=opens_at,
        closes_at=closes_at,
        paper_entry_deadline=paper_entry_deadline,
        **poll_kwargs,
    )
    for position, option_id in enumerate(option_ids):
        PollOption.objects.create(
            poll=poll, option_id=option_id, label_i18n={"fr": option_id.upper()}, position=position
        )
    # What a real import would leave behind; some tests count it (CLAUDE.md).
    # force_open's own RollEntry snapshot is taken from this.
    WorkingRollEntry.objects.create(
        birth_name=birth_name,
        first_names=first_names,
        date_of_birth=dob,
        date_of_birth_parsed=dob_parsed,
        list_types=["principale"],
    )
    return force_open(poll)


@pytest.fixture
def open_paper_poll(db: None) -> Poll:
    """A poll already ``open``: frozen one-entry snapshot, ``opening_seed``
    set, keying window sitting on ``closes_at`` — built directly (see
    ``_create_open_poll``), not through ``draft → announced → open``."""
    now = timezone.now()
    return _create_open_poll(
        title="Aménagement de la place",
        description="Trois propositions.",
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
        roll_name=("Dupont", "Émile", "12/05/1970", "1970-05-12"),
    )


@pytest.fixture
def paper_poll_countersign(db: None) -> Poll:
    """Open, with ``paper_requires_countersign`` set — which is frozen at
    creation (INV-6), so this cannot be derived from ``open_paper_poll``."""
    now = timezone.now()
    return _create_open_poll(
        title="Contreseing",
        description="Deux propositions.",
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
        roll_name=("Martin", "Claire", "01/01/1980", "1980-01-01"),
        paper_requires_countersign=True,
    )


@pytest.fixture
def paper_poll_reconciliation_window_open(db: None) -> Poll:
    """Open, with ``paper_requires_reconciliation`` set and the paper window
    still open — for tests that need to seed paper ballots before reconciling,
    or that exercise the premature-entry refusal (§6.4)."""
    now = timezone.now()
    return _create_open_poll(
        title="Rapprochement (fenêtre ouverte)",
        description="Deux propositions.",
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
        roll_name=("Bernard", "Julie", "03/03/1990", "1990-03-03"),
        paper_requires_reconciliation=True,
    )


@pytest.fixture
def paper_poll_reconciliation(db: None) -> Poll:
    """Open, with ``paper_requires_reconciliation`` set (frozen at creation,
    INV-6) and ``paper_entry_deadline`` already passed, so
    ``ballots.services.record_reconciliation`` is immediately callable (R-8.6)."""
    now = timezone.now()
    return _create_open_poll(
        title="Rapprochement",
        description="Deux propositions.",
        opens_at=now - timedelta(days=2),
        closes_at=now - timedelta(hours=1),
        paper_entry_deadline=now - timedelta(hours=1),
        roll_name=("Bernard", "Julie", "03/03/1990", "1990-03-03"),
        paper_requires_reconciliation=True,
    )
