# SPDX-License-Identifier: 0BSD
"""Screen 10 of §6.5 — comptes et rôles.

Two things it must get right. The gate is ``require_commune_admin``, not a
per-poll role and not a superuser flag (§3.7). And a role granted or revoked is
on §10's minimum audit list, so each one writes a ``ROLE_ASSIGNED`` /
``ROLE_REVOKED`` event referencing the operator account — staff identity, which
§10 keeps outside the elector-data rule.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.audit.models import Action, AuditEvent
from apps.backoffice.access import has_poll_role
from apps.core.models import PollRole, Role, User
from apps.elections.models import Poll, PollState

ACCOUNTS_URL = "/fr/mairie/comptes/"
ROLES_URL = "/fr/mairie/comptes/roles/"
STRONG_PASSWORD = "corrège-cheval-agrafe-42"


@pytest.fixture
def commune_admin(db: None) -> User:
    return User.objects.create_user(
        username="c.admin", password="x", full_name="C. Admin", is_commune_admin=True
    )


@pytest.fixture
def plain_operator(db: None) -> User:
    return User.objects.create_user(username="m.durand", password="x", full_name="M. Durand")


@pytest.fixture
def admin_client(client: Client, commune_admin: User) -> Client:
    client.force_login(commune_admin)
    return client


# --- the gate (§3.7) -----------------------------------------------------


@pytest.mark.parametrize("url", [ACCOUNTS_URL, ROLES_URL])
def test_anonymous_is_sent_to_the_login_page(client: Client, db: None, url: str) -> None:
    response = client.get(url)
    assert response.status_code == 302
    assert "/mairie/connexion/" in response["Location"]


@pytest.mark.parametrize("url", [ACCOUNTS_URL, ROLES_URL])
def test_a_plain_operator_is_refused(client: Client, plain_operator: User, url: str) -> None:
    """A per-poll role, even every per-poll role, is not commune-level (§3.7)."""
    client.force_login(plain_operator)
    assert client.get(url).status_code == 403


@pytest.mark.parametrize("url", [ACCOUNTS_URL, ROLES_URL])
def test_a_superuser_flag_is_not_consulted(client: Client, db: None, url: str) -> None:
    stray = User.objects.create_user(username="root", password="x")
    stray.is_superuser = True
    stray.is_staff = True
    stray.save(update_fields=["is_superuser", "is_staff"])
    client.force_login(stray)
    assert client.get(url).status_code == 403


@pytest.mark.parametrize("url", [ACCOUNTS_URL, ROLES_URL])
def test_a_commune_admin_reaches_both_screens(admin_client: Client, url: str) -> None:
    assert admin_client.get(url).status_code == 200


# --- accounts (R-2.2) --------------------------------------------------


def test_create_a_named_account_that_can_then_sign_in(admin_client: Client) -> None:
    response = admin_client.post(
        ACCOUNTS_URL,
        {
            "action": "create",
            "username": "p.nouveau",
            "full_name": "P. Nouveau",
            "raw_password": STRONG_PASSWORD,
        },
        follow=True,
    )
    assert response.status_code == 200
    created = User.objects.get(username="p.nouveau")
    assert created.full_name == "P. Nouveau"
    assert not created.is_commune_admin
    assert Client().login(username="p.nouveau", password=STRONG_PASSWORD)


def test_the_commune_admin_flag_is_set_at_creation_when_asked(admin_client: Client) -> None:
    admin_client.post(
        ACCOUNTS_URL,
        {
            "action": "create",
            "username": "p.chef",
            "full_name": "P. Chef",
            "raw_password": STRONG_PASSWORD,
            "is_commune_admin": "on",
        },
    )
    assert User.objects.get(username="p.chef").is_commune_admin


def test_a_duplicate_username_is_refused(admin_client: Client, plain_operator: User) -> None:
    admin_client.post(
        ACCOUNTS_URL,
        {
            "action": "create",
            "username": "m.durand",
            "full_name": "Autre",
            "raw_password": STRONG_PASSWORD,
        },
    )
    assert User.objects.filter(username="m.durand").count() == 1


def test_a_weak_password_is_refused(admin_client: Client) -> None:
    admin_client.post(
        ACCOUNTS_URL,
        {
            "action": "create",
            "username": "p.faible",
            "full_name": "P. Faible",
            "raw_password": "court",
        },
    )
    assert not User.objects.filter(username="p.faible").exists()


def test_deactivating_an_account(admin_client: Client, plain_operator: User) -> None:
    admin_client.post(ACCOUNTS_URL, {"action": "deactivate", "account": str(plain_operator.pk)})
    plain_operator.refresh_from_db()
    assert not plain_operator.is_active

    admin_client.post(ACCOUNTS_URL, {"action": "activate", "account": str(plain_operator.pk)})
    plain_operator.refresh_from_db()
    assert plain_operator.is_active


def test_you_cannot_deactivate_your_own_account(admin_client: Client, commune_admin: User) -> None:
    """Otherwise the operator locks themselves out mid-task."""
    admin_client.post(ACCOUNTS_URL, {"action": "deactivate", "account": str(commune_admin.pk)})
    commune_admin.refresh_from_db()
    assert commune_admin.is_active


def test_the_last_active_commune_admin_cannot_be_demoted(
    admin_client: Client, commune_admin: User
) -> None:
    admin_client.post(ACCOUNTS_URL, {"action": "demote", "account": str(commune_admin.pk)})
    commune_admin.refresh_from_db()
    assert commune_admin.is_commune_admin


def test_promote_then_demote_a_second_admin_is_audited(
    admin_client: Client, plain_operator: User
) -> None:
    admin_client.post(ACCOUNTS_URL, {"action": "promote", "account": str(plain_operator.pk)})
    plain_operator.refresh_from_db()
    assert plain_operator.is_commune_admin
    granted = AuditEvent.objects.get(action=Action.ROLE_ASSIGNED)
    assert granted.poll_id is None
    assert granted.object_ref == f"user:{plain_operator.pk}"
    assert granted.after == {"role": "commune_admin"}

    # A second admin exists now, so this one may go back.
    admin_client.post(ACCOUNTS_URL, {"action": "demote", "account": str(plain_operator.pk)})
    plain_operator.refresh_from_db()
    assert not plain_operator.is_commune_admin
    assert AuditEvent.objects.filter(
        action=Action.ROLE_REVOKED, object_ref=f"user:{plain_operator.pk}"
    ).exists()


def test_resetting_a_password(admin_client: Client, plain_operator: User) -> None:
    admin_client.post(
        ACCOUNTS_URL,
        {
            "action": "set_password",
            "account": str(plain_operator.pk),
            "raw_password": STRONG_PASSWORD,
        },
    )
    assert Client().login(username="m.durand", password=STRONG_PASSWORD)


def test_a_weak_reset_password_is_refused(admin_client: Client, plain_operator: User) -> None:
    admin_client.post(
        ACCOUNTS_URL,
        {"action": "set_password", "account": str(plain_operator.pk), "raw_password": "court"},
    )
    assert not Client().login(username="m.durand", password="court")


def test_an_absent_account_id_is_a_404(admin_client: Client) -> None:
    response = admin_client.post(
        ACCOUNTS_URL,
        {"action": "deactivate", "account": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 404


# --- per-poll roles (R-2.1, §3.7) ------------------------------------


def _sync_payload(poll: Poll, grants: dict[User, list[str]]) -> dict[str, str | list[str]]:
    """Build a POST for the role grid: ``grants`` maps each account whose row
    was in the grid to the roles left ticked on it."""
    payload: dict[str, str | list[str]] = {
        "action": "sync_roles",
        "poll": str(poll.pk),
        "grid_account": [str(account.pk) for account in grants],
    }
    for account, roles in grants.items():
        for role in roles:
            payload[f"role__{account.pk}__{role}"] = "1"
    return payload


def test_granting_a_role_writes_the_row_and_the_event(
    admin_client: Client, open_window_poll: Poll, plain_operator: User
) -> None:
    admin_client.post(ROLES_URL, _sync_payload(open_window_poll, {plain_operator: [Role.AUDITOR]}))
    assert PollRole.objects.filter(
        poll=open_window_poll, user=plain_operator, role=Role.AUDITOR
    ).exists()
    # And the grant is real: the gate lets the account through now.
    assert has_poll_role(plain_operator, open_window_poll, Role.AUDITOR)

    event = AuditEvent.objects.get(action=Action.ROLE_ASSIGNED, poll=open_window_poll)
    assert event.actor_id is not None
    assert event.object_ref == f"user:{plain_operator.pk}"
    assert event.after == {"role": Role.AUDITOR}


def test_granting_the_same_role_twice_is_a_no_op(
    admin_client: Client, open_window_poll: Poll, plain_operator: User
) -> None:
    """Resubmitting the grid with the same box still ticked is not a second
    grant — ``sync_roles`` diffs against what is already granted, so this
    never reaches ``grant_role``'s own idempotence refusal in the first
    place."""
    payload = _sync_payload(open_window_poll, {plain_operator: [Role.ENTRY_OPERATOR]})
    admin_client.post(ROLES_URL, payload)
    admin_client.post(ROLES_URL, payload)
    assert (
        PollRole.objects.filter(
            poll=open_window_poll, user=plain_operator, role=Role.ENTRY_OPERATOR
        ).count()
        == 1
    )
    assigned = AuditEvent.objects.filter(action=Action.ROLE_ASSIGNED, poll=open_window_poll)
    assert assigned.count() == 1


def test_a_role_cannot_be_granted_to_a_deactivated_account(
    admin_client: Client, open_window_poll: Poll, plain_operator: User
) -> None:
    """A deactivated account never appears in the grid (``role_grid`` filters
    to active accounts), so this exercises the belt-and-braces case: a grant
    for it slipped into the POST by hand still hits ``grant_role``'s own
    refusal instead of silently creating the row."""
    plain_operator.is_active = False
    plain_operator.save(update_fields=["is_active"])
    admin_client.post(ROLES_URL, _sync_payload(open_window_poll, {plain_operator: [Role.AUDITOR]}))
    assert not PollRole.objects.filter(poll=open_window_poll, user=plain_operator).exists()


def test_the_grid_lists_only_active_accounts_ticked_with_their_current_roles(
    admin_client: Client, open_window_poll: Poll, plain_operator: User
) -> None:
    PollRole.objects.create(poll=open_window_poll, user=plain_operator, role=Role.POLL_ADMIN)
    inactive = User.objects.create_user(username="d.retire", password="x", is_active=False)

    body = admin_client.get(ROLES_URL, {"scrutin": str(open_window_poll.pk)}).content.decode()
    assert f'name="role__{plain_operator.pk}__{Role.POLL_ADMIN}" value="1" checked' in body
    assert f'name="role__{plain_operator.pk}__{Role.AUDITOR}" value="1" checked' not in body
    assert f"role__{inactive.pk}__" not in body


def test_one_bulk_submission_grants_and_revokes_together(
    admin_client: Client, open_window_poll: Poll, plain_operator: User
) -> None:
    """A submit can tick a new box and untick an old one in the same round
    trip — each still lands as its own audit event (§10)."""
    held = PollRole.objects.create(poll=open_window_poll, user=plain_operator, role=Role.AUDITOR)
    admin_client.post(
        ROLES_URL, _sync_payload(open_window_poll, {plain_operator: [Role.POLL_ADMIN]})
    )
    assert not PollRole.objects.filter(pk=held.pk).exists()
    assert PollRole.objects.filter(
        poll=open_window_poll, user=plain_operator, role=Role.POLL_ADMIN
    ).exists()
    assigned = AuditEvent.objects.filter(action=Action.ROLE_ASSIGNED, poll=open_window_poll)
    assert assigned.count() == 1
    assert AuditEvent.objects.filter(action=Action.ROLE_REVOKED, poll=open_window_poll).count() == 1


def test_a_grid_submission_leaves_out_accounts_untouched(
    admin_client: Client, open_window_poll: Poll, plain_operator: User
) -> None:
    """An account whose row was not part of the submitted grid — deactivated
    after the page was rendered, say — keeps what it holds even though
    ``desired`` says nothing about it."""
    held = PollRole.objects.create(poll=open_window_poll, user=plain_operator, role=Role.AUDITOR)
    other = User.objects.create_user(username="a.autre", password="x")
    admin_client.post(ROLES_URL, _sync_payload(open_window_poll, {other: [Role.POLL_ADMIN]}))
    assert PollRole.objects.filter(pk=held.pk).exists()


def test_unticking_a_role_in_the_grid_removes_it_and_writes_the_event(
    admin_client: Client, open_window_poll: Poll, plain_operator: User
) -> None:
    """The grid is the only way to withdraw a role now that the read-only
    table of existing grants is gone: a submission with the account's row
    present but its box left unticked reaches ``sync_roles`` as a plain
    revoke (§10), same as ``test_one_bulk_submission_grants_and_revokes_
    together`` exercises alongside a grant."""
    grant = PollRole.objects.create(poll=open_window_poll, user=plain_operator, role=Role.AUDITOR)
    admin_client.post(ROLES_URL, _sync_payload(open_window_poll, {plain_operator: []}))
    assert not PollRole.objects.filter(pk=grant.pk).exists()
    event = AuditEvent.objects.get(action=Action.ROLE_REVOKED, poll=open_window_poll)
    assert event.object_ref == f"user:{plain_operator.pk}"
    assert event.before == {"role": Role.AUDITOR}


def test_the_roles_screen_without_a_poll_lists_the_polls(
    admin_client: Client, open_window_poll: Poll
) -> None:
    body = admin_client.get(ROLES_URL).content.decode()
    assert open_window_poll.title() in body


def _second_poll(reference: Poll, *, title: str) -> Poll:
    """A second, unrelated poll — same window as ``reference`` so its shared
    fields don't matter, distinct only in the ``title_i18n`` the list search
    is exercised against."""
    return Poll.objects.create(
        title_i18n={"fr": title},
        description_i18n={"fr": "Sans rapport."},
        languages=["fr"],
        opens_at=reference.opens_at,
        closes_at=reference.closes_at,
        paper_entry_deadline=reference.paper_entry_deadline,
    )


def test_the_poll_list_can_be_searched_by_title(
    admin_client: Client, open_window_poll: Poll
) -> None:
    """The list replacing the old dropdown (views._poll_list_page) narrows by
    a plain substring of the title, run in Python since ``title_i18n`` is
    per-language JSON rather than a column a query can match."""
    other = _second_poll(open_window_poll, title="Autre scrutin")
    body = admin_client.get(ROLES_URL, {"q": "Aménagement"}).content.decode()
    assert open_window_poll.title() in body
    assert other.title() not in body


def test_the_poll_list_can_be_filtered_by_état(
    admin_client: Client, open_window_poll: Poll
) -> None:
    """Both polls sit in ``draft`` fresh out of ``Poll.objects.create`` — the
    état filter excludes them once asked for a state neither is in, without
    needing a real transition to prove the filter works."""
    other = _second_poll(open_window_poll, title="Autre scrutin")
    same_state = admin_client.get(ROLES_URL, {"etat": PollState.DRAFT}).content.decode()
    assert open_window_poll.title() in same_state
    assert other.title() in same_state
    other_state = admin_client.get(ROLES_URL, {"etat": PollState.OPEN}).content.decode()
    assert open_window_poll.title() not in other_state
    assert other.title() not in other_state


def test_an_absent_poll_on_the_roles_screen_is_a_404(admin_client: Client) -> None:
    response = admin_client.get(ROLES_URL, {"scrutin": "00000000-0000-0000-0000-000000000000"})
    assert response.status_code == 404


def test_granting_a_role_is_still_not_access_for_the_commune_admin(
    admin_client: Client, open_window_poll: Poll, commune_admin: User
) -> None:
    """§3.7's split: the commune admin assigns a poll's roles and holds none of
    them. Reaching a poll screen still needs a grant somebody made."""
    assert not has_poll_role(commune_admin, open_window_poll, Role.POLL_ADMIN)
    response = admin_client.get(f"/fr/mairie/scrutin/{open_window_poll.pk}/")
    assert response.status_code == 403
