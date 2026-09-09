# SPDX-License-Identifier: 0BSD
"""Screens 1 and 8 of §6.5 — tableau de bord and journal d'audit.

The two screens that read and never write, which is why they land before the
services of §5.1 exist. What they must get right is what they read: turnout from
``Registration.channel`` and never from a ballot count (INV-5), blockers named
before the hour they would fire (§4), and a purged reference rendered as a
deletion rather than as an error (§10).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.models import Action, AuditEvent
from apps.backoffice.dashboard import describe_blocker, participation, permitted_actions
from apps.ballots.models import Ballot, BallotSource, BallotStatus
from apps.core.models import PollRole, Role, User
from apps.elections.models import Poll, PollOption, PollState
from apps.elections.transitions import close_poll, open_poll
from apps.registrations.models import Channel, Registration, RegistrationState


@pytest.fixture
def admin_user(db: None) -> User:
    return User.objects.create_user(username="p.martin", password="x", full_name="P. Martin")


def _grant(poll: Poll, user: User, role: Role) -> None:
    PollRole.objects.create(poll=poll, user=user, role=role)


def _register(poll: Poll, tag: str, *, state: str, channel: str = Channel.NONE) -> Registration:
    return Registration.objects.create(
        poll=poll,
        declared_last_name="Dupont",
        declared_first_names="Émile",
        declared_dob="12/05/1970",
        email=f"{tag}@example.fr",
        email_canonical=f"{tag}@example.fr",
        state=state,
        channel=channel,
    )


# --- Screen 1: tableau de bord (§6.5.1) -------------------------------------


def test_the_dashboard_names_what_would_stop_the_opening(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    """§6.5.1: while in ``draft`` it names every condition that would make
    ``open_poll`` refuse, so a gap is visible before the opening hour (§4)."""
    open_window_poll.languages = ["fr", "en"]
    open_window_poll.save(update_fields=["languages"])
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    body = client.get(f"/fr/mairie/scrutin/{open_window_poll.pk}/").content.decode()
    assert "ne peut pas s'ouvrir" in body
    assert "Traduction manquante en en" in body


def test_the_dashboard_names_the_countersignature_backlog_blocking_closure(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    """§6.5.1 asks for this one in words: *clôture bloquée : n bulletins en
    attente de contreseing*."""
    open_poll(open_window_poll)
    Ballot.objects.create(
        poll=open_window_poll,
        tracking_code="ABCD1234",
        ranking=[["a"], ["b"], ["c"]],
        source=BallotSource.PAPER,
        status=BallotStatus.PENDING_COUNTERSIGN,
    )
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    body = client.get(f"/fr/mairie/scrutin/{open_window_poll.pk}/").content.decode()
    assert "Clôture bloquée" in body
    assert "1 bulletin(s) en attente de contreseing" in body


def test_turnout_is_counted_on_registrations_not_on_ballots(open_window_poll: Poll) -> None:
    """INV-5. The ballots below outnumber the registrations that voted; the
    dashboard must report the registrations, because for an online ballot no
    link to a voter exists at all (§7)."""
    open_poll(open_window_poll)
    _register(open_window_poll, "10000001", state=RegistrationState.ACTIVE, channel=Channel.ONLINE)
    _register(open_window_poll, "10000002", state=RegistrationState.ACTIVE, channel=Channel.PAPER)
    _register(open_window_poll, "10000003", state=RegistrationState.ACTIVE)
    _register(open_window_poll, "10000004", state=RegistrationState.PENDING_REVIEW)
    for index in range(9):
        Ballot.objects.create(
            poll=open_window_poll,
            tracking_code=f"CODE{index:04d}",
            ranking=[["a"], ["b"], ["c"]],
            source=BallotSource.ONLINE,
        )

    counts = participation(open_window_poll)
    assert counts.voted_online == 1
    assert counts.voted_paper == 1
    assert counts.not_voted == 1
    assert counts.confirmed == 3
    assert counts.pending_review == 1
    assert counts.registered == 4
    assert not counts.as_at_closure


def test_a_closed_poll_shows_the_counts_frozen_at_closure(open_window_poll: Poll) -> None:
    """§9, T-58: never re-derived, because the retention purge deletes the
    registrations a fresh count would read (§11)."""
    open_poll(open_window_poll)
    _register(open_window_poll, "20000001", state=RegistrationState.ACTIVE, channel=Channel.ONLINE)
    close_poll(open_window_poll)

    Registration.objects.all().delete()  # what the purge does two months later
    counts = participation(Poll.objects.get(pk=open_window_poll.pk))
    assert counts.as_at_closure
    assert counts.registered == 1
    assert counts.voted_online == 1
    assert counts.confirmed is None


def test_the_dashboard_offers_only_actions_the_operator_holds_the_role_for(
    open_window_poll: Poll, admin_user: User
) -> None:
    """§6.5: offering a link the operator would be refused at is how a
    purpose-built back-office starts to feel like Django admin."""
    open_poll(open_window_poll)
    poll = Poll.objects.get(pk=open_window_poll.pk)

    for_operator = permitted_actions(poll, frozenset({Role.ENTRY_OPERATOR}))
    labels = {str(action.label) for action in for_operator}
    assert "Saisir un bulletin papier" in labels
    assert "Reporter la date de clôture" not in labels

    for_admin = permitted_actions(poll, frozenset({Role.POLL_ADMIN}))
    admin_labels = {str(action.label) for action in for_admin}
    assert "Reporter la date de clôture" in admin_labels
    assert "Saisir un bulletin papier" not in admin_labels


def _countersign_offered(poll: Poll) -> bool:
    return any(
        "Contresigner" in str(action.label)
        for action in permitted_actions(poll, frozenset({Role.ENTRY_OPERATOR}))
    )


def test_the_countersign_action_appears_only_where_it_is_configured(
    open_window_poll: Poll,
) -> None:
    """§6.5.7: the screen is present only where ``paper_requires_countersign``.

    The flag is set before opening because it is frozen configuration (INV-6,
    R-3.3) — the trigger refuses the update on an open poll, which is the
    behaviour, not an obstacle to work around.
    """
    open_poll(open_window_poll)
    assert not _countersign_offered(Poll.objects.get(pk=open_window_poll.pk))

    countersigned = Poll.objects.create(
        title_i18n={"fr": "Avec contreseing"},
        description_i18n={"fr": "Avec contreseing"},
        languages=["fr"],
        opens_at=open_window_poll.opens_at,
        closes_at=open_window_poll.closes_at,
        paper_entry_deadline=open_window_poll.paper_entry_deadline,
        paper_requires_countersign=True,
    )
    for position, option_id in enumerate(["a", "b"]):
        PollOption.objects.create(
            poll=countersigned, option_id=option_id, label_i18n={"fr": option_id}, position=position
        )
    open_poll(countersigned)
    assert _countersign_offered(Poll.objects.get(pk=countersigned.pk))


def test_blocker_codes_become_sentences() -> None:
    """The codes exist so the scheduled commands can log them (§14); this screen
    is where they become something a council member can act on."""
    assert "deux propositions" in describe_blocker("fewer_than_two_options")
    assert "Aucune liste électorale" in describe_blocker("no_roll_to_snapshot")
    assert "proposition « a »" in describe_blocker("missing_translation:option:a:en")
    assert "le titre" in describe_blocker("missing_translation:title:en")
    assert describe_blocker("something_new") == "something_new"


def test_an_entry_operator_reaches_the_dashboard_but_not_the_log(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    _grant(open_window_poll, admin_user, Role.ENTRY_OPERATOR)
    client.force_login(admin_user)
    assert client.get(f"/fr/mairie/scrutin/{open_window_poll.pk}/").status_code == 200
    assert client.get(f"/fr/mairie/scrutin/{open_window_poll.pk}/journal/").status_code == 403


# --- Screen 8: journal d'audit (§6.5.8) -------------------------------------


def test_an_auditor_reads_the_log(client: Client, open_window_poll: Poll, admin_user: User) -> None:
    open_poll(open_window_poll)
    _grant(open_window_poll, admin_user, Role.AUDITOR)
    client.force_login(admin_user)

    body = client.get(f"/fr/mairie/scrutin/{open_window_poll.pk}/journal/").content.decode()
    assert "copie figée prise" in body
    # Autoescaped, as everything rendered from the database must be.
    assert "transition d&#x27;état" in body


def test_consulting_the_log_is_itself_logged(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    """§10's minimum list ends with access to the log itself."""
    _grant(open_window_poll, admin_user, Role.AUDITOR)
    client.force_login(admin_user)
    client.get(f"/fr/mairie/scrutin/{open_window_poll.pk}/journal/?object=bulletin")

    event = AuditEvent.objects.get(action=Action.AUDIT_LOG_ACCESSED)
    assert event.actor == admin_user
    assert event.after["filters"]["object_ref"] == "bulletin"


