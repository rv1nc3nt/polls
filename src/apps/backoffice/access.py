# SPDX-License-Identifier: 0BSD
"""The gate on every back-office screen (§6.5, §3.7).

§6.5 requires all eleven screens to be "scoped to a poll and gated by the
per-poll roles of §3.7". That is one decision, made here, rather than eleven
ad-hoc checks in eleven views: a screen that forgets the check is a screen that
shows ballots to whoever has the URL, and the failure is silent.

**`commune_admin` is not a superuser.** §3.7 makes `poll_admin`,
`entry_operator` and `auditor` per-poll assignments and `commune_admin` a
commune-level flag — "gère les comptes et crée les scrutins". So the flag opens
the commune-level screens (§6.5.10, §6.5.11) and the poll index, and grants
nothing on any individual poll. A commune admin who needs to key a paper ballot
grants themselves `entry_operator` first, which writes a `ROLE_ASSIGNED` event
(§10). That is the point: screen 5 is the one place where a voter's identity
sits beside ballot content (§6.5), and every access to it should be traceable to
a grant somebody made, not to a flag somebody has.

For the same reason nothing here consults `is_superuser`. The first-run wizard
exists so that an adopting commune never runs `createsuperuser` (§6.5.11), and
a stray superuser must not be an unaudited way into the ballot screens.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps

from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _

from apps.core.models import PollRole, Role, User
from apps.elections.models import Poll

#: A view already past the gate: the poll is resolved and the role is checked.
#: Any further path captures (``ballot_id`` on screens 6–7) are forwarded as
#: keyword arguments, so the signature is left open.
PollView = Callable[..., HttpResponse]
#: What the URL dispatcher calls, with the ``poll_id`` captured from the path.
DispatchedView = Callable[..., HttpResponse]

Account = User | AnonymousUser


def _operator(user: Account) -> User | None:
    """The account, or ``None`` where there is no usable one.

    ``is_active`` is checked here and not only at login: deactivating an account
    must end the session it already has, and ``AuthenticationMiddleware`` will
    otherwise keep loading the user from the session cookie.
    """
    if isinstance(user, User) and user.is_authenticated and user.is_active:
        return user
    return None


def current_operator(request: HttpRequest) -> User:
    """The signed-in operator, for a view already past the gate.

    ``request.user`` is statically ``User | AnonymousUser`` everywhere, but a
    view wrapped in ``require_poll_role`` or ``require_commune_admin`` has
    already been through ``_operator``. This narrows the type without a cast, so
    that if the gate is ever removed from a view the failure is loud here rather
    than an anonymous actor silently landing in the audit log (§10).
    """
    operator = _operator(request.user)
    if operator is None:
        raise PermissionDenied(_("Action réservée à un compte connecté."))
    return operator


def poll_roles(user: Account, poll: Poll) -> frozenset[str]:
    """Every role this account holds on this poll (R-2.1). Empty for anyone else."""
    operator = _operator(user)
    if operator is None:
        return frozenset()
    return frozenset(
        PollRole.objects.filter(poll=poll, user=operator).values_list("role", flat=True)
    )


def has_poll_role(user: Account, poll: Poll, *roles: Role) -> bool:
    """True where the account holds at least one of ``roles`` on ``poll``."""
    return bool(poll_roles(user, poll) & {str(role) for role in roles})


def is_commune_admin(user: Account) -> bool:
    """The commune-level flag of §3.7. Says nothing about any individual poll."""
    operator = _operator(user)
    return operator is not None and operator.is_commune_admin


def accessible_polls(user: Account) -> QuerySet[Poll]:
    """The polls to offer this account after login.

    A commune admin sees every poll, because assigning roles and creating polls
    (§6.5.10) requires knowing what exists. Seeing a poll in this list is not
    access to any of its screens — that still needs a grant.
    """
    operator = _operator(user)
    if operator is None:
        return Poll.objects.none()
    if operator.is_commune_admin:
        return Poll.objects.all()
    return Poll.objects.filter(roles__user=operator).distinct()


def require_poll_role(*roles: Role) -> Callable[[PollView], DispatchedView]:
    """Gate a poll-scoped screen on the per-poll roles of §3.7.

    Resolves ``poll_id`` from the URL, sends an anonymous visitor to the login
    page with a ``next``, refuses an authenticated account without one of
    ``roles``, and hands the view a ``Poll`` so no screen re-fetches it or
    forgets which poll it is scoped to. Any other path captures — ``ballot_id``
    on screens 6 and 7 — are passed straight through as keyword arguments.
    """

    def decorate(view: PollView) -> DispatchedView:
        @wraps(view)
        def wrapper(request: HttpRequest, poll_id: str, **kwargs: object) -> HttpResponse:
            if _operator(request.user) is None:
                return redirect_to_login(request.get_full_path())
            poll = get_object_or_404(Poll, pk=poll_id)
            if not has_poll_role(request.user, poll, *roles):
                raise PermissionDenied(_("Vous n'avez pas le rôle requis sur ce scrutin."))
            return view(request, poll, **kwargs)

        return wrapper

    return decorate


def require_commune_admin(view: DispatchedView) -> DispatchedView:
    """Gate a commune-level screen (§6.5.10, §6.5.11) on the account flag."""

    @wraps(view)
    def wrapper(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        if _operator(request.user) is None:
            return redirect_to_login(request.get_full_path())
        if not is_commune_admin(request.user):
            raise PermissionDenied(_("Réservé à l'administration de la commune."))
        return view(request, *args, **kwargs)

    return wrapper
