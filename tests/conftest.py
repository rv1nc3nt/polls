# SPDX-License-Identifier: 0BSD
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.elections.models import Poll, PollOption, WorkingRollEntry
from apps.elections.transitions import open_poll


@pytest.fixture
def open_window_poll(db: None) -> Poll:
    """A poll whose window is open now, with three options and a roll."""
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


@pytest.fixture
def open_paper_poll(open_window_poll: Poll) -> Poll:
    """``open_window_poll`` taken through ``draft → open``: a frozen one-entry
    snapshot, ``opening_seed`` set, keying window sitting on ``closes_at``."""
    open_poll(open_window_poll)
    return Poll.objects.get(pk=open_window_poll.pk)


@pytest.fixture
def paper_poll_countersign(db: None) -> Poll:
    """Open, with ``paper_requires_countersign`` set — which is frozen at
    creation (INV-6), so this cannot be derived from ``open_paper_poll``."""
    now = timezone.now()
    poll = Poll.objects.create(
        title_i18n={"fr": "Contreseing"},
        description_i18n={"fr": "Deux propositions."},
        languages=["fr"],
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
        paper_requires_countersign=True,
    )
    for position, option_id in enumerate(["a", "b", "c"]):
        PollOption.objects.create(
            poll=poll, option_id=option_id, label_i18n={"fr": option_id.upper()}, position=position
        )
    WorkingRollEntry.objects.create(
        birth_name="Martin",
        first_names="Claire",
        date_of_birth="01/01/1980",
        date_of_birth_parsed="1980-01-01",
        list_types=["principale"],
    )
    open_poll(poll)
    return Poll.objects.get(pk=poll.pk)