def test_the_log_filters_by_actor_object_and_date(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    open_poll(open_window_poll)
    _grant(open_window_poll, admin_user, Role.AUDITOR)
    client.force_login(admin_user)
    url = f"/fr/mairie/scrutin/{open_window_poll.pk}/journal/"

    # The snapshot event references the poll; nothing references a ballot.
    assert "copie figée prise" in client.get(f"{url}?object=poll").content.decode()
    assert "copie figée prise" not in client.get(f"{url}?object=ballot").content.decode()

    # Those events were written by no account, so filtering on one drops them.
    filtered = client.get(f"{url}?actor={admin_user.pk}").content.decode()
    assert "copie figée prise" not in filtered

    tomorrow = (timezone.now() + timedelta(days=1)).date().isoformat()
    assert "copie figée prise" not in client.get(f"{url}?date_from={tomorrow}").content.decode()


def test_a_malformed_filter_does_not_break_the_log(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    """A hand-edited query string on a read-only log filters nothing rather
    than returning a 400."""
    open_poll(open_window_poll)
    _grant(open_window_poll, admin_user, Role.AUDITOR)
    client.force_login(admin_user)
    url = f"/fr/mairie/scrutin/{open_window_poll.pk}/journal/"
    response = client.get(f"{url}?actor=pas-un-uuid&date_from=le+trente+février")
    assert response.status_code == 200
    assert "copie figée prise" in response.content.decode()


def test_a_purged_reference_is_rendered_as_a_deletion(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    """§10: a dangling reference is expected, not an error. It is what the
    retention purge leaves behind, and it is what anonymises the log (§11)."""
    open_poll(open_window_poll)
    registration = _register(open_window_poll, "30000001", state=RegistrationState.ACTIVE)
    audit.record(
        action=Action.REGISTRATION_REVIEWED,
        poll=open_window_poll,
        actor=admin_user,
        object_ref=audit.ref(registration),
        after={"state": RegistrationState.ACTIVE},
    )
    _grant(open_window_poll, admin_user, Role.AUDITOR)
    client.force_login(admin_user)
    url = f"/fr/mairie/scrutin/{open_window_poll.pk}/journal/"

    assert "objet supprimé (rétention)" not in client.get(url).content.decode()

    close_poll(Poll.objects.get(pk=open_window_poll.pk))
    registration.delete()  # the retention purge, two months on
    body = client.get(url).content.decode()
    assert "objet supprimé (rétention)" in body
    # The event itself survives: INV-3 has no delete path, purge included.
    assert AuditEvent.objects.filter(action=Action.REGISTRATION_REVIEWED).exists()


def test_the_log_is_scoped_to_its_poll(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    other = Poll.objects.create(
        title_i18n={"fr": "Autre scrutin"},
        description_i18n={"fr": "Autre"},
        languages=["fr"],
        opens_at=open_window_poll.opens_at,
        closes_at=open_window_poll.closes_at,
        paper_entry_deadline=open_window_poll.paper_entry_deadline,
    )
    audit.record(
        action=Action.POLL_CREATED,
        poll=other,
        actor=admin_user,
        object_ref=audit.ref(other),
    )
    _grant(open_window_poll, admin_user, Role.AUDITOR)
    client.force_login(admin_user)

    body = client.get(f"/fr/mairie/scrutin/{open_window_poll.pk}/journal/").content.decode()
    assert "scrutin créé" not in body


def test_the_log_offers_no_way_to_change_anything(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    """R-12.3, INV-3: read-only, and the screen says so."""
    open_poll(open_window_poll)
    _grant(open_window_poll, admin_user, Role.AUDITOR)
    client.force_login(admin_user)
    body = client.get(f"/fr/mairie/scrutin/{open_window_poll.pk}/journal/").content.decode()
    assert "lecture seule" in body
    assert 'method="post"' not in body.split('<form method="get"')[0].split("</header>")[-1]


def test_a_published_poll_still_shows_its_dashboard(
    client: Client, open_window_poll: Poll, admin_user: User
) -> None:
    """The screen must survive every state, including the one where the
    registrations behind its counts no longer exist."""
    open_poll(open_window_poll)
    close_poll(Poll.objects.get(pk=open_window_poll.pk))
    _grant(open_window_poll, admin_user, Role.POLL_ADMIN)
    client.force_login(admin_user)

    poll = Poll.objects.get(pk=open_window_poll.pk)
    assert poll.state == PollState.CLOSED
    response = client.get(f"/fr/mairie/scrutin/{poll.pk}/")
    assert response.status_code == 200
    assert "Chiffres figés à la clôture" in response.content.decode()
