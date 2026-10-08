# SPDX-License-Identifier: 0BSD
"""Every ``aria-describedby`` on a form page names an element that is there (RGAA 11.1).

Django points a field at ``<id>_helptext`` and, once it has errors, at
``<id>_error``. A template that gives the help text or the error another id
leaves the reference dangling and the text unannounced, silently: nothing else
fails. Rendered with errors so both kinds of target are required.
"""

from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser

import pytest
from django.core.cache import cache
from django.test import Client

from apps.elections.models import Poll
from tests.conftest import force_open


class _Ids(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.refs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"] or "")
        self.refs += (values.get("aria-describedby") or "").split()


def _assert_references_resolve(page: str) -> None:
    parsed = _Ids()
    parsed.feed(page)
    assert any(r.endswith("_helptext") for r in parsed.refs), "no help-text reference to check"
    assert any(r.endswith("_error") for r in parsed.refs), "no error reference to check"
    assert [r for r in parsed.refs if r not in parsed.ids] == []
    assert [i for i, n in Counter(parsed.ids).items() if n > 1] == []


def test_the_registration_form_with_errors(open_window_poll: Poll) -> None:
    cache.clear()
    force_open(open_window_poll)
    response = Client().post(
        f"/fr/inscription/{open_window_poll.pk}/", {"last_name": "", "email": "not-an-address"}
    )
    assert response.status_code == 200
    _assert_references_resolve(response.content.decode())


@pytest.mark.django_db
def test_the_first_run_wizard_with_errors() -> None:
    response = Client().post("/fr/mairie/installation/", {"commune_name": ""})
    assert response.status_code == 200
    _assert_references_resolve(response.content.decode())
