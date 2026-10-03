# SPDX-License-Identifier: 0BSD
"""R-10.2: a published result stays reproducible whatever later code does.

Two halves (decision log #41). The tally runs the method version the poll
recorded, chosen from the versions it implements, and refuses any other. And
the artefacts are stored when the poll is published and served from there, so
no later change to the code can restate a published result at all.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import Client
from django.utils import timezone

from apps.audit.models import Reason
from apps.backoffice.forms import PollConfigForm
from apps.ballots.models import Ballot, BallotSource
from apps.core.codes import new_tracking_code
from apps.core.models import PollRole, Role, User
from apps.core.types import OptionId
from apps.elections import closure
from apps.elections.models import Poll, PollOption, PollState, WorkingRollEntry
from apps.elections.transitions import (
    TransitionRefused,
    announcing_blockers,
    close_poll,
    publish_poll,
)
from apps.tally.methods import (
    METHOD_VERSION,
    SELECTABLE_VERSIONS,
    Method,
    UnsupportedMethodVersion,
    tally,
)
from tests.conftest import force_open

BALLOTS = ([["a"], ["b"]], [["a"], ["b"]], [["b"], ["a"]])


def _poll(version: str = METHOD_VERSION, *, opens_in: timedelta = -timedelta(days=1)) -> Poll:
    now = timezone.now()
    poll = Poll.objects.create(
        title_i18n={"fr": "Version"},
        description_i18n={"fr": "R-10.2."},
        languages=["fr"],
        opens_at=now + opens_in,
        closes_at=now + timedelta(days=2),
        paper_entry_deadline=now + timedelta(days=2),
        tally_method_version=version,
    )
    for position, option_id in enumerate("ab"):
        PollOption.objects.create(
            poll=poll, option_id=option_id, label_i18n={"fr": option_id.upper()}, position=position
        )
    return poll


def _closed(version: str = METHOD_VERSION) -> Poll:
    poll = _poll(version)
    WorkingRollEntry.objects.create(
        birth_name="Dupont",
        first_names="Émile",
        date_of_birth="12/05/1970",
        date_of_birth_parsed="1970-05-12",
        list_types=["principale"],
    )
    force_open(poll)
    for ranking in BALLOTS:
        Ballot.objects.create(
            poll=poll,
            tracking_code=new_tracking_code(),
            ranking=ranking,
            source=BallotSource.ONLINE,
        )
    close_poll(poll, early_reason=Reason.ADMINISTRATIVE_DECISION)
    return Poll.objects.get(pk=poll.pk)


@pytest.fixture
def admin(db: None) -> User:
    return User.objects.create_user(username="v.admin", password="x")


# --- the tally runs the recorded version, or refuses --------------------------


def test_the_tally_refuses_a_version_it_does_not_implement() -> None:
    options = [OptionId("a"), OptionId("b")]
    with pytest.raises(UnsupportedMethodVersion):
        tally([], options, Method.SCHULZE, version="2")
    assert tally([], options, Method.SCHULZE, version="1").method_version == "1"


def test_the_form_offers_only_selectable_versions() -> None:
    field = PollConfigForm.base_fields["tally_method_version"]
    assert [value for value, _label in field.choices] == list(SELECTABLE_VERSIONS)  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        field.clean("v1")


@pytest.mark.django_db
def test_a_poll_recording_an_unknown_version_cannot_be_announced() -> None:
    """Announcing freezes the version (INV-6): it must be caught while the
    poll is still a draft, where it can be corrected."""
    poll = _poll("9", opens_in=timedelta(days=1))
    assert "unsupported_method_version" in announcing_blockers(poll)
    assert "unsupported_method_version" not in announcing_blockers(
        _poll(opens_in=timedelta(days=1))
    )


@pytest.mark.django_db
def test_a_closed_poll_with_an_unknown_version_is_neither_tallied_nor_published(
    client: Client, admin: User
) -> None:
    """A version this release does not know, as after a downgrade, and not a
    pre-check label (no ``legacy_tallied_as``): never tallied under another
    version's rules (#52)."""
    poll = _closed("9")
    PollRole.objects.create(poll=poll, user=admin, role=Role.POLL_ADMIN)
    client.force_login(admin)

    body = client.get(f"/fr/mairie/scrutin/{poll.pk}/depouillement/").content.decode()
    assert "« 9 »" in body
    with pytest.raises(TransitionRefused) as refused:
        publish_poll(poll, admin)
    assert refused.value.blockers == ["unsupported_method_version"]


