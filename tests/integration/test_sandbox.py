# SPDX-License-Identifier: 0BSD
"""Sandbox polls (R-3.7): reachable only through their share link, votable
end to end, and deletable from any state.

INV-8 stays as it was for everything public — no listing, no result, no
statistic (``test_publicsite.py``). What this file pins is the way in that
replaces "nobody can reach it": the link, the voter token, and what happens to
the session when the link changes. And the deletion, which is the one thing
allowed to cut through the INV-2/3/6/7 delete triggers — for a sandbox poll and
for nothing else.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta
from typing import Any

import pytest
from django.core import mail as django_mail
from django.core.cache import cache
from django.db import IntegrityError, connection
from django.db.utils import DatabaseError
from django.test import Client
from django.utils import timezone

from apps.audit.models import Action, AuditEvent
from apps.ballots.models import Ballot, PaperBallotLink
from apps.core.models import PollRole, Role, User
from apps.elections import sandbox, sharelink
from apps.elections.models import Poll, PollOption, PollState, RollEntry, WorkingRollEntry
from apps.registrations.models import Registration
from tests.conftest import force_announce, force_open

FORM = {
    "last_name": "Dupont",
    "first_names": "Émile",
    "date_of_birth": "12/05/1970",
    "email": "emile.dupont@example.fr",
    "declared_on_honour": "on",
}
STRICT = {"order": "a,b,c", "rank_a": "1", "rank_b": "2", "rank_c": "3"}

CaptureOnCommit = Callable[..., AbstractContextManager[list[Any]]]


def _make_poll(*, sandbox_flag: bool) -> Poll:
    now = timezone.now()
    poll = Poll.objects.create(
        title_i18n={"fr": "Essai de la place"},
        description_i18n={"fr": "Trois propositions."},
        languages=["fr"],
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
        is_sandbox=sandbox_flag,
    )
    for position, option_id in enumerate(["a", "b", "c"]):
        PollOption.objects.create(
            poll=poll, option_id=option_id, label_i18n={"fr": option_id.upper()}, position=position
        )
    return poll


@pytest.fixture(autouse=True)
def _roll_and_cache(db: None) -> None:
    cache.clear()
    WorkingRollEntry.objects.create(
        birth_name="Dupont",
        first_names="Émile",
        date_of_birth="12/05/1970",
        date_of_birth_parsed="1970-05-12",
        list_types=["principale"],
    )


@pytest.fixture
def sandbox_poll(db: None) -> Poll:
    poll = _make_poll(sandbox_flag=True)
    force_open(poll)
    poll.refresh_from_db()
    return poll


@pytest.fixture
def real_poll(db: None) -> Poll:
    poll = _make_poll(sandbox_flag=False)
    force_open(poll)
    poll.refresh_from_db()
    return poll


@pytest.fixture
def admin_user(db: None) -> User:
    return User.objects.create_user(username="p.martin", password="x", full_name="P. Martin")


@pytest.fixture
def operator() -> User:
    return User.objects.create_user(username="op", password="x", full_name="Op")


def _link(poll: Poll, operator: User) -> str:
    sharelink.generate(poll, actor=operator)
    poll.refresh_from_db()
    return f"/fr/scrutin/{poll.pk}/apercu/{poll.preview_token}/"


# --- Reaching it (T-15, T-87) ------------------------------------------------


def test_without_the_link_every_voter_facing_page_is_a_404(
    client: Client, sandbox_poll: Poll
) -> None:
    for url in (
        f"/fr/scrutin/{sandbox_poll.pk}/",
        f"/fr/inscription/{sandbox_poll.pk}/",
        f"/fr/inscription/{sandbox_poll.pk}/recu/pending_email/",
        f"/fr/bulletin/{sandbox_poll.pk}/modifier/",
        f"/fr/bulletin/{sandbox_poll.pk}/recu/",
        f"/fr/bulletin/{sandbox_poll.pk}/info/mairie/",
        f"/fr/bulletin/{sandbox_poll.pk}/acces/not-a-token/",
    ):
        assert client.get(url).status_code == 404, url


def test_the_link_serves_the_poll_page_with_registration_and_a_test_notice(
    client: Client, sandbox_poll: Poll, operator: User
) -> None:
    response = client.get(_link(sandbox_poll, operator))
    body = response.content.decode()

    assert response.status_code == 200
    assert "Scrutin d&#x27;essai" in body or "Scrutin d'essai" in body
    assert "Consultation ouverte." in body
    assert f"/fr/inscription/{sandbox_poll.pk}/" in body


def test_the_link_opens_registration_for_that_browser_only(
    client: Client, sandbox_poll: Poll, operator: User
) -> None:
    client.get(_link(sandbox_poll, operator))

    assert client.get(f"/fr/inscription/{sandbox_poll.pk}/").status_code == 200
    assert Client().get(f"/fr/inscription/{sandbox_poll.pk}/").status_code == 404


def test_a_wrong_token_is_a_404_and_grants_nothing(
    client: Client, sandbox_poll: Poll, operator: User
) -> None:
    _link(sandbox_poll, operator)
    assert client.get(f"/fr/scrutin/{sandbox_poll.pk}/apercu/wrong/").status_code == 404
    assert client.get(f"/fr/inscription/{sandbox_poll.pk}/").status_code == 404


def test_regenerating_the_link_ends_the_access_of_those_who_used_the_old_one(
    client: Client, sandbox_poll: Poll, operator: User
) -> None:
    old = _link(sandbox_poll, operator)
    client.get(old)
    assert client.get(f"/fr/inscription/{sandbox_poll.pk}/").status_code == 200

    new = _link(sandbox_poll, operator)

    assert client.get(f"/fr/inscription/{sandbox_poll.pk}/").status_code == 404
    assert client.get(old).status_code == 404
    assert client.get(new).status_code == 200
    assert client.get(f"/fr/inscription/{sandbox_poll.pk}/").status_code == 200


def test_revoking_the_link_ends_access(client: Client, sandbox_poll: Poll, operator: User) -> None:
    url = _link(sandbox_poll, operator)
    client.get(url)
    sharelink.revoke(sandbox_poll, actor=operator)

    assert client.get(f"/fr/inscription/{sandbox_poll.pk}/").status_code == 404
    assert client.get(url).status_code == 404


def test_a_real_poll_link_still_redirects_to_the_public_page(
    client: Client, real_poll: Poll, operator: User
) -> None:
    """R-3.10 bis is unchanged for a poll that is not a sandbox."""
    response = client.get(_link(real_poll, operator))
    assert response.status_code == 302
    assert response["Location"] == f"/fr/scrutin/{real_poll.pk}/"


def test_a_sandbox_link_grants_nothing_on_another_poll(
    client: Client, sandbox_poll: Poll, real_poll: Poll, operator: User
) -> None:
    client.get(_link(sandbox_poll, operator))
    assert client.get(f"/fr/inscription/{real_poll.pk}/").status_code == 200  # public anyway
    other = _make_poll(sandbox_flag=True)
    assert client.get(f"/fr/inscription/{other.pk}/").status_code == 404


def test_a_withdrawn_sandbox_link_shows_only_the_withdrawn_notice(
    client: Client, sandbox_poll: Poll, operator: User
) -> None:
    url = _link(sandbox_poll, operator)
    Poll.objects.filter(pk=sandbox_poll.pk).update(state=PollState.WITHDRAWN)
    body = client.get(url).content.decode()
    assert "retiré" in body
    assert "Essai de la place" not in body


def test_a_sandbox_poll_stays_off_every_public_page_even_with_a_link(
    client: Client, sandbox_poll: Poll, operator: User
) -> None:
    _link(sandbox_poll, operator)
    anonymous = Client()
    assert "Essai de la place" not in anonymous.get("/fr/").content.decode()
    assert anonymous.get(f"/fr/scrutin/{sandbox_poll.pk}/").status_code == 404
    assert anonymous.get(f"/fr/scrutin/{sandbox_poll.pk}/resultats/").status_code == 404


# --- Voting on it, end to end (T-88) -----------------------------------------


def test_a_tester_can_register_and_vote_through_the_link_from_the_mail(
    client: Client,
    sandbox_poll: Poll,
    operator: User,
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    client.get(_link(sandbox_poll, operator))
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(f"/fr/inscription/{sandbox_poll.pk}/", FORM)
    assert response.status_code == 302
    assert client.get(response["Location"]).status_code == 200

    match = re.search(r"/bulletin/[0-9a-f-]+/acces/(\S+?)/", str(django_mail.outbox[0].body))
    assert match, django_mail.outbox[0].body
    # The mail is opened on another device: no share link, no cookie.
    voter = Client()
    cast = voter.post(f"/fr/bulletin/{sandbox_poll.pk}/acces/{match.group(1)}/", STRICT)
    assert cast.status_code == 302
    receipt = voter.get(cast["Location"])
    assert receipt.status_code == 200
    assert "Scrutin d&#x27;essai" in receipt.content.decode() or (
        "Scrutin d'essai" in receipt.content.decode()
    )
    assert Ballot.objects.filter(poll=sandbox_poll).count() == 1


def test_a_wrong_voter_token_on_a_sandbox_poll_reveals_nothing(
    sandbox_poll: Poll,
) -> None:
    response = Client().get(f"/fr/bulletin/{sandbox_poll.pk}/acces/nope/")
    assert response.status_code == 404
    assert "Essai de la place" not in response.content.decode()


# --- Deleting it (T-89, T-90) ------------------------------------------------


def _fill(poll: Poll) -> None:
    """A registration, a cast ballot and a superseded version — everything the
    delete triggers exist to protect."""
    from apps.ballots import services as ballots
    from apps.registrations import services as registrations

    registration, token = registrations.register(poll, FORM, language="fr")
    assert token is not None
    registrations.confirm_mailbox(registration)
    ballots.cast_online(poll, token, [["a"], ["b"], ["c"]])
    ballots.modify(poll, ballots.online_ballot_hash(poll, token), [["c"], ["b"], ["a"]])


def test_deleting_removes_the_poll_and_everything_it_holds(
    sandbox_poll: Poll, operator: User
) -> None:
    _fill(sandbox_poll)
    pk = sandbox_poll.pk
    assert Ballot.objects.filter(poll_id=pk).count() == 2  # live + superseded

    sandbox.delete_poll(sandbox_poll, actor=operator)

    assert not Poll.objects.filter(pk=pk).exists()
    assert not Ballot.objects.filter(poll_id=pk).exists()
    assert not Registration.objects.filter(poll_id=pk).exists()
    assert not RollEntry.objects.filter(poll_id=pk).exists()
    assert not PollOption.objects.filter(poll_id=pk).exists()
    assert not PaperBallotLink.objects.filter(poll_id=pk).exists()


@pytest.mark.parametrize(
    "state", [PollState.DRAFT, PollState.ANNOUNCED, PollState.OPEN, PollState.CLOSED]
)
def test_deletion_works_from_every_state(state: PollState, operator: User) -> None:
    poll = _make_poll(sandbox_flag=True)
    if state == PollState.ANNOUNCED:
        force_announce(poll)
    elif state != PollState.DRAFT:
        force_open(poll)
        _fill(poll)
        if state == PollState.CLOSED:
            Poll.objects.filter(pk=poll.pk).update(state=PollState.CLOSED)
    poll.refresh_from_db()
    assert poll.state == state

    sandbox.delete_poll(poll, actor=operator)

    assert not Poll.objects.filter(pk=poll.pk).exists()


def test_deletion_keeps_the_audit_log_and_adds_its_own_event(
    sandbox_poll: Poll, operator: User
) -> None:
    _fill(sandbox_poll)
    pk = sandbox_poll.pk
    before = AuditEvent.objects.filter(poll_id=pk).count()
    assert before > 0

    sandbox.delete_poll(sandbox_poll, actor=operator)

    events = AuditEvent.objects.filter(poll_id=pk)
    assert events.count() == before + 1
    deleted = events.get(action=Action.POLL_DELETED)
    assert deleted.actor == operator
    assert deleted.before["state"] == "open"
    assert deleted.before["title"] == "Essai de la place"
    assert deleted.object_ref == f"poll:{pk}"


def test_a_real_poll_cannot_be_deleted_by_the_service(real_poll: Poll, operator: User) -> None:
    with pytest.raises(sandbox.NotASandbox):
        sandbox.delete_poll(real_poll, actor=operator)
    assert Poll.objects.filter(pk=real_poll.pk).exists()


def test_the_triggers_still_refuse_every_delete_on_a_real_poll(
    real_poll: Poll, operator: User
) -> None:
    """The exemption is `is_sandbox`, nothing wider: raw SQL against a real poll
    is refused exactly as before, and so is deleting the poll row itself."""
    _fill(real_poll)
    for statement in (
        "DELETE FROM ballots_ballot WHERE poll_id = %s",
        "DELETE FROM registrations_registration WHERE poll_id = %s",
        "DELETE FROM elections_rollentry WHERE poll_id = %s",
    ):
        with pytest.raises(DatabaseError), connection.cursor() as cursor:
            cursor.execute(statement, [real_poll.pk.hex])
    with pytest.raises(DatabaseError), connection.cursor() as cursor:
        cursor.execute("DELETE FROM elections_polloption WHERE poll_id = %s", [real_poll.pk.hex])
    with pytest.raises(DatabaseError), connection.cursor() as cursor:
        cursor.execute("DELETE FROM elections_poll WHERE id = %s", [real_poll.pk.hex])
    with pytest.raises((IntegrityError, DatabaseError)):
        real_poll.delete()


def test_the_audit_log_stays_append_only_after_the_migration(
    sandbox_poll: Poll, operator: User
) -> None:
    sandbox.delete_poll(sandbox_poll, actor=operator)
    with pytest.raises(DatabaseError), connection.cursor() as cursor:
        cursor.execute("DELETE FROM audit_auditevent")
    with pytest.raises(DatabaseError), connection.cursor() as cursor:
        cursor.execute("UPDATE audit_auditevent SET reason = 'other'")


def test_a_sandbox_that_never_got_a_link_or_a_ballot_deletes_too(operator: User) -> None:
    poll = _make_poll(sandbox_flag=True)
    sandbox.delete_poll(poll, actor=operator)
    assert not Poll.objects.filter(pk=poll.pk).exists()


# --- The back-office screen --------------------------------------------------


def _screen(poll: Poll) -> str:
    return f"/fr/mairie/scrutin/{poll.pk}/essai/"


def _grant(poll: Poll, user: User, role: Role) -> None:
    PollRole.objects.create(poll=poll, user=user, role=role)


def test_the_screen_is_a_404_for_a_poll_that_is_not_a_sandbox(
    client: Client, real_poll: Poll, admin_user: User
) -> None:
    _grant(real_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)
    assert client.get(_screen(real_poll)).status_code == 404


def test_the_screen_generates_and_revokes_the_link(
    client: Client, sandbox_poll: Poll, admin_user: User
) -> None:
    _grant(sandbox_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    assert 'value="generate_preview_link"' in client.get(_screen(sandbox_poll)).content.decode()
    client.post(_screen(sandbox_poll), {"action": "generate_preview_link"})
    sandbox_poll.refresh_from_db()
    assert sandbox_poll.preview_token
    body = client.get(_screen(sandbox_poll)).content.decode()
    assert f"/apercu/{sandbox_poll.preview_token}/" in body

    client.post(_screen(sandbox_poll), {"action": "revoke_preview_link"})
    sandbox_poll.refresh_from_db()
    assert sandbox_poll.preview_token == ""


def test_deleting_from_the_screen_needs_the_confirmation_tick(
    client: Client, sandbox_poll: Poll, admin_user: User
) -> None:
    _grant(sandbox_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    client.post(_screen(sandbox_poll), {"action": "delete"})
    assert Poll.objects.filter(pk=sandbox_poll.pk).exists()

    response = client.post(_screen(sandbox_poll), {"action": "delete", "confirm": "yes"})
    assert response.status_code == 302
    assert response["Location"] == "/fr/mairie/"
    assert not Poll.objects.filter(pk=sandbox_poll.pk).exists()
    assert AuditEvent.objects.filter(action=Action.POLL_DELETED, actor=admin_user).exists()


def test_an_auditor_sees_the_screen_but_cannot_act_on_it(
    client: Client, sandbox_poll: Poll, admin_user: User
) -> None:
    _grant(sandbox_poll, admin_user, Role.AUDITOR)
    client.force_login(admin_user)

    body = client.get(_screen(sandbox_poll)).content.decode()
    assert 'value="delete"' not in body
    assert (
        client.post(_screen(sandbox_poll), {"action": "delete", "confirm": "yes"}).status_code
        == 403
    )
    assert Poll.objects.filter(pk=sandbox_poll.pk).exists()


def test_a_commune_admin_without_a_role_is_refused(
    client: Client, sandbox_poll: Poll, admin_user: User
) -> None:
    """`commune_admin` grants nothing on an individual poll."""
    User.objects.filter(pk=admin_user.pk).update(is_commune_admin=True)
    client.force_login(admin_user)
    assert client.get(_screen(sandbox_poll)).status_code == 403
