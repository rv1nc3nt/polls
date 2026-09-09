# SPDX-License-Identifier: 0BSD
"""Accounts and per-poll roles — the read model and write path of screen 10
(§6.5.10, comptes et rôles).

§6.5 forbids a view from writing through the ORM, so the commune admin's
account and role changes go through here. Two of them are on §10's minimum
list — a role granted, a role revoked — and this module is their only writer,
so the ``ROLE_ASSIGNED`` / ``ROLE_REVOKED`` event is emitted here rather than
left to a view to remember. The commune-admin flag is the one commune-level
role of §3.7, so a change to it is logged the same way, with no ``poll``.

Account creation, the initial password and its later reset are **not** on §10's
list and carry no code in ``audit.models.Action``; they are not logged. Adding a
vocabulary term is a change to the audit app and a decision in its own right,
not something to make in passing while building this screen; if the
staff-account lifecycle should be audited it is a deliberate extension, recorded
there.

``object_ref`` on a role event is ``user:<uuid>`` — a named operator account,
which §10 keeps outside the elector-data rule ("staff identity is different").
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.db.models import Prefetch, QuerySet
from django.utils.translation import gettext_lazy as _

from apps.audit import services as audit
from apps.audit.models import Action
from apps.core.models import PollRole, User
from apps.elections.models import Poll

#: The commune-level role of §3.7. Not a ``Role`` choice — it is a flag on the
#: account — but a grant of it is a "role assignment" for §10's purposes, and it
#: rides the same two events with this label in ``before`` / ``after``.
COMMUNE_ADMIN_ROLE = "commune_admin"


class AccountActionRefused(ValueError):
    """A guard on screen 10 said no: a self-lockout, the last commune admin, or
    a role the account already holds."""


@dataclass(frozen=True)
class AccountRow:
    """One line of the accounts table, with every poll-role the account holds
    already loaded so the template counts no queries."""

    account: User
    roles: list[PollRole]


def accounts() -> list[AccountRow]:
    """Every account, in username order, each with its poll-roles."""
    holdings = PollRole.objects.select_related("poll").order_by("poll__created_at", "role")
    users = User.objects.order_by("username").prefetch_related(
        Prefetch("poll_roles", queryset=holdings)
    )
    return [AccountRow(account=user, roles=list(user.poll_roles.all())) for user in users]


def _active_commune_admins() -> QuerySet[User]:
    return User.objects.filter(is_commune_admin=True, is_active=True)


def _would_orphan_the_commune(exclude: User) -> bool:
    """True where the change under way removes the last usable way into screens
    10 and 11 — a commune with no active administrator cannot make another."""
    return not _active_commune_admins().exclude(pk=exclude.pk).exists()


def create_account(
    *, username: str, full_name: str, raw_password: str, is_commune_admin: bool
) -> User:
    """A new named operator account (R-2.2). The form has already checked the
    username is free and the password strong enough."""
    return User.objects.create_user(
        username=username,
        password=raw_password,
        full_name=full_name,
        is_commune_admin=is_commune_admin,
    )


def set_active(account: User, *, active: bool, actor: User) -> None:
    """Deactivating ends the account's access on its next request (``access``
    checks ``is_active`` there, not only at login). Refused where it would lock
    the actor out of their own session mid-task, or leave the commune with no
    administrator."""
    if not active:
        if account.pk == actor.pk:
            raise AccountActionRefused(_("Vous ne pouvez pas désactiver votre propre compte."))
        if account.is_commune_admin and _would_orphan_the_commune(exclude=account):
            raise AccountActionRefused(
                _("C'est le dernier administrateur de la commune ; il doit en rester un.")
            )
    account.is_active = active
    account.save(update_fields=["is_active"])


@transaction.atomic
def set_commune_admin(account: User, *, flag: bool, actor: User) -> None:
    """Grant or withdraw the commune-level role of §3.7. Logged as a role
    assignment (§10), with no ``poll`` because it is not poll-scoped."""
    if account.is_commune_admin == flag:
        return
    if not flag and _would_orphan_the_commune(exclude=account):
        raise AccountActionRefused(_("Il doit rester au moins un administrateur de la commune."))
    account.is_commune_admin = flag
    account.save(update_fields=["is_commune_admin"])
    audit.record(
        action=Action.ROLE_ASSIGNED if flag else Action.ROLE_REVOKED,
        poll=None,
        actor=actor,
        object_ref=audit.ref(account),
        before={} if flag else {"role": COMMUNE_ADMIN_ROLE},
        after={"role": COMMUNE_ADMIN_ROLE} if flag else {},
    )


def set_password(account: User, *, raw_password: str, actor: User) -> None:
    """Reset an operator's password from the screen — there is no email reset
    (see ``OperatorLoginView``). Not on §10's list, so not logged."""
    account.set_password(raw_password)
    account.save(update_fields=["password"])


def role_holders(poll: Poll) -> list[PollRole]:
    """Who holds which per-poll role on ``poll``, with the granting operator."""
    return list(
        PollRole.objects.filter(poll=poll)
        .select_related("user", "granted_by")
        .order_by("role", "user__username")
    )


@transaction.atomic
def grant_role(poll: Poll, account: User, role: str, *, actor: User) -> PollRole:
    """Assign one per-poll role (R-2.1). Idempotence is a refusal, not a
    silent no-op, so the operator sees why nothing changed. Writes
    ``ROLE_ASSIGNED`` (§10)."""
    if not account.is_active:
        raise AccountActionRefused(
            _("Ce compte est désactivé ; réactivez-le avant de lui attribuer un rôle.")
        )
    grant, created = PollRole.objects.get_or_create(
        poll=poll, user=account, role=role, defaults={"granted_by": actor}
    )
    if not created:
        raise AccountActionRefused(_("Ce compte détient déjà ce rôle sur ce scrutin."))
    audit.record(
        action=Action.ROLE_ASSIGNED,
        poll=poll,
        actor=actor,
        object_ref=audit.ref(account),
        after={"role": role},
    )
    return grant


@transaction.atomic
def revoke_role(grant: PollRole, *, actor: User) -> None:
    """Withdraw one per-poll role. Writes ``ROLE_REVOKED`` (§10); the reference
    is kept even though the row is gone, so the log still reads
    *operator M lost auditor on poll P, by N, at T*."""
    poll, account, role = grant.poll, grant.user, grant.role
    grant.delete()
    audit.record(
        action=Action.ROLE_REVOKED,
        poll=poll,
        actor=actor,
        object_ref=audit.ref(account),
        before={"role": role},
    )