# --- the published artefacts are stored and served as stored -----------------


@pytest.mark.django_db
def test_publication_stores_exactly_what_it_serves(client: Client, admin: User) -> None:
    poll = _closed()
    expected_document = closure.serialise_document(closure.publication(poll))
    expected_csv = closure.published_csv(poll)

    publish_poll(poll, admin)
    poll.refresh_from_db()

    assert poll.published_document == expected_document
    assert poll.published_csv == expected_csv
    base = f"/fr/scrutin/{poll.pk}/resultats/"
    assert client.get(base + "?format=json").content.decode() == expected_document
    assert client.get(base + "?format=csv").content.decode() == expected_csv


@pytest.mark.django_db
def test_a_later_change_to_the_tally_does_not_restate_a_published_result(
    client: Client, admin: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The point of R-10.2: once published, what the code would compute now
    no longer matters to anything a reader sees."""
    poll = _closed()
    publish_poll(poll, admin)
    poll.refresh_from_db()
    stored = json.loads(poll.published_document or "")
    assert stored["winner"] == "a"

    def restated(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("a published result was recomputed")

    monkeypatch.setattr(closure, "publication", restated)
    monkeypatch.setattr(closure, "tallied", restated)
    base = f"/fr/scrutin/{poll.pk}/resultats/"
    assert json.loads(client.get(base + "?format=json").content)["winner"] == "a"
    assert client.get(base).status_code == 200
    PollRole.objects.create(poll=poll, user=admin, role=Role.POLL_ADMIN)
    client.force_login(admin)
    assert client.get(f"/fr/mairie/scrutin/{poll.pk}/depouillement/").status_code == 200


@pytest.mark.django_db
def test_the_stored_artefacts_cannot_be_rewritten(admin: User) -> None:
    """Write-once, held by the database (migration 0015), not by the code."""
    poll = _closed()
    publish_poll(poll, admin)
    for column in ("published_document", "published_csv"):
        with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cur:
            cur.execute(
                f"UPDATE elections_poll SET {column} = 'rewritten' WHERE id = %s",  # noqa: S608
                [poll.pk.hex],
            )
    poll.refresh_from_db()
    assert poll.published_document and "rewritten" not in poll.published_document


# --- polls published before the artefacts were stored --------------------------


def _published_without_artefacts(version: str = METHOD_VERSION) -> Poll:
    """A poll as it stood when published by earlier code: published, nothing
    stored. ``closed → published`` is a legal edge, so only the stored
    artefacts are missing."""
    poll = _closed(version)
    Poll.objects.filter(pk=poll.pk).update(state=PollState.PUBLISHED)
    return Poll.objects.get(pk=poll.pk)


@pytest.mark.django_db
def test_freeze_publications_stores_what_a_legacy_poll_was_serving() -> None:
    poll = _published_without_artefacts()
    serving = closure.serialise_document(closure.publication(poll))

    call_command("freeze_publications")
    poll.refresh_from_db()
    assert poll.published_document == serving

    call_command("freeze_publications")  # idempotent
    poll.refresh_from_db()
    assert poll.published_document == serving


@pytest.mark.django_db
def test_a_legacy_poll_with_an_unknown_version_is_frozen_as_published_under_version_1(
    client: Client,
) -> None:
    """Before the check, every poll was tallied under version 1 whatever its
    field said: that is what readers downloaded, and what is stored."""
    poll = _published_without_artefacts("9")
    _as_migration_0018_leaves_it(poll)
    call_command("freeze_publications")
    poll.refresh_from_db()

    document = json.loads(poll.published_document or "")
    assert document["tally_method_version"] == "1"
    assert document["winner"] == "a"
    response = client.get(f"/fr/scrutin/{poll.pk}/resultats/?format=json")
    assert json.loads(response.content) == document


def _as_migration_0018_leaves_it(poll: Poll) -> None:
    """A poll frozen before versions were checked, under a label naming none."""
    Poll.objects.filter(pk=poll.pk).update(legacy_tallied_as="1")
    poll.refresh_from_db()


# --- legacy and retired versions (decision log #52) ---------------------------


@pytest.mark.django_db
def test_a_closed_poll_frozen_before_the_check_publishes_under_version_1(
    client: Client, admin: User
) -> None:
    """Its free-text label was never read: version 1 is what it was always
    going to be tallied under, and what its publication says."""
    poll = _closed("v1.0")
    _as_migration_0018_leaves_it(poll)
    PollRole.objects.create(poll=poll, user=admin, role=Role.POLL_ADMIN)
    client.force_login(admin)

    body = client.get(f"/fr/mairie/scrutin/{poll.pk}/depouillement/").content.decode()
    assert "« v1.0 »" not in body
    published = publish_poll(poll, admin)
    document = json.loads(published.published_document or "")
    assert document["tally_method_version"] == "1"
    assert document["winner"] == "a"
    assert published.tally_method_version == "v1.0"  # the frozen label is kept


@pytest.mark.django_db
def test_a_retired_version_cannot_be_announced_but_still_runs(
    monkeypatch: pytest.MonkeyPatch, admin: User
) -> None:
    """Retiring takes a version out of SELECTABLE_VERSIONS only: no new poll
    takes it, and a poll that already recorded it opens, closes and publishes
    under it."""
    from apps.elections import transitions

    draft = _poll(opens_in=timedelta(days=1))
    poll = _closed()
    monkeypatch.setattr(transitions, "SELECTABLE_VERSIONS", ())
    assert "unsupported_method_version" in announcing_blockers(draft)
    assert "unsupported_method_version" not in transitions.opening_blockers(poll)
    published = publish_poll(poll, admin)
    assert json.loads(published.published_document or "")["tally_method_version"] == "1"


@pytest.mark.django_db
def test_a_template_seeds_only_a_selectable_version(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.elections import polltemplates
    from apps.elections.models import PollTemplate

    template = PollTemplate.objects.create(name="Ancien", tally_method_version="v1.0")
    assert polltemplates.scalars(template)["tally_method_version"] == METHOD_VERSION
    template = PollTemplate.objects.create(name="Retirée", tally_method_version="1")
    monkeypatch.setattr(polltemplates, "SELECTABLE_VERSIONS", ())
    monkeypatch.setattr(polltemplates, "METHOD_VERSION", "2")
    assert polltemplates.scalars(template)["tally_method_version"] == "2"


@pytest.mark.django_db
def test_migration_0018_marks_only_frozen_polls_with_unknown_labels() -> None:
    import importlib

    from django.apps import apps

    migration = importlib.import_module("apps.elections.migrations.0018_legacy_tallied_as")
    draft = _poll("v1.0", opens_in=timedelta(days=1))
    known = _closed()
    legacy = _closed("v1.0")
    migration.mark_legacy_labels(apps, None)
    for poll, expected in ((draft, None), (known, None), (legacy, "1")):
        poll.refresh_from_db()
        assert poll.legacy_tallied_as == expected, poll.tally_method_version


@pytest.mark.django_db
def test_the_poll_table_keeps_its_triggers_through_migration_0018() -> None:
    """The column is nullable so SQLite adds it in place: a rebuild would
    have dropped these."""
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'elections_poll'"
        )
        triggers = {name for (name,) in cursor.fetchall()}
    assert triggers >= {
        "inv3_poll_commitments_write_once",
        "inv3_poll_no_delete",
        "inv3_poll_publication_write_once",
        "inv6_poll_config_frozen",
        "poll_state_irreversible",
    }
