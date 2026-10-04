# SPDX-License-Identifier: 0BSD
"""Finding one's ballot on the results page (R-11.4, review A-7).

The receipt prints a tracking code as ``ABCDE-FGHJK``; the published list holds
``ABCDEFGHJK``, so searching the downloaded file for the code as received found
nothing. The results page now takes the code as typed and answers from the
published document. The code is posted, never put in an address: beside the
visitor's IP in an access log, it would say how that visitor voted.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.audit.models import Reason
from apps.ballots.models import Ballot, BallotSource
from apps.core.models import User
from apps.elections import closure
from apps.elections.models import Poll, PollOption
from apps.elections.transitions import close_poll, publish_poll
from apps.registrations.models import Channel, Registration, RegistrationState
from tests.conftest import force_open

TIED = "ABCDEFGHJK"
STRICT = "23456789AB"


def _poll() -> Poll:
    now = timezone.now()
    poll = Poll.objects.create(
        title_i18n={"fr": "Aménagement de la place"},
        description_i18n={"fr": "Trois propositions."},
        languages=["fr"],
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
        allow_ties_in_ballot=True,
    )
    for position, (option_id, label) in enumerate(
        [("a", "Place minérale"), ("b", "Jardin"), ("c", "Mixte")]
    ):
        PollOption.objects.create(
            poll=poll, option_id=option_id, label_i18n={"fr": label}, position=position
        )
    return force_open(poll)


def _cast(poll: Poll, code: str, ranking: list[list[str]]) -> None:
    Registration.objects.create(
        poll=poll,
        declared_last_name="Dupont",
        declared_first_names="Émile",
        email=f"{code}@example.fr",
        email_canonical=f"{code}@example.fr",
        state=RegistrationState.ACTIVE,
        channel=Channel.ONLINE,
    )
    Ballot.objects.create(
        poll=poll, tracking_code=code, ranking=ranking, source=BallotSource.ONLINE
    )


@pytest.fixture
def published(db: None) -> Poll:
    poll = _poll()
    _cast(poll, TIED, [["b", "c"], ["a"]])
    _cast(poll, STRICT, [["a"], ["b"], ["c"]])
    close_poll(poll, early_reason=Reason.ADMINISTRATIVE_DECISION)
    publish_poll(poll, User.objects.create_user(username="p.admin", password="x"))
    return Poll.objects.get(pk=poll.pk)


def _url(poll: Poll) -> str:
    return f"/fr/scrutin/{poll.pk}/resultats/"


def _answer(body: str) -> str:
    """The lookup block, tags stripped and whitespace collapsed."""
    block = body[body.index('id="retrouver"') : body.index("</form>", body.index('id="retrouver"'))]
    return " ".join(re.sub(r"<[^>]+>", " ", block).split())


def test_the_code_as_printed_on_the_receipt_finds_the_ballot(published: Poll) -> None:
    response = Client().post(_url(published), {"code": " abcde-fghjk "})

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    answer = _answer(response.content.decode())
    assert "Le bulletin ABCDE-FGHJK figure dans la liste publiée" in answer
    assert "Jardin = Mixte Place minérale" in answer


def test_each_rank_is_one_list_item_numbered_by_the_list(published: Poll) -> None:
    body = Client().post(_url(published), {"code": STRICT}).content.decode()
    items = re.findall(r"<li>([^<]*)</li>", body[body.index('id="retrouver"') :])
    assert items[:3] == ["Place minérale", "Jardin", "Mixte"]


def test_a_well_formed_code_the_list_does_not_hold_is_reported(published: Poll) -> None:
    answer = _answer(Client().post(_url(published), {"code": "ZZZZZ-ZZZZZ"}).content.decode())
    assert "Aucun bulletin de la liste publiée ne porte le code ZZZZZ-ZZZZZ" in answer
    assert "figure dans la liste" not in answer


@pytest.mark.parametrize("typed", ["ABCDE-FGHJ", "OBCDEFGHJK", "1BCDEFGHJK", ""])
def test_a_malformed_code_is_refused_with_the_rule(published: Poll, typed: str) -> None:
    body = Client().post(_url(published), {"code": typed}).content.decode()
    assert 'aria-invalid="true"' in body
    assert "figure dans la liste" not in body
    assert "Aucun bulletin de la liste" not in body


def test_the_answer_comes_from_the_published_document(
    published: Poll, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not from ``Ballot``: the voter checks what was published. A ballot the
    document lacks is reported missing, though its row exists. A trigger keeps
    the stored document from being rewritten (R-10.2), so the test hands the
    page one that lost a ballot, as a tampered publication would."""
    document = json.loads(published.published_document or "")
    document["ballots"] = [b for b in document["ballots"] if b["tracking_code"] != STRICT]
    monkeypatch.setattr(closure, "document", lambda poll: document)

    assert Ballot.objects.filter(poll=published, tracking_code=STRICT).exists()
    answer = _answer(Client().post(_url(published), {"code": STRICT}).content.decode())
    assert "Aucun bulletin de la liste publiée" in answer


def test_the_code_reaches_no_address_and_no_log(
    published: Poll, caplog: pytest.LogCaptureFixture
) -> None:
    client = Client()
    page = client.get(_url(published)).content.decode()
    action = re.search(r'<form method="post" action="([^"]+)"', page)
    assert action is not None
    assert action.group(1) == f"{_url(published)}#retrouver"

    with caplog.at_level(logging.DEBUG):
        response = client.post(_url(published), {"code": "abcde-fghjk"})
    assert response.status_code == 200
    assert "ABCDE" not in caplog.text.upper()
    assert "FGHJK" not in caplog.text.upper()


def test_the_form_carries_its_csrf_token(published: Poll) -> None:
    client = Client(enforce_csrf_checks=True)
    page = client.get(_url(published)).content.decode()
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page)
    assert token is not None
    response = client.post(_url(published), {"code": TIED, "csrfmiddlewaretoken": token.group(1)})
    assert response.status_code == 200
    assert "figure dans la liste publiée" in response.content.decode()


def test_a_poll_not_yet_published_answers_nothing(db: None) -> None:
    poll = _poll()
    _cast(poll, TIED, [["a"]])
    close_poll(poll, early_reason=Reason.ADMINISTRATIVE_DECISION)
    assert Client().post(_url(poll), {"code": TIED}).status_code == 404


def test_the_page_alone_shows_the_form_and_no_answer(published: Poll) -> None:
    body = Client().get(_url(published)).content.decode()
    assert 'name="code"' in body
    assert "figure dans la liste" not in body
    assert "Aucun bulletin de la liste" not in body
