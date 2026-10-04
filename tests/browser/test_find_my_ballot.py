# SPDX-License-Identifier: 0BSD
"""A voter finds their ballot on the results page (R-11.4), in a real browser.

What the HTTP tests cannot see: the form posting with the ``Origin`` and
referrer a browser sends, the answer brought into view by the action's
fragment, and the answered page passing ``check_page``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page

from apps.audit.models import Reason
from apps.ballots.models import Ballot, BallotSource
from apps.core.models import User
from apps.elections.models import Poll
from apps.elections.transitions import close_poll, publish_poll
from apps.registrations.models import Channel, Registration, RegistrationState
from tests.browser.conftest import check_page
from tests.conftest import _create_open_poll

pytestmark = pytest.mark.browser

CODE = "ABCDEFGHJK"


@pytest.fixture
def published(_flushable_db: None) -> Poll:
    now = timezone.now()
    poll = _create_open_poll(
        title="Aménagement de la place",
        description="Trois propositions pour la place de la mairie.",
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
        roll_name=("Dupont", "Émile", "12/05/1970", "1970-05-12"),
    )
    Registration.objects.create(
        poll=poll,
        declared_last_name="Dupont",
        declared_first_names="Émile",
        email="emile.dupont@example.fr",
        email_canonical="emile.dupont@example.fr",
        state=RegistrationState.ACTIVE,
        channel=Channel.ONLINE,
    )
    Ballot.objects.create(
        poll=poll, tracking_code=CODE, ranking=[["b"], ["a"]], source=BallotSource.ONLINE
    )
    close_poll(poll, early_reason=Reason.ADMINISTRATIVE_DECISION)
    publish_poll(poll, User.objects.create_user(username="p.admin", password="x"))
    return Poll.objects.get(pk=poll.pk)


def test_the_code_as_received_finds_the_ballot(page: Page, published: Poll) -> None:
    results = f"/fr/scrutin/{published.pk}/resultats/"
    page.goto(results)
    page.fill('[name="code"]', "abcde-fghjk")
    page.locator("#retrouver button[type='submit']").click()
    page.wait_for_load_state()

    assert page.url.endswith(f"{results}#retrouver")
    answer = page.locator("#retrouver")
    assert "figure dans la liste publiée" in answer.inner_text()
    assert answer.locator("ol.ranking-summary li").count() == 2
    check_page(page)


def test_a_malformed_code_is_explained_on_the_field(page: Page, published: Poll) -> None:
    page.goto(f"/fr/scrutin/{published.pk}/resultats/")
    page.fill('[name="code"]', "OOOO")
    page.locator("#retrouver button[type='submit']").click()
    page.wait_for_load_state()

    assert page.get_attribute('[name="code"]', "aria-invalid") == "true"
    assert "sans O, 0, I ni 1" in page.locator("#retrouver").inner_text()
    check_page(page)
