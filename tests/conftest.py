# SPDX-License-Identifier: 0BSD
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.elections.models import Poll, PollOption, WorkingRollEntry


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
