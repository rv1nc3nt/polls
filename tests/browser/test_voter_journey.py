# SPDX-License-Identifier: 0BSD
"""An elector's whole journey, in a browser: the poll page, registration, the
mailed link, the ballot and the receipt (review C-8). Each page is also
checked for script errors, CSP violations and accessibility (``check_page``).
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

import pytest
from django.core import mail
from django.utils import timezone
from playwright.sync_api import Page

from apps.ballots.models import Ballot
from apps.elections.models import Poll
from tests.browser.conftest import check_page
from tests.conftest import _create_open_poll

pytestmark = pytest.mark.browser


@pytest.fixture
def poll(_flushable_db: None) -> Poll:
    now = timezone.now()
    return _create_open_poll(
        title="Aménagement de la place",
        description="Trois propositions pour la place de la mairie.",
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
        roll_name=("Dupont", "Émile", "12/05/1970", "1970-05-12"),
    )


def test_register_vote_and_read_the_receipt(page: Page, poll: Poll, live_server: Any) -> None:
    page.goto(f"/fr/scrutin/{poll.pk}/")
    check_page(page)

    page.goto(f"/fr/inscription/{poll.pk}/")
    check_page(page)
    page.fill('[name="last_name"]', "Dupont")
    page.fill('[name="first_names"]', "Émile")
    page.fill('[name="date_of_birth"]', "12/05/1970")
    page.fill('[name="email"]', "emile.dupont@example.fr")
    page.check('[name="declared_on_honour"]')
    page.locator('main form button[type="submit"]').click()
    page.wait_for_load_state()
    check_page(page)

    assert len(mail.outbox) == 1
    body = str(mail.outbox[0].body)
    link = re.search(r"/fr/bulletin/[0-9a-f-]+/acces/[^/\s]+/", body)
    assert link, body

    page.goto(link.group(0))
    check_page(page)
    # The language choice is a link here, not set_language's form, whose POST
    # would carry Origin: null from a page that sends no referrer (#51).
    assert page.locator('form[action*="i18n"]').count() == 0
    page.locator('.langswitch a[hreflang="en"]').click()
    page.wait_for_load_state()
    assert "/en/bulletin/" in page.url
    assert page.get_attribute("html", "lang") == "en"
    check_page(page)
    selects = page.locator('select[name^="rank_"]')
    for index in range(selects.count()):
        selects.nth(index).select_option(str(index + 1))
    page.locator("main form button[type=submit]").click()
    page.wait_for_load_state()
    check_page(page)

    ballot = Ballot.objects.get(poll=poll)
    assert re.sub(r"\W", "", ballot.tracking_code) in re.sub(r"\W", "", page.content())
    assert "/acces/" not in page.url  # the token left the address bar (§6.3)
