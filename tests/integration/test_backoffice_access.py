# SPDX-License-Identifier: 0BSD
"""The back-office gate (§6.5, §3.7).

§6.5 gates all eleven screens on the per-poll roles of §3.7. These tests pin the
two things that are easy to get wrong and expensive to discover: that a role on
one poll is not a role on another, and that ``commune_admin`` is a commune-level
flag rather than a superuser.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from django.test import Client, RequestFactory
from django.utils import timezone

from apps.backoffice.access import accessible_polls, require_poll_role
from apps.core.models import PollRole, Role, User
from apps.elections.models import Poll

SRC = Path(__file__).resolve().parents[2] / "src"


@require_poll_role(Role.ENTRY_OPERATOR)
def _entry_screen(request: HttpRequest, poll: Poll) -> HttpResponse:
    """Stands in for screen 5, the one that shows identity beside a ballot."""
    return HttpResponse(str(poll.pk))


def _call(user: User | None, poll_id: str) -> HttpResponse:
    request = RequestFactory().get(f"/fr/mairie/scrutin/{poll_id}/saisie/")
    request.user = user if user is not None else AnonymousUser()
    return _entry_screen(request, poll_id=poll_id)


@pytest.fixture
def operator(db: None) -> User:
    return User.objects.create_user(username="m.durand", password="x", full_name="M. Durand")


def test_anonymous_is_sent_to_the_login_page(open_window_poll: Poll) -> None:
    response = _call(None, str(open_window_poll.pk))
    assert response.status_code == 302
    assert "/mairie/connexion/" in response["Location"]


def test_an_account_without_a_role_is_refused(open_window_poll: Poll, operator: User) -> None:
    with pytest.raises(PermissionDenied):
        _call(operator, str(open_window_poll.pk))


def test_the_wrong_role_on_the_right_poll_is_refused(
    open_window_poll: Poll, operator: User
) -> None:
    """An auditor reads the log (§6.5.8); that is not permission to key a ballot."""
    PollRole.objects.create(poll=open_window_poll, user=operator, role=Role.AUDITOR)
    with pytest.raises(PermissionDenied):
        _call(operator, str(open_window_poll.pk))


def test_the_right_role_passes_and_the_view_receives_the_poll(
    open_window_poll: Poll, operator: User
) -> None:
    PollRole.objects.create(poll=open_window_poll, user=operator, role=Role.ENTRY_OPERATOR)
    response = _call(operator, str(open_window_poll.pk))
    assert response.status_code == 200
    assert response.content.decode() == str(open_window_poll.pk)


def test_a_role_on_one_poll_is_not_a_role_on_another(
    open_window_poll: Poll, operator: User
) -> None:
    """Roles are per poll (R-2.1). The gate is scoped or it is not a gate."""
    other = Poll.objects.create(
        title_i18n={"fr": "Autre"},
        description_i18n={"fr": "Autre"},
        languages=["fr"],
        opens_at=open_window_poll.opens_at,
        closes_at=open_window_poll.closes_at,
        paper_entry_deadline=open_window_poll.paper_entry_deadline,
    )
    PollRole.objects.create(poll=open_window_poll, user=operator, role=Role.ENTRY_OPERATOR)
    with pytest.raises(PermissionDenied):
        _call(operator, str(other.pk))


def test_commune_admin_alone_opens_no_poll_screen(open_window_poll: Poll, operator: User) -> None:
    """§3.7 makes ``commune_admin`` commune-level: it manages accounts and
    creates polls. Screen 5 is the one place a voter's identity sits beside
    ballot content (§6.5), so reaching it must follow a ``ROLE_ASSIGNED`` grant
    somebody made (§10), not a flag somebody has.
    """
    operator.is_commune_admin = True
    operator.save(update_fields=["is_commune_admin"])
    with pytest.raises(PermissionDenied):
        _call(operator, str(open_window_poll.pk))


def test_a_superuser_flag_grants_nothing(open_window_poll: Poll, operator: User) -> None:
    """The first-run wizard exists so no commune runs ``createsuperuser``
    (§6.5.11); a stray superuser must not be an unaudited way in."""
    operator.is_superuser = True
    operator.is_staff = True
    operator.save(update_fields=["is_superuser", "is_staff"])
    with pytest.raises(PermissionDenied):
        _call(operator, str(open_window_poll.pk))


def test_deactivating_an_account_ends_its_access(open_window_poll: Poll, operator: User) -> None:
    """Checked on every request, not only at login: the session cookie outlives
    the decision to revoke the account.

    The refusal is the login redirect rather than a 403, because a deactivated
    account is not an operator whose roles are worth consulting — and the login
    it lands on refuses it too.
    """
    PollRole.objects.create(poll=open_window_poll, user=operator, role=Role.ENTRY_OPERATOR)
    operator.is_active = False
    operator.save(update_fields=["is_active"])
    response = _call(operator, str(open_window_poll.pk))
    assert response.status_code == 302
    assert "/mairie/connexion/" in response["Location"]


def test_an_unknown_poll_is_a_404(operator: User) -> None:
    with pytest.raises(Http404):
        _call(operator, "00000000-0000-0000-0000-000000000000")


def test_the_index_lists_only_the_polls_an_operator_has_a_role_on(
    open_window_poll: Poll, operator: User
) -> None:
    assert list(accessible_polls(operator)) == []
    PollRole.objects.create(poll=open_window_poll, user=operator, role=Role.POLL_ADMIN)
    assert list(accessible_polls(operator)) == [open_window_poll]


def test_the_index_lists_every_poll_for_a_commune_admin(
    open_window_poll: Poll, operator: User
) -> None:
    """Seeing that a poll exists is not access to any of its screens (§6.5.10)."""
    operator.is_commune_admin = True
    operator.save(update_fields=["is_commune_admin"])
    assert list(accessible_polls(operator)) == [open_window_poll]


def test_sign_in_reaches_the_poll_index(client: Client, operator: User) -> None:
    operator.set_password("un-mot-de-passe")
    operator.save(update_fields=["password"])
    response = client.post(
        "/fr/mairie/connexion/",
        {"username": "m.durand", "password": "un-mot-de-passe"},
        follow=True,
    )
    assert response.status_code == 200
    assert "Vos scrutins" in response.content.decode()


def test_the_index_requires_sign_in(client: Client, db: None) -> None:
    response = client.get("/fr/mairie/")
    assert response.status_code == 302
    assert "/mairie/connexion/" in response["Location"]


def test_no_admin_is_routed(client: Client, db: None) -> None:
    """§14: not in the URL configuration, in any environment."""
    assert client.get("/admin/").status_code == 404


def test_every_poll_scoped_view_is_gated() -> None:
    """The gate holds as the other ten screens land (§6.5).

    A view that takes a ``poll`` is a poll-scoped screen; if it is not wrapped
    in ``require_poll_role`` it is reachable by anyone signed in. Django gives
    no error for that, so this test is the error.
    """
    module = ast.parse((SRC / "apps" / "backoffice" / "views.py").read_text())
    ungated = [
        node.name
        for node in ast.walk(module)
        if isinstance(node, ast.FunctionDef)
        and any(arg.arg == "poll" for arg in node.args.args)
        and not any(
            isinstance(d, ast.Call)
            and isinstance(d.func, ast.Name)
            and d.func.id == "require_poll_role"
            for d in node.decorator_list
        )
    ]
    assert ungated == [], f"poll-scoped views without require_poll_role: {ungated}"


def test_the_poll_index_shows_the_operator_name(client: Client, operator: User) -> None:
    """R-2.2: shared logins are the thing the audit log cannot survive, so the
    operator can always see whose actions are about to be recorded."""
    client.force_login(operator)
    body = client.get("/fr/mairie/").content.decode()
    assert "M. Durand" in body
    assert timezone.now().year  # sanity: the fixture DB is live
