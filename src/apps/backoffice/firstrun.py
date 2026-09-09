# SPDX-License-Identifier: 0BSD
"""First-run wizard — screen 11 of §6.5 (première installation).

The wizard exists so an adopting commune goes from a fresh database to a usable
instance without ``createsuperuser`` (§6.5.11, §14): it creates the commune
record (R-1.3, R-13.1/2) and the initial ``commune_admin`` account in one
transaction, so the two never exist apart.

**Gate.** Every other back-office screen is gated on a role or the commune-admin
flag; this one cannot be, because it runs before any account exists. It is
gated instead on there being *no* usable account — ``is_open()`` — and closes
for good the moment the first one is created. ``access.require_first_run``
enforces that on the view.

**Not audited.** The audit log records what named operators do (§10); there is
no operator yet and no ``Action`` code for "instance installed". This matches
``accounts.create_account``, which is likewise unlogged — adding a vocabulary
term for the staff-account lifecycle is a deliberate change to the audit app,
not something to do in passing here.
"""

from __future__ import annotations

from django.db import transaction

from apps.core.models import Commune, User

from . import accounts


def is_open() -> bool:
    """True while the wizard should still run: no account has been created yet.

    An account is the thing the wizard produces, so its absence is the clean
    signal. A half-built instance with a ``Commune`` row but no account cannot
    occur — ``install`` writes both under one transaction.
    """
    return not User.objects.exists()


@transaction.atomic
def install(
    *,
    commune_name: str,
    data_protection_referent: str,
    data_protection_contact: str,
    username: str,
    full_name: str,
    raw_password: str,
) -> User:
    """Create the commune record and the initial administrator, atomically.

    The form has already checked the password against Django's validators and
    that the two entries match; shape is its job, the write is this one's
    (§6.5: no view writes through the ORM).
    """
    Commune.objects.create(
        name=commune_name,
        data_protection_referent=data_protection_referent,
        data_protection_contact=data_protection_contact,
    )
    return accounts.create_account(
        username=username,
        full_name=full_name,
        raw_password=raw_password,
        is_commune_admin=True,
    )
