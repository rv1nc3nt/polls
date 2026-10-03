# SPDX-License-Identifier: 0BSD
"""The espace mairie's own scripts, in a browser (review C-8): signing in, the
configuration screen's tabs and proposition editor, and the "Lire la suite"
dialog of the draft preview. Each page is checked as in the voter journey.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page

from apps.core.models import PollRole, Role, User
from apps.elections.models import Poll, PollOption
from tests.browser.conftest import check_page

pytestmark = pytest.mark.browser

PASSWORD = "un mot de passe sûr"


@pytest.fixture
def draft(_flushable_db: None) -> Poll:
    now = timezone.now()
    poll = Poll.objects.create(
        title_i18n={"fr": "Salle polyvalente"},
        description_i18n={"fr": "Où construire la salle."},
        languages=["fr"],
        opens_at=now + timedelta(days=7),
        closes_at=now + timedelta(days=14),
        paper_entry_deadline=now + timedelta(days=14),
    )
    long_text = "Un paragraphe **en gras** et [un lien](https://example.org). " * 30
    for position, option_id in enumerate(["nord", "sud"]):
        PollOption.objects.create(
            poll=poll,
            option_id=option_id,
            label_i18n={"fr": f"Site {option_id}"},
            details_i18n={"fr": f"## Détail\n\n{long_text}"},
            position=position,
        )
    user = User.objects.create_user(username="j.mercier", password=PASSWORD, full_name="J. Mercier")
    PollRole.objects.create(poll=poll, user=user, role=Role.POLL_ADMIN)
    return poll


def test_sign_in_add_a_proposition_and_read_the_preview(page: Page, draft: Poll) -> None:
    page.goto("/fr/mairie/connexion/")
    check_page(page)
    page.fill('[name="username"]', "j.mercier")
    page.fill('[name="password"]', PASSWORD)
    page.get_by_role("button", name="Se connecter").click()
    page.wait_for_load_state()
    check_page(page)

    page.goto(f"/fr/mairie/scrutin/{draft.pk}/configuration/")
    page.locator('[aria-controls="cfg-options"], [href="#cfg-options"]').first.click()
    check_page(page)
    rows = page.locator("[data-option-rows] [data-option-row]")
    before = rows.count()  # the two stored, and the formset's blank extras
    page.locator("[data-option-add-button]").click()
    row = rows.last
    expected = f"opt-{before}-option_id"
    assert row.locator('[name$="-option_id"]').get_attribute("name") == expected
    assert page.evaluate("document.activeElement.name") == expected
    assert page.input_value("#id_opt-TOTAL_FORMS") == str(before + 1)
    row.locator('[name$="-option_id"]').fill("centre")
    row.locator('[name$="-label_fr"]').fill("Site centre")
    page.locator('#cfg-options button:has-text("Enregistrer la configuration")').click()
    page.wait_for_load_state()
    check_page(page)
    assert list(draft.options.values_list("option_id", flat=True)) == ["nord", "sud", "centre"]

    page.goto(f"/fr/mairie/scrutin/{draft.pk}/apercu/")
    check_page(page)
    page.locator("button.option-details-more").first.click()
    dialog = page.locator("dialog.details-dialog[open]")
    assert dialog.locator(".details-dialog__body h2").count() == 1
    assert dialog.locator(".details-dialog__body a[href='https://example.org']").count() == 30
    check_page(page)
