# SPDX-License-Identifier: 0BSD
"""Every main page type, in a browser, through ``check_page`` (review C-3).

The journeys check the pages a voter and an editor pass through. This visits
the rest, public and espace mairie alike, on an instance with something on
each screen: an open poll with a registration awaiting review, a paper ballot
awaiting countersignature and the trend shown, and a published poll. Each page
must load without a script error or a CSP violation and pass axe's WCAG 2.2 AA
rules; axe finds only part of what a person would, so this is a floor.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from playwright.sync_api import Page

from apps.audit.models import Reason
from apps.ballots import services as ballots
from apps.ballots.models import Ballot, BallotSource
from apps.core.models import PollRole, Role, User
from apps.elections.models import Poll, RollEntry
from apps.elections.transitions import close_poll, publish_poll
from apps.registrations.models import Channel, Registration, RegistrationState
from tests.browser.conftest import check_page
from tests.conftest import _create_open_poll

pytestmark = pytest.mark.browser

PASSWORD = "un mot de passe sûr"
ROLL_NAME = ("Dupont", "Émile", "12/05/1970", "1970-05-12")


def _open_poll(title: str, *, countersign: bool = False) -> Poll:
    now = timezone.now()
    return _create_open_poll(
        title=title,
        description="Trois propositions pour la place de la mairie.",
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
        roll_name=ROLL_NAME,
        paper_requires_countersign=countersign,
    )


@pytest.fixture
def instance(_flushable_db: None, settings: Any) -> dict[str, str]:
    """The ids the page paths need."""
    operator = User.objects.create_user(
        username="m.rousseau", password=PASSWORD, full_name="M. Rousseau", is_commune_admin=True
    )
    keyer = User.objects.create_user(username="k.saisie", password=PASSWORD, full_name="K. Saisie")

    live = _open_poll("Aménagement de la place", countersign=True)
    for role in (Role.POLL_ADMIN, Role.ENTRY_OPERATOR, Role.AUDITOR):
        PollRole.objects.create(poll=live, user=operator, role=role)
    PollRole.objects.create(poll=live, user=keyer, role=Role.ENTRY_OPERATOR)
    Registration.objects.create(
        poll=live,
        declared_last_name="Martin",
        declared_first_names="Claire",
        declared_dob="01/02/1980",
        email="claire.martin@example.fr",
        email_canonical="claire.martin@example.fr",
        state=RegistrationState.PENDING_REVIEW,
    )
    paper = ballots.enter_paper(
        live,
        str(RollEntry.objects.get(poll=live).pk),
        [["a"], ["b"], ["c"]],
        str(keyer.pk),
        "fr",
        identity_confirmed=True,
    )
    settings.TREND_POLL_IDS = frozenset({live.pk})

    published = _open_poll("Horaires de la médiathèque")
    for role in (Role.POLL_ADMIN, Role.AUDITOR):
        PollRole.objects.create(poll=published, user=operator, role=role)
    Registration.objects.create(
        poll=published,
        declared_last_name="Dupont",
        declared_first_names="Émile",
        email="emile.dupont@example.fr",
        email_canonical="emile.dupont@example.fr",
        state=RegistrationState.ACTIVE,
        channel=Channel.ONLINE,
    )
    Ballot.objects.create(
        poll=published,
        tracking_code="ABCDEFGHJK",
        ranking=[["b"], ["a"]],
        source=BallotSource.ONLINE,
    )
    close_poll(published, early_reason=Reason.ADMINISTRATIVE_DECISION)
    publish_poll(Poll.objects.get(pk=published.pk), operator)
    return {"live": str(live.pk), "published": str(published.pk), "paper": str(paper.pk)}


PUBLIC = {
    "poll-list": "/fr/",
    "poll-detail": "/fr/scrutin/{live}/",
    "registration": "/fr/inscription/{live}/",
    "results": "/fr/scrutin/{published}/resultats/",
    "help": "/fr/aide/",
}

BACK_OFFICE = {
    "poll-index": "/fr/mairie/",
    "dashboard": "/fr/mairie/scrutin/{live}/",
    "configuration": "/fr/mairie/scrutin/{live}/configuration/",
    "registration-queue": "/fr/mairie/scrutin/{live}/inscriptions/",
    "roll-status": "/fr/mairie/scrutin/{live}/liste-electorale/",
    "paper-entry": "/fr/mairie/scrutin/{live}/bulletin-papier/",
    "paper-list": "/fr/mairie/scrutin/{live}/bulletins-papier/",
    "paper-ballot": "/fr/mairie/scrutin/{live}/bulletin-papier/{paper}/",
    "paper-receipt": "/fr/mairie/scrutin/{live}/bulletin-papier/{paper}/recu/",
    "countersign": "/fr/mairie/scrutin/{live}/contreseing/",
    "audit-log": "/fr/mairie/scrutin/{live}/journal/",
    "trend": "/fr/mairie/scrutin/{live}/tendance/",
    "closure-publication": "/fr/mairie/scrutin/{published}/depouillement/",
    "accounts": "/fr/mairie/comptes/",
    "roles": "/fr/mairie/comptes/roles/?scrutin={live}",
    "mail-settings": "/fr/mairie/messagerie/",
    "templates": "/fr/mairie/modeles/",
    "commune": "/fr/mairie/commune/",
    "roll-import": "/fr/mairie/liste-electorale/",
    "manual": "/fr/mairie/aide/",
}


@pytest.mark.parametrize("path", PUBLIC.values(), ids=PUBLIC.keys())
def test_a_public_page(page: Page, instance: dict[str, str], path: str) -> None:
    page.goto(path.format(**instance))
    check_page(page)


def test_the_not_found_page(page: Page, instance: dict[str, str]) -> None:
    response = page.goto("/fr/nulle-part/")
    assert response is not None and response.status == 404
    # The browser logs the 404 response itself to the console; that is the
    # page's status, not a script failing on it.
    errors: list[str] = getattr(page, "script_errors")  # noqa: B009
    errors[:] = [e for e in errors if not e.startswith("Failed to load resource")]
    check_page(page)


@pytest.mark.parametrize("path", BACK_OFFICE.values(), ids=BACK_OFFICE.keys())
def test_a_back_office_page(page: Page, instance: dict[str, str], path: str) -> None:
    page.goto("/fr/mairie/connexion/")
    page.fill('[name="username"]', "m.rousseau")
    page.fill('[name="password"]', PASSWORD)
    page.get_by_role("button", name="Se connecter").click()
    page.wait_for_load_state()

    response = page.goto(path.format(**instance))
    assert response is not None and response.status == 200, path
    check_page(page)
